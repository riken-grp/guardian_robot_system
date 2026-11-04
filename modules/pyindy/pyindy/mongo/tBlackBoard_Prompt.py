#!/usr/bin/python3
##############################################################################################
# MongoDB
##############################################################################################
import datetime
from zoneinfo import ZoneInfo

from pymongo import MongoClient


class mng_collection():
    def __init__(self, hostname, port, db='tBlackBoard'):
        self.client = MongoClient(f"mongodb://" + hostname, port)
        self.db = self.client[db]
        self.col = self.db.Prompt
        #

    def insert(self, s_id, llm, fmt, cnt, dy, ref):
        prompt={}
        prompt['senario_id']=s_id
        prompt['llm_params']=llm
        prompt['format']=fmt
        prompt['context']=cnt
        prompt['dynamic']=dy
        prompt['reference']=ref
        return self.col.insert_one(prompt)

    def get_dynamic(self, entry_id):
        query={"_id": entry_id}
        if self.col.count_documents(query) ==0:
            return False
        return self.col.find_one(query)

    def set_dynamic(self, entry_id, dynamic_context):
        query={"_id": entry_id}
        if self.col.count_documents(query) ==0:
            return False
        return self.col.insert_one(query, {'$set':{'dynamic': dynamic_context}}, upsert=Ture)

    def print_collection(self):
        D = self.col.find()
        for d in D:
            print(d)


