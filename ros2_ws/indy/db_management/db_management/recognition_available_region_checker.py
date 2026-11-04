import numpy as np
from pymongo import MongoClient


class RecognitionAvailableRegionChecker:
    def __init__(self, mongo_uri, mongo_port):
        client = MongoClient(mongo_uri, mongo_port)
        config = client["rism_configs"]["rism_config"].find_one()
        client.close()
        if "recognition_available_regions" not in config:
            self.regions = None
        else:
            self.regions = config["recognition_available_regions"]

    def is_in(self, location):
        """
        location: (x, y) in the world coordinate
        """
        if self.regions is None:
            return True, None
        for region in self.regions:
            if region["type"] == "rectangle":
                points = region["locations"]
                max_x, max_y = np.asarray(points).max(axis=0)
                min_x, min_y = np.asarray(points).min(axis=0)

                if min_x < location[0] < max_x and min_y < location[1] < max_y:
                    return True, region["region_id"]
            else:
                raise NotImplementedError()

        return False, None
