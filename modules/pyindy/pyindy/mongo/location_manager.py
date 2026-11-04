import datetime
from zoneinfo import ZoneInfo
import time
from logging import DEBUG, getLogger
from pymongo import ASCENDING, MongoClient
import random


class LocationManager:
    def __init__(self, hostname, port, robot_name, dbname="tBlackBoard"):
        self.action_type = None
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.Locations
        self._logger = getLogger(__name__)
        self._logger.setLevel(DEBUG)
        self.robot_name = robot_name

    def insert(self, name, coordinate, reachable=False, option={'alias': []}):
        if not (self.find_from_name(name) == None):
            print("Location Manager error: The location (" + name + ") has already existed.")
            return False
        data = {}
        data["name"] = name
        data["coordinate"] = coordinate
        data["reachable"] = reachable # True: robot position, False: TV, Desk, ...
        data["option"] = option
        data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        return self.col.insert_one(data)

    def update_many(self, queue, value):
        return self.col.update_many(queue, value)

    def reset_mongodb(self, hostname, port, dbname="tBlackBoard"):
        self.client = MongoClient(f"mongodb://{hostname}:{port}")
        self.db = self.client[dbname]
        self.col = self.db.Locations
        return self.col

    def find_from_name(self, name):
        query={"name": name}
        id=self.col.find_one(query)
        # print(id)
        return id

    def delete_from_name(self, name):
        query={"name": name}
        id=self.col.delete_one(query)
        # print(id)
        return id

    def clear_collection(self):
        # print(self.col.count_documents({}))
        self.col.delete_many({})
        return 

    def find_nearest(self, p, threshold=1.0):
        x=p[0]
        y=p[1]
        nn=self.col.find_one({'coordinate':{'$near':[x,y,threshold]}})
        return nn
    
    def test_insert(self, n):
        for i in range(n):
            name=str(i)
            c=[random.random(), random.random()]
            r= (random.random()<0.8)
            self.insert(name, c, r)
        return True

    def make_new_collection(self):
        name='origin'
        c=[0.0, 0.0]
        r=False
        self.insert(name, c, r)
        self.col.create_index([("coordinate","2d")])
        return True

    def get_option(self, name):
        query={'name':name}
        D=self.col.find_one(query)
        return D['option']

    def set_option(self, name, option):
        query={'name':name}
        D=self.col.find_one(query)
        c=D['coordinate']
        r=D['reachable']
        o=option
        self.delete_from_name(name)
        id=self.insert(name, c, r, o)
        return id
