import datetime
from zoneinfo import ZoneInfo
import time
from logging import DEBUG, getLogger
from pymongo import ASCENDING, MongoClient
import random


class DialogueHistoryManager:
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard"):
        self.action_type = None
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.dialogue_history
        self._logger = getLogger(__name__)
        self._logger.setLevel(DEBUG)
        self.robot_name = robot_name

    def insert(self, name, text, port=-1):
        data = {}
        data["name"] = name
        data["text"] = text
        data["port"] = port
        data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        return self.col.insert_one(data)

    def update_many(self, queue, value):
        return self.col.update_many(queue, value)

    def clear_collection(self):
        # print(self.col.count_documents({}))
        self.col.delete_many({})
        return
