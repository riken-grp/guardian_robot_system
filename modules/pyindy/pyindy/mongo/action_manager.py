import datetime
from logging import DEBUG, getLogger
from zoneinfo import ZoneInfo

from pymongo import ASCENDING, MongoClient


class ActionManager:
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        self.action_type = None
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.Actions
        self._logger = getLogger(__name__)
        self._logger.setLevel(DEBUG)
        self.robot_name = robot_name
        self.version = version  # "1.0" or "2.0"

    def direct_insert(self, command, option="none", condition=None):
        data = {}
        data["actor"] = self.robot_name
        data["status"] = "waiting"
        data["option"] = option

        if self.version == "1.0":
            # Version 1.0: use 'command' field with timestamps
            data["command"] = command
            data["condition"] = condition if condition is not None else {"type": "none"}
            data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
            data["last_update"] = "never"
        else:
            # Version 2.0: use 'name' field without timestamps
            data["name"] = command
            data["condition"] = condition if condition is not None else {}

        return self.col.insert_one(data)

    def insert(self, command, option="none", condition=None):
        data = {}
        data["actor"] = self.robot_name
        data["status"] = "waiting"
        data["option"] = option

        if self.version == "1.0":
            # Version 1.0: use 'command' field with timestamps
            data["command"] = command
            data["condition"] = condition if condition is not None else {"type": "none"}
            data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
            data["last_update"] = "never"
        else:
            # Version 2.0: use 'name' field without timestamps
            data["name"] = command
            data["condition"] = condition if condition is not None else {}

        return self.col.insert_one(data)

    def insert_many(self, com_list):
        # com_list format
        # {'command type 1': option 1}, {'command type 2': option 2}, ...]
        documents = []
        for k in com_list.keys():
            data = {}
            data["actor"] = self.robot_name
            data["status"] = "waiting"
            data["option"] = com_list[k]

            if self.version == "1.0":
                # Version 1.0: use 'command' field with timestamps
                data["command"] = k
                data["condition"] = {"type": "none"}
                data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
                data["last_update"] = "never"
            else:
                # Version 2.0: use 'name' field without timestamps
                data["name"] = k
                data["condition"] = {}

            documents.append(data)
        return self.col.insert_many(documents)

    def update_many(self, queue, value):
        return self.col.update_many(queue, value)

    def reset_mongodb(self, hostname, port, dbname="tBlackBoard"):
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.Actions
        return self.col

    def check_condition(self, condition):
        print("check_condition")
        print(condition)
        if "runWith" in condition:
            query = {"_id": condition["runWith"]}
            data = self.col.find_one(query)
            if data == None:
                print("get_next: No mathc found: condition")
                return "cancel"
            if data["status"] == "waiting":
                return "wait"
            if data["status"] == "is_playing":
                return "do"
            else:
                return "cancel"
        if "runAfter" in condition:
            query = {"_id": condition["runAfter"]}
            data = self.col.find_one(query)
            if data == None:
                print("get_next: No mathc found: condition")
                return "cancel"
            if data["status"] == "waiting":
                return "wait"
            if data["status"] == "is_playing":
                return "wait"
            if data["status"] == "done":
                return "do"
            if data["status"] == "ignored":
                return "do"
            else:
                return "cancel"
        else:
            return "do"

    def get_next(self, query=False):
        if not query:
            query = {"status": "waiting", "actor": self.robot_name}
        data = self.col.find_one(query, sort=[("inserted", ASCENDING)])
        if data == None:
            print("get_next: No match found.")
            return False
        else:
            flag = self.check_condition(data["condition"])
            print(flag)
            if flag == "do":
                return data
            elif flag == "wait":
                return False
            else:
                self.set_status(data["_id"], "cancel")
                return False

    def set_status(self, entry_id, status):
        num = self.col.count_documents({"_id": entry_id})
        if num == 0:
            return "unknown id"
        dt_now = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        self.col.update_one(
            {"_id": entry_id},
            {"$set": {"status": status, "last_update": dt_now}},
            upsert=True,
        )
        return "success"

    def cancel_all(self, actor=False, command=False):
        query = {"$or": [{"status": "waiting"}, {"status": "is_playing"}]}
        if actor:
            query["actor"] = actor
        if command:
            query["command"] = command
        dt_now = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        a = self.col.update_many(
            query, {"$set": {"status": "canceled", "last_update": dt_now}}
        )
        return a.matched_count

    def stop_all(self, actor=None, command=None):
        option = {}
        option["type"] = "normal"
        option["topic"] = f"/{self.robot_name}/robot/action_ctl"
        option["data"] = "stop"
        if command is not None:
            option["data"] = command + "." + option["data"]
        self.direct_insert("ros_command", option=option, condition=None)

    def get_status(self, entry_id):
        num = self.col.count_documents({"_id": entry_id})
        if num == 0:
            return "unknown entry_id"
        return self.col.find_one({"_id": entry_id})["status"]

    def clear_texts(self):
        num = self.col.count_documents({})
        self._logger.debug(f"number of documents to be eraces: {num}")
        self.col.delete_many({})
        self.insert("speak", {"text": "初期化しました。"})

    def get_num_playing(self):
        if self.action_type is None:
            return self.col.count_documents(
                {"$or": [{"status": "is_playing"}, {"status": "waiting"}]}
            )
        else:
            return self.col.count_documents(
                {
                    "$or": [
                        {"command": self.action_type, "status": "is_playing"},
                        {"command": self.action_type, "status": "waiting"},
                    ]
                }
            )

    def get_num_playing_all(self, ignore_observation=False):
        return self.col.count_documents(
            {
                "$or": [{"status": "is_playing"}, {"status": "waiting"}],
                "command": {"$ne": "observation"},
            }
        )

    def clear_playing(self):
        query = {"status": "is_playing"}
        dt_now = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        a = self.col.update_many(
            query, {"$set": {"status": "failed", "last_update": dt_now}}
        )
        return a.matched_count


