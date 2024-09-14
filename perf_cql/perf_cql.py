import datetime, time
import os.path
import numpy
from cassandra.query import BatchStatement, BoundStatement
from qgate_perf.parallel_executor import ParallelExecutor
from qgate_perf.parallel_probe import ParallelProbe
from qgate_perf.run_setup import RunSetup
from dotenv import dotenv_values
from cql_config import CQLConfig, CQLType, CQLGraph
from cql_access import CQLAccess, Setting
from colorama import Fore, Style
import cql_helper
from cql_health import CQLHealth, CQLDiagnosePrint
import click


def prf_readwrite(run_setup: RunSetup) -> ParallelProbe:
    # TODO: Add readwrite operations
    pass

def prf_read(run_setup: RunSetup) -> ParallelProbe:
    generator = cql_helper.get_rng_generator()
    columns, items="", ""
    cql = None
    session = None

    if run_setup.is_init:
        return None

    try:
        cql = CQLAccess(run_setup)
        cql.open()
        session = cql.create_session()

        # INIT - contains executor synchronization, if needed
        probe = ParallelProbe(run_setup)

        # prepare select statement
        for i in range(0, run_setup.bulk_col):
            columns+=f"fn{i},"

        for i in range(0, run_setup.bulk_row):
            items+="?,"

        select_statement = session.prepare(f"SELECT {columns[:-1]} FROM {run_setup['keyspace']}.{Setting.TABLE_NAME} WHERE fn0 IN ({items[:-1]}) and fn1 IN ({items[:-1]})")
        bound = BoundStatement(select_statement, consistency_level=run_setup['consistency_level'])

        while True:

            # generate synthetic data
            #  NOTE: It will generate only values for two columns (as primary keys), not for all columns
            synthetic_data = generator.integers(Setting.MAX_GNR_VALUE, size=run_setup.bulk_row*2)

            # prepare data
            bound.bind(synthetic_data)

            # START - probe, only for this specific code part
            probe.start()

            rows = session.execute(bound)

            # STOP - probe
            if probe.stop():
                break
    finally:
        if session:
            session.shutdown()
        if cql:
            cql.close()
    return probe

def prf_write(run_setup: RunSetup) -> ParallelProbe:
    generator = cql_helper.get_rng_generator()
    columns, items = "", ""
    cql = None
    session = None

    if run_setup.is_init:
        # create schema for write data
        try:
            cql = CQLAccess(run_setup)
            cql.open()
            cql.create_model()
        finally:
            if cql:
                cql.close()
        return None

    try:
        cql = CQLAccess(run_setup)
        cql.open()
        session = cql.create_session()

        # INIT - contains executor synchronization, if needed
        probe = ParallelProbe(run_setup)

        # prepare insert statement for batch
        for i in range(0, run_setup.bulk_col):
            columns+=f"fn{i},"
            items+="?,"
        insert_statement = session.prepare(f"INSERT INTO {run_setup['keyspace']}.{Setting.TABLE_NAME} ({columns[:-1]}) VALUES ({items[:-1]})")
        batch = BatchStatement(consistency_level=run_setup['consistency_level'])

        while True:
            batch.clear()

            # generate synthetic data
            synthetic_data = generator.integers(Setting.MAX_GNR_VALUE, size=(run_setup.bulk_row, run_setup.bulk_col))

            # prepare data
            for row in synthetic_data:
                batch.add(insert_statement, row)

            # START - probe, only for this specific code part
            probe.start()

            session.execute(batch)

            # STOP - probe
            if probe.stop():
                break
    finally:
        if session:
            session.shutdown()
        if cql:
            cql.close()

    return probe

def cluster_diagnose(run_setup, level):

    cql = None
    try:
        level = CQLDiagnosePrint[level.lower()]
        if level == CQLDiagnosePrint.off:
            return

        cql = CQLAccess(run_setup)
        cql.open()
        status = CQLHealth(cql.cluster)
        status.diagnose(level)
    finally:
        if cql:
            cql.close()

def generate_graphs(generator:ParallelExecutor, global_param):
    """Generate graph based on setting"""

    level = CQLGraph[global_param['generate_graph'].lower()]
    if level == CQLGraph.perf:
        print("Generate graph: performance...")
        generator.create_graph_perf(os.path.join(global_param['perf_dir'],"../output"), suppress_error = True)
    elif level == CQLGraph.exe:
        print("Generate graph: execution...")
        generator.create_graph_exec(os.path.join(global_param['perf_dir'],"../output"), suppress_error = True)
    elif level == CQLGraph.all:
        print("Generate graph: performance & execution...")
        generator.create_graph(os.path.join(global_param['perf_dir'], "../output"), suppress_error=True)
    else:
        print("Generate graph: Off")


