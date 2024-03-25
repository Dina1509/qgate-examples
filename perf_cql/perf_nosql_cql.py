from enum import Enum
import datetime
import numpy

from cassandra import ConsistencyLevel
from cassandra.cluster import ExecutionProfile
from cassandra.cluster import EXEC_PROFILE_DEFAULT
from cassandra.policies import DCAwareRoundRobinPolicy
from cassandra.query import BatchStatement

from qgate_perf.parallel_executor import ParallelExecutor
from qgate_perf.parallel_probe import ParallelProbe
from qgate_perf.run_setup import RunSetup
from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import Cluster

from dotenv import load_dotenv, dotenv_values
from ssl import PROTOCOL_TLSv1_2, PROTOCOL_TLSv1, SSLContext, CERT_NONE, CERT_REQUIRED


class CQLType(Enum):
    ScyllaDB = 1
    Cassandra = 2
    AstraDB = 3
    CosmosDB = 4


def read_file(file) -> str:
    with open(file) as f:
        return f.readline()

def prf_cql(run_setup: RunSetup) -> ParallelProbe:
    generator = numpy.random.default_rng()  #seed=int(time.time())
    columns, items="", ""
    authProvider=None

    # connection setting
    if run_setup['username']:
        authProvider = PlainTextAuthProvider(username=run_setup["username"],
                                             password=read_file(run_setup["password"]))

    if run_setup["secure_connect_bundle"]:
        # connection with 'secure_connect_bundle' to the cloud
        cloud_config = {
            "secure_connect_bundle" : run_setup["secure_connect_bundle"],
            'use_default_tempdir': True
        }
        cluster = Cluster(cloud = cloud_config,
                          auth_provider=authProvider,
                          execution_profiles={EXEC_PROFILE_DEFAULT: ExecutionProfile(request_timeout=30)},
                          control_connection_timeout=30,
                          idle_heartbeat_interval=30,
                          connect_timeout=30)
    else:
        # ssl_opts = {
        #     'ca_certs': 'C:\Python\qgate-examples\secrets\public-key.pem',
        #     'ssl_version': PROTOCOL_TLSv1_2,
        #     'cert_reqs': CERT_REQUIRED  # Certificates are required and validated
        # }
        #
        # ssl_context = SSLContext(PROTOCOL_TLSv1_2)
        # ssl_context.verify_mode = CERT_NONE

        # connection with 'ip' and 'port'
        cluster = Cluster(contact_points=run_setup['ip'],
                          port=run_setup['port'],
                          auth_provider=authProvider,
                          execution_profiles={EXEC_PROFILE_DEFAULT: ExecutionProfile(request_timeout=30)},
                          control_connection_timeout=30,
                          idle_heartbeat_interval=30,
                          connect_timeout=30)

    if run_setup.is_init:
        # create NoSQL schema
        prepare_model(cluster, run_setup)
        return None

    try:
        session = cluster.connect()

        # INIT - contain executor synchronization, if needed
        probe = ParallelProbe(run_setup)

        # prepare insert statement for batch
        for i in range(0, run_setup.bulk_col):
            columns+=f"fn{i},"
            items+="?,"
        insert_statement = session.prepare(f"INSERT INTO {run_setup['keyspace']}.t02 ({columns[:-1]}) VALUES ({items[:-1]})")
        if run_setup['cql']==CQLType.AstraDB:
            # not support CL.ONE see error "Provided value ONE is not allowed for Write Consistency Level (disallowed values are: [ANY, ONE, LOCAL_ONE]"
            batch = BatchStatement(consistency_level=ConsistencyLevel.QUORUM)
        else:
            batch = BatchStatement(consistency_level=ConsistencyLevel.ONE)

        while True:
            batch.clear()

            # generate synthetic data (only 1 mil. values for insert or update)
            synthetic_data = generator.integers(999999, size=(run_setup.bulk_row, run_setup.bulk_col))

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
        if cluster:
            cluster.shutdown()

    return probe

def prepare_model(cluster, run_setup: RunSetup):

    try:
        session = cluster.connect()
        columns=""

        if run_setup["cql"]!=CQLType.AstraDB:

            # Drop key space
            session.execute(f"DROP KEYSPACE IF EXISTS {run_setup['keyspace']}")

            # Create key space
            # use different replication strategy 'class':'NetworkTopologyStrategy' for production HA mode
            #            session.execute("CREATE KEYSPACE IF NOT EXISTS jist2 WITH replication = {'class':'NetworkTopologyStrategy', 'replication_factor' : 3};")
            session.execute(f"CREATE KEYSPACE IF NOT EXISTS {run_setup['keyspace']}" + " WITH replication = {" + "'class':'SimpleStrategy', 'replication_factor' : 1" + "};")

        # use LTW atomic command with IF
        session.execute(f"DROP TABLE IF EXISTS {run_setup['keyspace']}.t02")

        # prepare insert statement for batch
        for i in range(0, run_setup.bulk_col):
            columns+=f"fn{i} int,"

        # complex primary key (partition key 'fn0' and cluster key 'fn1')
        session.execute(f"CREATE TABLE IF NOT EXISTS {run_setup['keyspace']}.t02 ({columns[:-1]}, PRIMARY KEY (fn0, fn1))")

    finally:
        if cluster:
            cluster.shutdown()

