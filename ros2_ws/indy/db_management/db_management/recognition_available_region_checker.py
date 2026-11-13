import numpy as np

from .mongo_utils import load_config


class RecognitionAvailableRegionChecker:
    def __init__(self):
        # 設定 DB (9100) から読む
        config = load_config()
        # 未登録の場合は全領域を認識可能とみなす
        if not config or config.get("recognition_available_regions") is None:
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
