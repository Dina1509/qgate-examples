import datetime, time
import cassandra.query
import numpy
from cassandra.query import BatchStatement, BoundStatement
from qgate_perf.parallel_executor import ParallelExecutor
from qgate_perf.parallel_probe import ParallelProbe
from qgate_perf.run_setup import RunSetup
from dotenv import load_dotenv, dotenv_values
from cql_config import CQLConfig, CQLType
from cql_access import CQLAccess, Setting


def init_rng_generator():
    """Init generator of random values"""

    # now
    now = time.time()
    now_ms = (now - int(now)) * 1000000000

    # random value, based on CPU
    ns_start = time.perf_counter_ns()
    time.sleep(0.01)
    ns_stop = time.perf_counter_ns()

    return numpy.random.default_rng([int(now), int(now_ms), ns_stop - ns_start, ns_stop])

def prf_cql_read(run_setup: RunSetup) -> ParallelProbe:
    generator = init_rng_generator()
    columns, items="", ""

    try:
        cql = CQLAccess(run_setup)
        cql.open()

        # INIT - contain executor synchronization, if needed
        probe = ParallelProbe(run_setup)

        # prepare select statement for batch
        for i in range(0, run_setup.bulk_col):
            columns+=f"fn{i},"
        select_statement = cql.session.prepare(f"SELECT {columns[:-1]} FROM {run_setup['keyspace']}.{Setting.TABLE_NAME} WHERE fn0=? and fn1=?")
        bound = cassandra.query.BoundStatement(select_statement, consistency_level=run_setup['consistency_level'])

        while True:

            # generate synthetic data
            #  NOTE: It will generate only values for two columns (as primary keys), not for all columns
            synthetic_data = generator.integers(Setting.MAX_GNR_VALUE, size=(run_setup.bulk_row, 2))

            # START - probe, only for this specific code part
            probe.start()

            # prepare data
            for row in synthetic_data:
                bound.bind(row)
                cql.session.execute(bound)

            # STOP - probe
            if probe.stop():
                break
    finally:
        if cql:
            cql.close()

    return probe

def prf_cql_write(run_setup: RunSetup) -> ParallelProbe:
    generator = init_rng_generator()
    columns, items = "", ""

    if run_setup.is_init:
        # create NoSQL schema for write perf tests
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

        # INIT - contain executor synchronization, if needed
        probe = ParallelProbe(run_setup)

        # prepare insert statement for batch
        for i in range(0, run_setup.bulk_col):
            columns+=f"fn{i},"
            items+="?,"
        insert_statement = cql.session.prepare(f"INSERT INTO {run_setup['keyspace']}.{Setting.TABLE_NAME} ({columns[:-1]}) VALUES ({items[:-1]})")
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

            cql.session.execute(batch)

            # STOP - probe
            if probe.stop():
                break
    finally:
        if cql:
            cql.close()

    return probe

def perf_test(cql: CQLType, parameters: dict, duration=5, bulk_list=None, executor_list=None):

    lbl = str(cql).split('.')[1]
    lbl_suffix = f"-{parameters['label']}" if parameters.get('label', None) else ""

    if parameters['test_type']=='W':    # WRITE perf test
        generator = ParallelExecutor(prf_cql_write,
                                     label=f"{lbl}-write{lbl_suffix}",
                                     detail_output=True,
                                     output_file=f"../output/prf_{lbl.lower()}-write{lbl_suffix.lower()}-{datetime.date.today()}.txt",
                                     init_each_bulk=True)
    elif parameters['test_type']=='R':    # READ perf test
        generator = ParallelExecutor(prf_cql_read(),
                                     label=f"{lbl}-read{lbl_suffix}",
                                     detail_output=True,
                                     output_file=f"../output/prf_{lbl.lower()}-write{lbl_suffix.lower()}-{datetime.date.today()}.txt",
                                     init_each_bulk=True)
    # TODO: Add read & write
    # elif parameters['test_type']=='RW' or parameters['test_type']=='WR':    # READ & WRITE perf test
    #     generator = ParallelExecutor(prf_cql_read(),
    #                                  label=f"{lbl}-read{lbl_suffix}",
    #                                  detail_output=True,
    #                                  output_file=f"../output/prf_{lbl.lower()}-write{lbl_suffix.lower()}-{datetime.date.today()}.txt",
    #                                  init_each_bulk=True)


    parameters["cql"] = cql

    # run tests & generate graphs
    setup = RunSetup(duration_second=duration, start_delay=0, parameters=parameters)
    generator.run_bulk_executor(bulk_list, executor_list, run_setup=setup)
    generator.create_graph_perf("../output", suppress_error = True)

def exec_config(config, bulks, duration_seconds, executors):

    param = CQLConfig(config, 'COSMOSDB').get_params()
    if param:
        perf_test(CQLType.CosmosDB,
                  param,
                  bulk_list=bulks,
                  duration=duration_seconds,
                  executor_list=executors)

    param = CQLConfig(config, 'SCYLLADB').get_params()
    if param:
        perf_test(CQLType.ScyllaDB,
                  param,
                  duration=duration_seconds,
                  bulk_list=bulks,
                  executor_list=executors)

    param = CQLConfig(config, 'CASSANDRA').get_params()
    if param:
        perf_test(CQLType.Cassandra,
                  param,
                  duration=duration_seconds,
                  bulk_list=bulks,
                  executor_list=executors)

    param = CQLConfig(config, 'ASTRADB').get_params()
    if param:
        perf_test(CQLType.AstraDB,
                  param,
                  bulk_list=bulks,
                  duration=duration_seconds,
                  executor_list=executors)

if __name__ == '__main__':

    # size of data bulks, requested format [[rows, columns], ...]
    bulks = [[200, 10]]

    # list of executors (for application to all bulks)
    # executors = [[2, 1, '1x threads'], [4, 1, '1x threads'], [8, 1, '1x threads'],
    #              [2, 2, '2x threads'], [4, 2, '2x threads'], [8, 2, '2x threads']]
    #
    executors = [[2, 1, '1x threads'], [4, 1, '1x threads'], [8, 1, '1x threads'], [16, 1, '1x threads'],
                 [2, 2, '2x threads'], [4, 2, '2x threads'], [8, 2, '2x threads'], [16, 2, '2x threads']]

    #executors = [[2, 2, '1x threads'], [4, 2, '1x threads']]

    # performance test duration
    duration_seconds=5

    config = dotenv_values("config/perf_nosql_cql.env")
    param=config.get('MULTIPLE_ENV', None)
    if param:
        # multiple configurations
        envs=config["MULTIPLE_ENV"].split(",")
        for env in envs:
            exec_config(dotenv_values(env.strip()), bulks, duration_seconds, executors)
    else:
        # single configuration
        exec_config(config, bulks, duration_seconds, executors)
