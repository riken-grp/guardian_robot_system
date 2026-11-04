import datetime
from zoneinfo import ZoneInfo
import time
from logging import DEBUG, getLogger

from pymongo import ASCENDING, MongoClient


class PersonaDBManager:
    def __init__(self, hostname, port, dbname="persona"):
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self._logger = getLogger(__name__)
        self._logger.setLevel(DEBUG)

    def insert_episode(self, episode):
        col=self.db.episodes
        data = {}
        data["episode"] = episode
        data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        return col.insert_one(data)

    def get_episode(self):
        col=self.db.episodes
        return col

    def get_voice_params(self):
        col=self.db.Voice
        query = {"key": "voice_params"}
        if col.count_documents(query) == 0:
            return False
        return col.find_one(query)

class ActionPrimitives:
    def __init__(self, hostname, port, dbname="persona"):
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.ActionPrimitives
        self._logger = getLogger(__name__)
        self._logger.setLevel(DEBUG)
    #
    def find(self, name):
        query = {"name" : name}
        D=self.col.find_one(query)
        print(D)
        if D==None:
            return False
        else:
            return D
    #
    def insert(self, name, head = [0, 0], body = 0, ra=[0, 0, 0, 0, 0, 0], la=[0, 0, 0, 0, 0, 0]):
        query = {"name" : name}
        if self.col.count_documents(query) == 0:
            option={}
            option['head']=head
            option['body']=body
            option['rightArm']=ra
            option['leftArm']=la
            D={}
            D['name']=name
            D['option']=option
            return self.col.insert_one(D)
        else:
            return False
    def delete(self, name):
        query = {"name" : name}
        if self.col.count_documents(query) == 0:
            return False
        return self.col.delete_many(query)
        
        