def perf_test(cql: CQLType, unique_id, global_param, parameters: dict, only_cluster_diagnose = False):

    lbl = str(cql).split('.')[1]
    lbl_suffix = f"{parameters['label']}" if parameters.get('label', None) else ""

    generator = None
    if parameters['test_type']=='w':    # WRITE perf test
        generator = ParallelExecutor(prf_write,
                                     label=f"{lbl}{unique_id}-W{lbl_suffix}",
                                     detail_output=global_param['detail_output'],
                                     output_file=os.path.join(global_param['perf_dir'],f"../output/prf_{lbl.lower()}-W{lbl_suffix.lower()}-{datetime.date.today()}.txt"),
                                     init_each_bulk=True)
    elif parameters['test_type']=='r':  # READ perf test
        generator = ParallelExecutor(prf_read,
                                     label=f"{lbl}{unique_id}-R{lbl_suffix}",
                                     detail_output=global_param['detail_output'],
                                     output_file=os.path.join(global_param['perf_dir'],f"../output/prf_{lbl.lower()}-R{lbl_suffix.lower()}-{datetime.date.today()}.txt"),
                                     init_each_bulk=True)
    # TODO: Add read & write
    # elif parameters['test_type']=='rw' or parameters['test_type']=='wr':    # READ & WRITE perf test
    #     generator = ParallelExecutor(prf_cql_readwrite(),
    #                                  label=f"{lbl}-read{lbl_suffix}",
    #                                  detail_output=True,
    #                                  output_file=f"../output/prf_{lbl.lower()}-write{lbl_suffix.lower()}-{datetime.date.today()}.txt",
    #                                  init_each_bulk=True)

    parameters["cql"] = cql

    # run tests & generate graphs
    setup = RunSetup(duration_second = global_param['executor_duration'],
                     start_delay = global_param['executor_start_delay'],
                     parameters = parameters)

    cluster_diagnose(setup, global_param['cluster_diagnose'])
    if global_param['cluster_diagnose_only']:
        return

    generator.run_bulk_executor(parameters['bulk_list'],
                                global_param['executors'],
                                run_setup = setup)

    generate_graphs(generator, global_param)
    #generator.create_graph_perf(os.path.join(global_param['perf_dir'],"../output"), suppress_error = True)

def exec_config(config, unique_id, global_param):

    param = CQLConfig(config).get_params('COSMOSDB', global_param)
    if param:
        perf_test(CQLType.CosmosDB,
                  unique_id,
                  global_param,
                  param)

    param = CQLConfig(config).get_params('SCYLLADB', global_param)
    if param:
        perf_test(CQLType.ScyllaDB,
                  unique_id,
                  global_param,
                  param)

    param = CQLConfig(config).get_params('CASSANDRA', global_param)
    if param:
        perf_test(CQLType.Cassandra,
                  unique_id,
                  global_param,
                  param)

    param = CQLConfig(config).get_params('ASTRADB', global_param)
    if param:
        perf_test(CQLType.AstraDB,
                  unique_id,
                  global_param,
                  param)

def main_execute(env="cass.env", perf_dir=".", only_cluster_diagnose = False, level = "short"):

    global_param = CQLConfig(dotenv_values(os.path.join(perf_dir, "config", env))).get_global_params()
    if global_param:
        # multiple configurations
        unique_id = "-" + datetime.datetime.now().strftime("%H%M%S")
        envs = [env.strip() for env in global_param['multiple_env'].split(",")]
        global_param['perf_dir'] = perf_dir
        env_count = 0
        for env in envs:
            if not env.lower().endswith(".env"):
                env += ".env"
            env_count += 1
            print(Fore.LIGHTGREEN_EX + f"Environment switch {env_count}/{len(envs)}: '{env}' ..." + Style.RESET_ALL)
            if env_count > 1:
                time.sleep(global_param['multiple_env_delay'])
            if only_cluster_diagnose:
                global_param['cluster_diagnose'] = level
                global_param['cluster_diagnose_only'] = True
            exec_config(dotenv_values(os.path.join(perf_dir, "config", env)),
                        unique_id,
                        global_param)
    else:
        print("Missing 'MULTIPLE_ENV' configuration")

@click.group()
def diagnose_group():
    pass

@diagnose_group.command()
@click.option("-e", "--env", help="name of ENV file (default 'cass.env')", default="cass.env")
@click.option("-d", "--perf_dir", help="directory with perf_cql (default '.')", default=".")
@click.option("-l", "--level", help="level of diagnose, acceptable values 'short', 'full', 'extra' (default 'short')", default="short")
def diagnose(env, perf_dir, level):
    """Run only diagnostic for connection based on ENV file."""
    main_execute(env, perf_dir, True, level)

@click.group()
def run_group():
    pass

@run_group.command()
@click.option("-e", "--env", help="name of ENV file (default 'cass.env')", default="cass.env")
@click.option("-d", "--perf_dir", help="directory with perf_cql (default '.')", default=".")
def run(env, perf_dir):
    """Run performance tests based on ENV file."""
    main_execute(env, perf_dir)

cli = click.CommandCollection(sources=[run_group, diagnose_group])

if __name__ == '__main__':
    cli()