class UtteranceManager(ActionManager):
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        super().__init__(hostname, port, robot_name, dbname, version=version)
        self.action_type = "speak"

    def get_next(self):
        query = {"status": "waiting", "command": "speak", "actor": self.robot_name}
        return super().get_next(query)

    def cancel_all(self, command=False):
        return super().cancel_all(actor=self.robot_name, command="speak")

    def insert(self, utterance, condition=None):
        return super().insert(command="speak", option=utterance, condition=condition)

    def stop_all(self):
        super().stop_all()


class GestureManager(ActionManager):
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        super().__init__(hostname, port, robot_name, dbname, version=version)
        self.action_type = "gesture"

    def get_next(self):
        query = {"status": "waiting", "command": "gesture", "actor": self.robot_name}
        return super().get_next(query)

    def cancel_all(self, command=False):
        return super().cancel_all(actor=self.robot_name, command="gesture")

    def insert(self, gesture, condition=None):
        return super().insert(command="gesture", option=gesture, condition=condition)


class NavigationManager(ActionManager):
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        super().__init__(hostname, port, robot_name, dbname, version=version)
        self.action_type = "navigation"

    def get_next(self):
        query = {"status": "waiting", "command": "navigation", "actor": self.robot_name}
        return super().get_next(query)

    def cancel_all(self, command=False):
        return super().cancel_all(actor=self.robot_name, command="navigation")

    def insert(self, navigation, condition=None):
        return super().insert(
            command="navigation", option=navigation, condition=condition
        )


class EyeManager(ActionManager):
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        super().__init__(hostname, port, robot_name, dbname, version=version)
        self.action_type = "eye"

    def get_next(self):
        query = {"status": "waiting", "command": "eye", "actor": self.robot_name}
        return super().get_next(query)

    def cancel_all(self, command=False):
        return super().cancel_all(actor=self.robot_name, command="eye")

    def insert(self, option, condition=None):
        return super().insert(command="eye", option=option, condition=condition)


class ObservationManager(ActionManager):
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        super().__init__(hostname, port, robot_name, dbname, version=version)
        self.action_type = "observation"

    def get_next(self):
        query = {
            "status": "waiting",
            "command": "observation",
            "actor": self.robot_name,
        }
        return super().get_next(query)

    def cancel_all(self, command=False):
        return super().cancel_all(actor=self.robot_name, command="observation")

    def insert(self, option, condition=None):
        return super().insert(command="observation", option=option, condition=condition)


class ROSCommandManager(ActionManager):
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        super().__init__(hostname, port, robot_name, dbname, version=version)
        self.action_type = "ros_command"

    def get_next(self):
        query = {
            "status": "waiting",
            "command": "ros_command",
            "actor": self.robot_name,
        }
        return super().get_next(query)

    def cancel_all(self, command=False):
        return super().cancel_all(actor=self.robot_name, command="ros_command")

    def insert(self, option, condition=None):
        return super().insert(command="ros_command", option=option, condition=condition)


class RecallManager(ActionManager):
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard", version="1.0"):
        super().__init__(hostname, port, robot_name, dbname, version=version)
        self.action_type = "recall_mem"

    def get_next(self):
        query = {
            "status": "waiting",
            "command": "recall_mem",
            "actor": self.robot_name,
        }
        return super().get_next(query)  # type: ignore

    def cancel_all(self, command=False):
        return super().cancel_all(
            actor=self.robot_name,
            command="recall_mem",  # type: ignore
        )

    def insert(self, option, condition=None):
        return super().insert(command="recall_mem", option=option, condition=condition)
