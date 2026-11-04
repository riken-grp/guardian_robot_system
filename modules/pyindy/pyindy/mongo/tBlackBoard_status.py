import datetime
from zoneinfo import ZoneInfo
import time
from logging import DEBUG, getLogger

from pymongo import ASCENDING, MongoClient


class StatusManager:
    def __init__(self, hostname, port, robot_name, subsystem, dbname="tBlackBoard"):
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.status
        self._logger = getLogger(__name__)
        self._logger.setLevel(DEBUG)
        self.robot_name = robot_name
        self.subsystem = subsystem

    def set_status(self, status):
        query={"key": self.subsystem}
        data = {}
        data["time"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        data["actor"] = self.robot_name
        data["key"] = self.subsystem
        data["status"] = status
        return self.col.update_one(query, {"$set": data}, upsert=True)

    def get_status(self):
        query={"key": self.subsystem}
        num = self.col.count_documents(query)
        if num == 0:
            return "unknown entry_id"
        return self.col.find_one(query)["status"]

