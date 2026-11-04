from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

class ParamManager:
    def __init__(self, env_uri: str, env_port: int):
        self.__params = []
        self.__key_list = []

        mongo_client = MongoClient(f"mongodb://{env_uri}:{env_port}",
                                 serverSelectionTimeoutMS=1000)
        try:
            mongo_client.server_info()
        except ServerSelectionTimeoutError as e:
            raise ConnectionError(f"Failed to connect to mongodb://{env_uri}:{env_port}") from e
        robot_config = mongo_client["robot_config"]
        param_db = robot_config.system_parameters
        self.__params = list(param_db.find({}))
        try:
            self.__key_list = [x["name"] for x in self.__params]
        except KeyError as e:
            raise KeyError("Parameter documents must contain a 'name' field") from e

    def get_param(self, key_name: str):
        if key_name not in self.__key_list:
            return None
        else:
            param_idx = self.__key_list.index(key_name)
            param = self.__params[param_idx]["config"]
            return param

    def get_all_param(self):
        return self.__params

    def get_all_key(self):
        return self.__key_list
