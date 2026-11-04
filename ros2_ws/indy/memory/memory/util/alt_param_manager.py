from pyindy.param_manager import param_manager
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError


class ParamManager(param_manager.ParamManager):
    def __init__(self, mongo_client: MongoClient):
        self.__params = []
        self.__key_list = []

        try:
            mongo_client.server_info()
        except ServerSelectionTimeoutError as e:
            env_uri, env_port = (
                mongo_client.address
                if mongo_client.address is not None
                else ("unknown", 0)
            )
            raise ConnectionError(
                f"Failed to connect to mongodb://{env_uri}:{env_port}"
            ) from e
        robot_config = mongo_client["robot_config"]
        param_db = robot_config.system_parameters
        self.__params = list(param_db.find({}))
        try:
            self.__key_list = [x["name"] for x in self.__params]
        except KeyError as e:
            raise KeyError(
                "Parameter documents must contain a 'name' field"
            ) from e
