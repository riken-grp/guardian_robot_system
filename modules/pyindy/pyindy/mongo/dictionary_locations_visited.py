#!/usr/bin/python3
##############################################################################################
# MongoDB
##############################################################################################
import datetime
from zoneinfo import ZoneInfo

from pymongo import MongoClient


class mng_collection():
    def __init__(self, hostname, port):
        self.client = MongoClient(f"mongodb://" + hostname, port)
        self.db = self.client["dictionary"]
        self.col = self.db.locations_visited

    def register_location(self, location=[-10000., -10000.], orientation=-10000.):
        if self.col.count_documents({}) == 0:
            id = 0
        else:
            id = self.find("max")[0]["_id"] + 1
        print(id)
        self.col.update_one({"_id": id}, {'$set': {'location': location}}, upsert=True)
        self.col.update_one({"_id": id}, {'$set': {'orientation': orientation}}, upsert=True)
        dt_now = datetime.datetime.now(tz=ZoneInfo("Asia/Tokyo"))
        self.col.update_one({"_id": id}, {'$set': {'inserted': dt_now}}, upsert=True)
        return self.col.count_documents({})

    def find(self, name="max"):
        D = self.col.find().sort("_id", -1).limit(1)
        dd = list(D).copy()
        return dd

    def delete(self, obj="none"):
        self.col.delete_one({"_id": int(obj)})
        return self.col.count_documents({})

    def print_collection(self):
        D = self.col.find()
        for d in D:
            print(d)

    def clear_collection(self):
        print("number of documents to be eraces: ", str(self.col.count_documents({})))
        self.col.delete_many({})
        return "Erase all registered locations"


#################################################################################
import sys
#################################################################################
# main loop
#################################################################################
from time import sleep

if __name__ == '__main__':
    args = sys.argv
    if len(args) < 4:
        print(args[0], "server_name port add coordinate_x coordinate_y orientation")
        print(args[0], "server_name port add_alias name alias")
        print(args[0], "server_name port clear")
        exit(0)
    serv = args[1]
    port = int(args[2])
    command = args[3]
    mng = mng_collection(serv, port)
    if command == "add":
        print(mng.register_location([float(args[4]), float(args[5])], float(args[6])))
    elif command == "print":
        mng.print_collection()
    elif command == "clear":
        print(mng.clear_collection())
    elif command == "delete":
        mng.delete(args[4])


#
