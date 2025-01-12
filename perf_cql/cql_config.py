from cassandra import ConsistencyLevel
from ast import literal_eval
from enum import Enum
from os import path
import cql_helper


class CQLType(Enum):
    ScyllaDB = 1
    Cassandra = 2
    AstraDB = 3
    CosmosDB = 4

class ConsistencyHelper:
    name_to_value = {
    'ANY': ConsistencyLevel.ANY,
    'ONE': ConsistencyLevel.ONE,
    'TWO': ConsistencyLevel.TWO,
    'THREE': ConsistencyLevel.THREE,
    'QUORUM': ConsistencyLevel.QUORUM,
    'ALL': ConsistencyLevel.ALL,
    'LOCAL_QUORUM': ConsistencyLevel.LOCAL_QUORUM,
    'LOCAL_ONE': ConsistencyLevel.LOCAL_ONE,
    'LOCAL_SERIAL': ConsistencyLevel.LOCAL_SERIAL,
    'EACH_QUORUM': ConsistencyLevel.EACH_QUORUM,
    'SERIAL': ConsistencyLevel.SERIAL,
    }

class CQLConfigSetting:

    # The key parameters
    EXECUTOR_DURATION = "5"
    BULK_LIST = "[[200, 10]]"
    BULK_LIST_W = "[[200, 10]]"
    BULK_LIST_R = "[[1, 10]]"
    EXECUTORS = "[[1, 1, '1x threads'], [2, 1, '1x threads']]"

    # The other tuning
    EXECUTOR_START_DELAY = "0"
    DETAIL_OUTPUT = "True"
    GENERATE_GRAPH = "Perf"
    CLUSTER_DIAGNOSE = "Short"
    MULTIPLE_ENV_DELAY = "0"

    KEYSPACE = "prftest"
    TEST_TYPE = "W"
    REPLICATION_CLASS = "NetworkTopologyStrategy"
    REPLICATION_FACTOR = "3"
    CONSISTENCY_LEVEL = "LOCAL_QUORUM"
    LB_LOCAL_DC = "datacenter1"
    USERNAME = "cassandra"
    PASSWORD = "cassandra"
    PORT = "9042"
    IP = "localhost"
    LABEL = "local"

