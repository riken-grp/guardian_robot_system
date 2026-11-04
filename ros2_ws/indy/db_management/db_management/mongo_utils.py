from pymongo import MongoClient


def load_config(host, port):
    """Load rism_config from MongoDB and return the configuration document."""
    client = MongoClient(host, port)
    config = client["rism_configs"].rism_config.find_one()
    client.close()
    return config
