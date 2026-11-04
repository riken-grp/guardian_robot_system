from pymongo import MongoClient


def load_config(host: str, port: int) -> dict:
    client = MongoClient(host, port)
    db = client["rism_configs"].rism_config

    config = db.find_one()

    robots = {}
    for key, r in config["robot_list"].items():
        tmpclient = MongoClient(r["host"], r["port"])
        tmpdb = tmpclient["rism_configs"][r["config_name"]]
        robots[key] = tmpdb.find_one({"robot_id": key})
        if robots[key] is None:
            del robots[key]
            continue
        robots[key].update(r)
    config["robot_list"] = robots

    return config