class CQLConfig:

    def __init__(self, config = {}):
        self._config = config

    def _inherit_param_eval(self, param_name, global_param, global_param_name, param_name_default = None, adapter = None):
        """Get adapter from single or from global ENV"""
        if adapter:
            param_name=f"{adapter}_{param_name}"

        if self._config.get(param_name, None):
            return literal_eval(self._config[param_name])
        else:
            # inheritance of param from global_param
            if global_param:
                if global_param.get(global_param_name, None):
                    return global_param[global_param_name]
            return param_name_default


    def _inherit_param(self, param_name, global_param, global_param_name, param_name_default = None, adapter = None):
        """Get adapter from single or from global ENV"""

        if adapter:
            param_name=f"{adapter}_{param_name}"

        if self._config.get(param_name, None):
            return self._config[param_name]
        else:
            # inheritance of param from global_param
            if global_param:
                if global_param.get(global_param_name, None):
                    return global_param[global_param_name]
            return param_name_default

    def get_global_params(self, force_default = False):

        global_param={}

        # shared params for all providers
        global_param['multiple_env'] = self._config.get('MULTIPLE_ENV', None)
        if global_param['multiple_env'] or force_default:
            # multiple configurations

            global_param['executors'] = literal_eval(self._config.get("EXECUTORS", CQLConfigSetting.EXECUTORS))
            global_param['detail_output'] = cql_helper.str2bool(self._config.get('DETAIL_OUTPUT', CQLConfigSetting.DETAIL_OUTPUT))
            global_param['generate_graph'] = self._config.get('GENERATE_GRAPH', CQLConfigSetting.GENERATE_GRAPH)
            global_param['executor_duration'] = int(self._config.get('EXECUTOR_DURATION', CQLConfigSetting.EXECUTOR_DURATION))
            global_param['executor_start_delay'] = int(self._config.get('EXECUTOR_START_DELAY', CQLConfigSetting.EXECUTOR_START_DELAY))
            global_param['cluster_diagnose'] = self._config.get("CLUSTER_DIAGNOSE", CQLConfigSetting.CLUSTER_DIAGNOSE)
            global_param['cluster_diagnose_only'] = False
            global_param['keyspace'] = self._config.get("KEYSPACE", CQLConfigSetting.KEYSPACE)
            global_param['bulk_list_r'] = literal_eval(self._config.get("BULK_LIST_R", CQLConfigSetting.BULK_LIST_R))
            global_param['bulk_list_w'] = literal_eval(self._config.get("BULK_LIST_W", CQLConfigSetting.BULK_LIST_W))
            global_param['multiple_env_delay'] = int(self._config.get('MULTIPLE_ENV_DELAY', CQLConfigSetting.MULTIPLE_ENV_DELAY))
            return global_param
        else:
            return None

    def get_params(self, adapter, global_param):
        param={}

        if cql_helper.str2bool(self._config.get(adapter, "Off")):
            # shared params for all providers
            param['test_type'] = self._config.get("TEST_TYPE", CQLConfigSetting.TEST_TYPE).lower()
            if param['test_type'] == "r":
                param['bulk_list'] = self._inherit_param_eval("BULK_LIST", global_param,'bulk_list_r', CQLConfigSetting.BULK_LIST_R)
            else:
                param['bulk_list'] = self._inherit_param_eval("BULK_LIST", global_param,'bulk_list_w', CQLConfigSetting.BULK_LIST_W)
            param['keyspace'] = self._inherit_param("KEYSPACE", global_param, "keyspace", CQLConfigSetting.KEYSPACE)

            # connection setting
            param["ip"] = self._config.get(f"{adapter}_IP", CQLConfigSetting.IP).split(",")
            param["port"] = self._config.get(f"{adapter}_PORT", CQLConfigSetting.PORT)
            if self._config.get(f"{adapter}_SECURE_CONNECT_BUNDLE", None):
                param["secure_connect_bundle"] = self._config[f"{adapter}_SECURE_CONNECT_BUNDLE"]

            # login setting
            param['username'] = self._config.get(f"{adapter}_USERNAME", CQLConfigSetting.USERNAME)
            if self._config.get(f"{adapter}_PASSWORD", None):
                param['password'] = cql_helper.read_file(path.join(global_param['perf_dir'], self._config[f"{adapter}_PASSWORD"]))
            else:
                param['password'] = CQLConfigSetting.PASSWORD

            # replication setting
            param['replication_class'] = self._config.get(f"{adapter}_REPLICATION_CLASS", CQLConfigSetting.REPLICATION_CLASS)
            param['replication_factor'] = self._config.get(f"{adapter}_REPLICATION_FACTOR", CQLConfigSetting.REPLICATION_FACTOR)

            # compaction
            if self._config.get(f"{adapter}_COMPACTION", None):
                param['compaction'] = self._config[f"{adapter}_COMPACTION"]
            if self._config.get(f"{adapter}_COMPACTION_PARAMS", None):
                param['compaction_params'] = self._config[f"{adapter}_COMPACTION_PARAMS"]

            # consistency level
            param['consistency_level'] = ConsistencyHelper.name_to_value[self._config.get(f"{adapter}_CONSISTENCY_LEVEL",
                                                                                          CQLConfigSetting.CONSISTENCY_LEVEL).upper()]

            # network balancing, local data center for correct setting of balancing (RoundRobinPolicy or DCAwareRoundRobinPolicy)
            param['local_dc'] = self._config.get(f"{adapter}_LB_LOCAL_DC", CQLConfigSetting.LB_LOCAL_DC)

            # label
            param['label'] = self._config.get(f"{adapter}_LABEL", CQLConfigSetting.LABEL)

            return param
        else:
            return None