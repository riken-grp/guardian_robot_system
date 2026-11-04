import datetime

from pymongo import MongoClient


class _InternalStateLogger:
    def __init__(self, config):
        host: str = config["db_config"]["internal_state_db"]["host"]
        port: int = config["db_config"]["internal_state_db"]["port"]
        dbname: str = config["db_config"]["internal_state_db"]["dbname"]
        col_name: str = config["db_config"]["internal_state_db"]["col_name"]
        client = MongoClient(f"mongodb://{host}:{port}")
        db = client[dbname]
        self.col = db[col_name]
        self.scenario_history = db["scenario_history"]

    def idling(self):
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["status"] = "idling"
        q["option"]["scenario"] = None
        self.col.update_one({"_name": "status"}, {"$set": q}, upsert=True)

    def scenario_update(self, scenario_manager):
        d = datetime.datetime.now()
        q = {"option": {}, "last_update": d}
        q["option"]["status"] = "running"
        q["option"]["scenario"] = scenario_manager.scenario.name
        self.col.update_one({"_name": "status"}, {"$set": q}, upsert=True)
        self.add_recent_scenarios(scenario_manager.scenario)

        q = {
            "scenario_name": scenario_manager.scenario.name,
            "scenario_id": scenario_manager.scenario.scenario_id,
            "executed time": d,
        }
        self.scenario_history.insert_one(q)

    def run_initialize(self):
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["command"] = None
        self.col.update_one({"_name": "run"}, {"$set": q}, upsert=True)

    def run_action(self, action):
        q = {"_name": "run"}
        data = self.col.find_one(q)
        if data is None:
            q = {"option": {}}
        else:
            q = data
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["command"] = action["command"]
        self.col.update_one({"_name": "run"}, {"$set": q}, upsert=True)

    def output_initialize(self):
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["command"] = None
        self.col.update_one({"_name": "output"}, {"$set": q}, upsert=True)

    def output(self, actions):
        q = {"_name": "output"}
        data = self.col.find_one(q)
        if data is None:
            q = {"option": {}}
        else:
            q = data
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["command"] = ""
        q["option"]["action"] = actions
        self.col.update_one({"_name": "output"}, {"$set": q}, upsert=True)

    def output_start_observation(self, action):
        q = {"_name": "output"}
        data = self.col.find_one(q)
        if data is None:
            q = {"option": {}}
        else:
            q = data
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["command"] = "observation"
        q["option"]["action"] = action
        self.col.update_one({"_name": "output"}, {"$set": q}, upsert=True)

    def output_end_observation(self):
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["command"] = None
        self.col.update_one({"_name": "output"}, {"$set": q}, upsert=True)

    def output_talking_person(self, person_id):
        q = {"_name": "output"}
        data = self.col.find_one(q)
        if data is None:
            q = {"option": {}}
        else:
            q = data
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["talking_person"] = person_id
        self.col.update_one({"_name": "output"}, {"$set": q}, upsert=True)

    def run_talking_person(self, person_id):
        q = {"_name": "run"}
        data = self.col.find_one(q)
        if data is None:
            q = {"option": {}}
        else:
            q = data
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["talking_person"] = person_id
        self.col.update_one({"_name": "run"}, {"$set": q}, upsert=True)

    def interruption_initialize(self):
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["observations"] = None
        q["option"]["subscenario"] = None
        q["option"]["temp_queue"] = None
        self.col.update_one({"_name": "interruption"}, {"$set": q}, upsert=True)

    def interruption_subscenario(self, observations, subscenario):
        q = {"option": {}, "last_update": datetime.datetime.now()}
        q["option"]["observations"] = observations
        q["option"]["subscenario"] = subscenario
        self.col.update_one({"_name": "interruption"}, {"$set": q}, upsert=True)

    def interruption_temp_queue(self, temp_queue):
        q = {"_name": "interruption"}
        data = self.col.find_one(q)
        if data is None:
            q = {"option": {}}
        else:
            q = data
        q["last_update"] = datetime.datetime.now()
        q["option"]["temp_queue"] = temp_queue
        self.col.update_one({"_name": "interruption"}, {"$set": q}, upsert=True)

    def proc_show_variable(self, name, value):
        q = {"option": {}}
        q["last_update"] = datetime.datetime.now()
        q["option"]["value"] = value
        self.col.update_one(
            {"_name": f"proc variable: {name}"}, {"$set": q}, upsert=True
        )

    def add_recent_scenarios(self, scenario):
        q = {"_name": "recent_scenarios"}
        data = self.col.find_one(q)

        q = {"option": {}}
        if data is None or "recent" not in data["option"]:
            recent = []
        else:
            recent = data["option"]["recent"]

        recent.append((scenario.name, datetime.datetime.now()))
        if len(recent) > 10:
            recent.pop(0)
        q["option"]["recent"] = recent
        self.col.update_one({"_name": "recent_scenarios"}, {"$set": q}, upsert=True)


_internal_state_logger = None


def get_internal_state_logger(config=None):
    global _internal_state_logger
    if _internal_state_logger is None and config is not None:
        _internal_state_logger = _InternalStateLogger(config)

    return _internal_state_logger
