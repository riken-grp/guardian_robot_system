import os
import sys
from datetime import datetime
from pymongo import MongoClient

def register_db(mongo_uri="example.local", mongo_port="3000"):
    mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
    network_db = mongo_client["log"]
    network_collection = network_db["text"]

    return network_collection 

def write_db(msg, db_collection):
    dt_now = datetime.now()
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    host_name = os.uname()[1]

    obj = {}
    obj["time"] = dt_now
    obj["robot"] = robot_name
    obj["host"] = host_name
    obj["test"] = "nw_connection"
    obj["text"] = host_name + "'s AP connection is " + msg
    db_collection.insert_one(obj)
    # print(obj["time"], obj["host"], obj["text"])


def main():
    args = sys.argv
    if len(args) != 4:
        print("Please input argument 'msg mongo_uri mongo_port'")
        sys.exit()
    mongo_uri = args[2]
    mongo_port = args[3]
    db_collection = register_db(mongo_uri, mongo_port)
    write_db(args[1], db_collection)


if __name__ == '__main__':
    main()
