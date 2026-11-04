import datetime
from zoneinfo import ZoneInfo
import time
from logging import DEBUG, getLogger
from pymongo import ASCENDING, MongoClient


class tmpGestureManager:
    def __init__(self, hostname, port, robot_name, dbname='tBlackBoard'):
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.gestures
        self._logger = getLogger(__name__)
        self._logger.setLevel(DEBUG)
        self.robot_name=robot_name
        
    def set(self, key, value):
        query={ "key": key }
        dt_now = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        self.col.update_one(query, {'$set':{'value': value,'inserted': dt_now}}, upsert=True)
        return 

    def get(self, key):
        query={ "key": key }
        return self.col.find_one(query)['value']

