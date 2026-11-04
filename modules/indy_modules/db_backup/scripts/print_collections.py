import re
import sys
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

class PrintCollections():
    def __init__(self, mongo_uri, mongo_port, db_name):
        mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        if db_name not in mongo_client.list_database_names():
            print(db_name + " DB is not exist.")
            return
        log_db = mongo_client[db_name]
        collection_name_list = log_db.list_collection_names()
        for collection_name in collection_name_list:
            print(collection_name)


def main():
    args = sys.argv
    if len(args) != 4:
        print("Please input argument 'mongo_uri mongo_port db_name date(yyyy/mm/dd)'")
        return
    mongo_uri = args[1]
    mongo_port = args[2]
    db_name = args[3]
    PrintCollections(mongo_uri, mongo_port, db_name)

if __name__ == '__main__':
    main()