def perf_test(cql: CQLType, parameters: dict, duration=5, bulk_list=None, executor_list=None):

    lbl=""
    if cql==CQLType.ScyllaDB:
        lbl="Scylla"
    elif cql==CQLType.Cassandra:
        lbl = "Cassandra"
    elif cql==CQLType.AstraDB:
        lbl = "AstraDB"
    elif cql==CQLType.CosmosDB:
        lbl = "CosmosDB"

    generator = ParallelExecutor(prf_cql,
                                 label=lbl,
                                 detail_output=True,
                                 output_file=f"../output/prf_{lbl.lower()}-{datetime.date.today()}.txt",
                                 init_each_bulk=True)

    parameters["cql"]=cql
    setup = RunSetup(duration_second=duration, start_delay=0, parameters=parameters)
    generator.run_bulk_executor(bulk_list, executor_list, run_setup=setup)
    generator.create_graph_perf(f"..\output")

def get_config(config, adapter):
    param={}
    param['keyspace']=config["KEYSPACE"]

    if config[adapter].lower() == "on":
        # connection setting
        if config.get(f"{adapter}_IP", None):
            param["ip"]=[config[f"{adapter}_IP"]]
        if config.get(f"{adapter}_PORT", None):
            param["port"]=config[f"{adapter}_PORT"]
        if config.get(f"{adapter}_SECURE_CONNECT_BUNDLE", None):
            param["secure_connect_bundle"]=config[f"{adapter}_SECURE_CONNECT_BUNDLE"]

        # login setting
        if config.get(f"{adapter}_USERNAME", None):
            param['username'] = config[f"{adapter}_USERNAME"]
            param['password'] = config[f"{adapter}_PASSWORD"]

        # replication setting
        if config.get(f"{adapter}_REPLICATION_CLASS", None):
            param['replication_class'] = config[f"{adapter}_REPLICATION_CLASS"]
            param['replication_factor'] = config[f"{adapter}_REPLICATION_FACTOR"]

        return param
    else:
        return None

if __name__ == '__main__':

    # size of data bulks
    bulks = [[200, 10]]

    # list of executors (for application to all bulks)
    executors = [[2, 2, '2x threads'],
                 [4, 2, '2x threads'],
                 [16, 2, '2x threads']]
#    executors = [[1, 1, '1x threads']]

    # performance test duration
    duration_seconds=5

    config = dotenv_values("perf_nosql_cql.env")

    # if config['REPLICATION_CLASS'].lower() == "on":
    #     config['REPLICATION_FACTOR


    param=get_config(config, 'COSMOSDB')
    if param:
    # if config['COSMOSDB'].lower() == "on":
    #     param["ip"]=[config["COSMOSDB_IP"]]
    #     param["port"]=config["COSMOSDB_PORT"]
    #     if config.get('COSMOSDB_USERNAME', None):
    #         param['username'] = config['COSMOSDB_USERNAME']
    #         param['password'] = config['COSMOSDB_PASSWORD']
    #     if config.get('COSMOSDB_REPLICATION_CLASS', None):
    #         param['replication_class'] = config['COSMOSDB_REPLICATION_CLASS']
    #         param['replication_factor'] = config['COSMOSDB_REPLICATION_FACTOR']
        perf_test(CQLType.CosmosDB,
                  param,
                  bulk_list=bulks,
                  duration=duration_seconds,
                  executor_list=executors)

    param=get_config(config, 'SCYLLADB')
    if param:
    # if config['SCYLLADB'].lower() == "on":
    #     param["ip"]=[config["SCYLLADB_IP"]]
    #     param["port"]=config["SCYLLADB_PORT"]
    #     if config.get('SCYLLADB_USERNAME',None):
    #         param['username'] = config['SCYLLADB_USERNAME']
    #         param['password'] = config['SCYLLADB_PASSWORD']
        perf_test(CQLType.ScyllaDB,
                  param,
                  duration=duration_seconds,
                  bulk_list=bulks,
                  executor_list=executors)

    param=get_config(config, 'CASSANDRA')
    if param:
    # if config['CASSANDRA'].lower() == "on":
    #     param["ip"]=[config["CASSANDRA_IP"]]
    #     param["port"]=config["CASSANDRA_PORT"]
    #     if config.get('CASSANDRA_USERNAME', None):
    #         param['username'] = config['CASSANDRA_USERNAME']
    #         param['password'] = config['CASSANDRA_PASSWORD']
        perf_test(CQLType.Cassandra,
                  param,
                  duration=duration_seconds,
                  bulk_list=bulks,
                  executor_list=executors)

    param=get_config(config, 'ASTRADB')
    if param:
    # if config['ASTRADB'].lower() == "on":
    #
    #     param["secure_connect_bundle"]=config["ASTRADB_SECURE_CONNECT_BUNDLE"]
    #     if config.get('ASTRADB_USERNAME', None):
    #         param['username'] = config['ASTRADB_USERNAME']
    #         param['password'] = config['ASTRADB_PASSWORD']
        perf_test(CQLType.AstraDB,
                  param,
                  bulk_list=bulks,
                  duration=duration_seconds,
                  executor_list=executors)

