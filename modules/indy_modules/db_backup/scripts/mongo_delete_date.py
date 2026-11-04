import re
import sys
import os
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BACKUP_DIR="~/mongo_backup/"

class ControlMongo():
    def __init__(self, mongo_uri, mongo_port, db_name, date):
        mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        if db_name not in mongo_client.list_database_names():
            print(db_name + " DB is not exist.")
            return
        log_db = mongo_client[db_name]
        log_dir = os.path.expanduser(BACKUP_DIR) + "fail_log"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        f = open(log_dir + "/"+date.replace("/", "")+"_status.txt", "a")
        collection_name_list = log_db.list_collection_names()
        time_format1 = re.compile(".*/.*/.*:.*:.*[.].*")
        time_format2 = re.compile(".*/.*/.*:.*:.*:.*")
        date_format = re.compile(".*/.*/.*")
        delete_date = datetime.strptime(date, "%Y/%m/%d")
        # delete_date = delete_date.astimezone(timezone(timedelta(hours=0)))
        if date_format.match(date) is None:
            print("date format is wrong.(yyyy/mm/dd)")
            return
        for collection_name in collection_name_list:
            if collection_name == "log_text":
                continue
            print("delete start " + collection_name)
            log_collection = log_db[collection_name]
            all_document = [doc for doc in log_collection.find({})]
            for document in all_document:
                if "time" not in document.keys():
                    print("time key is not exist.")
                    continue
                date_str = document["time"]
                if type(date_str) is str:
                    if time_format1.match(date_str) is not None:
                        date_data = datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S.%f")
                    elif time_format2.match(date_str) is not None:
                        date_data = datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S:%f")
                elif type(date_str) is datetime:
                    date_data = date_str
                    date_data = date_data.astimezone(timezone(timedelta(hours=9)))
                else:
                    print("not match format")
                    continue
                date_data = date_data.astimezone(timezone(timedelta(hours=9)))
                if date_data.date() == delete_date.date():
                    if "status" not in document.keys():
                        print("status key is not exist.")
                    if ("status" in document.keys() and
                        "time" in document.keys() and
                        "test" in document.keys() and
                        "host" in document.keys()):
                        if document["status"] != "OK":
                            f.write(str(document["_id"]) + ", " + \
                                    str(document["time"]) + ", " + \
                                    str(document["test"]) + ", " + \
                                    str(document["host"]) + ", " + \
                                    document["status"] + "\n")
                    log_collection.delete_one({"_id": document["_id"]})
            print("delete end " + collection_name)


def main():
    args = sys.argv
    if len(args) != 5:
        print("Please input argument 'mongo_uri mongo_port db_name date(yyyy/mm/dd)'")
        return
    mongo_uri = args[1]
    mongo_port = args[2]
    db_name = args[3]
    date = args[4]
    ControlMongo(mongo_uri, mongo_port, db_name, date)

if __name__ == '__main__':
    main()
