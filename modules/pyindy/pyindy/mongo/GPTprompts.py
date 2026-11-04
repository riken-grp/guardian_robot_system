#!/usr/bin/python3
##############################################################################################
# MongoDB
##############################################################################################
import datetime
from zoneinfo import ZoneInfo

from pymongo import MongoClient


class mng_style(object):
    def __init__(self, hostname, port, dbname='GPTprompts'):
        self.client = MongoClient(f"mongodb://" + hostname, port)
        self.db = self.client[dbname]
        self.col = self.db.style
        #
    def insert(self, name, text, option='none'):
        data = {}
        data["name"] = name
        data["style"] = text
        data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        data["option"] = option
        return self.col.insert_one(data)
    #
    def get(self, name):
        query={"name": name}
        ret = self.col.find_one(query)
        if ret is None:
            return False
        return self.col.find_one(query)['style']

###
class mng_episode(object):
    def __init__(self, hostname, port, dbname='GPTprompts'):
        self.client = MongoClient(f"mongodb://" + hostname, port)
        self.db = self.client[dbname]
        self.col = self.db.episode
        #
    def insert(self, keywords, text, option='none'):
        data = {}
        data["keywords"] = keywords
        data["episode"] = text
        data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        data["option"] = option
        return self.col.insert_one(data)
    #
    def get(self, keyword):
        query={"keywords": keyword}
        ret = self.col.find_one(query)
        if ret is None:
            return False
        return self.col.find_one(query)['episode']
###
class mng_purpose(object):
    def __init__(self, hostname, port, dbname='GPTprompts'):
        self.client = MongoClient(f"mongodb://" + hostname, port)
        self.db = self.client[dbname]
        self.col = self.db.purpose
        #
    def insert(self, purpose, text, option='none'):
        data = {}
        data["purpose"] = purpose
        data["instruction"] = text
        data["inserted"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        data["option"] = option
        return self.col.insert_one(data)
    #
    def get(self, command):
        query={"purpose": command}
        ret = self.col.find_one(query)
        if ret is None:
            return False
        return self.col.find_one(query)['instruction']

###
class mng_scenario(object):
    def __init__(self, hostname, port, dbname='robot_config'):
        self.client = MongoClient(f"mongodb://" + hostname, port)
        self.db = self.client[dbname]
        self.col = self.db.scenarios
        #
    def insert(self, s):
        return self.col.insert_one(s)


