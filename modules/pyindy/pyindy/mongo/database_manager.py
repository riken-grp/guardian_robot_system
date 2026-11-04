import datetime
from zoneinfo import ZoneInfo

from bson.objectid import ObjectId
from pymongo import DESCENDING, MongoClient


class GenericDBManager:
    def __init__(self, host, port, dbname, collection):
        assert collection in ["physical_topic", "cyber_topic"]
        self.client = MongoClient(host, port)
        self.db = self.client[dbname][collection]

    def get_latest(self):
        ret = self.db.find_one(
            {"mentioned": False},
            sort=[("priority", DESCENDING), ("inserted", DESCENDING)],
        )
        return ret if ret is not None else {}

    def get_latest_N(self, n, observe_after=None):
        ret = self.db.find(
            {"mentioned": False, "ignored": {"$ne": True}},
            sort=[("inserted", DESCENDING), ("priority", DESCENDING)],
        ).limit(n)
        data = list(ret) if ret is not None else []

        filtered = []
        for d in data:
            if (
                observe_after is None
                or not isinstance(d, dict)
                or "started_time" not in d["contents"]
                or d["contents"]["started_time"] > observe_after
            ):
                filtered.append(d)
        return filtered

    def set_mentioned(self, entry, same_events=False):
        # 使用済みのフラグを立てる
        query = {}
        query["mentioned"] = True
        query["last_mentioned"] = datetime.datetime.now(ZoneInfo("Asia/Tokyo"))
        self.db.update_one({"_id": ObjectId(entry["_id"])}, {"$set": query})

        if same_events:
            # 同じイベントを参照済みにする
            i = self.db.update_many(
                {
                    "event": entry["event"],
                },
                {"$set": query},
            )

    def decrease_priority(self):
        self.db.update_many({}, {"$inc": {"priority": -1}})
        self.db.delete_many({"priority": {"$lt": 0}})

    def delete(self, query):
        self.db.delete_many(query)


class WriterMixin:
    def insert(self, contents, priority=50):
        if self.event is None:
            self._logger.warn("Event type is not specified")
            return

        q = {}
        q["event"] = self.event
        q["priority"] = priority
        q["inserted"] = datetime.datetime.now()
        q["contents"] = contents
        q["mentioned"] = False
        q["last_mentioned"] = None
        return self.db.insert_one(q)


class CyberDBReader(GenericDBManager):
    def __init__(self, host, port, dbname):
        super().__init__(host, port, dbname, "cyber_topic")


class PhysicalDBReader(GenericDBManager):
    def __init__(self, host, port, dbname):
        super().__init__(host, port, dbname, "physical_topic")


class CyberDBWriter(GenericDBManager, WriterMixin):
    def __init__(self, host, port, dbname, event_name):
        super().__init__(host, port, dbname, "cyber_topic")
        self.event = event_name


class PhysicalDBWriter(GenericDBManager, WriterMixin):
    def __init__(self, host, port, dbname, event_name):
        super().__init__(host, port, dbname, "physical_topic")
        self.event = event_name


class DBManager(GenericDBManager, WriterMixin):
    def insert(self, event_name, contents, priority=50):
        q = {}
        q["event"] = event_name
        q["priority"] = priority
        q["inserted"] = datetime.datetime.now()
        q["contents"] = contents
        q["mentioned"] = False
        q["last_mentioned"] = None
        return self.db.insert_one(q)
