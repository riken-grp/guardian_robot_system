from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pymongo import MongoClient


class LogText():
    def __init__(self, hostname, port, robot_name, node_name):
        self.client = MongoClient(f"mongodb://" + hostname, port)
        self.db = self.client["log"]
        self.col = self.db.log_text
        self.robot_name = robot_name
        self.node_name = node_name

    def insert(self, text):
        data = {}
        data["robot_name"] = self.robot_name
        data["node"] = self.node_name
        data["text"] = text
        data["time"] = datetime.now(ZoneInfo("Asia/Tokyo"))
        return self.col.insert_one(data)
