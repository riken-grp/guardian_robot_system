from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

from pyindy.mongo.internal_state_logger import get_internal_state_logger
from pymongo import MongoClient


@dataclass
class ScenarioInfo:
    name: str
    date: datetime

    def date_as_ts(self) -> float:
        return self.date.timestamp()

    @classmethod
    def from_list(cls, doclist: list) -> List[ScenarioInfo]:
        return [cls(*d) for d in doclist]

    def __str__(self) -> str:
        return f'{self.name} ({self.date.strftime("%m/%d/%Y, %H:%M:%S")})'

    def __repr__(self) -> str:
        return str(self)


class ScenarioChangeTracker:
    def __init__(self, db: MongoClient) -> None:
        # Load Config, ISL
        self.__config = db.rism_configs.rism_config.find_one({})
        if not self.__config:
            raise Exception("No Configuration Found")
        self.__isl = get_internal_state_logger(self.__config)
        if self.__isl is None:
            raise Exception("Error Loading Internal State Logger")

        self.scenario_list: List[ScenarioInfo] = []
        self.current_scenario: ScenarioInfo = ScenarioInfo(
            "", datetime.fromtimestamp(0)
        )
        self.current_status: str = ""
        self.current_status_since: float = 0
        self.current_status_scenario = ""
        self.is_idling = False

    def update_scenario_list(self):
        if self.__isl is None:
            return
        status = self.__isl.col.find_one({"_name": "recent_scenarios"})

        if status is None:
            return

        self.scenario_list = ScenarioInfo.from_list(status["option"]["recent"])

    def get_current_status(self):
        if self.__isl is None:
            return
        status = self.__isl.col.find_one({"_name": "status"})
        if status is None:
            return
        self.current_status = status["option"]["status"]
        self.current_status_since = status["last_update"].timestamp()
        self.current_status_scenario = status["option"]["scenario"]

    def check_scenario_change(self):
        self.update_scenario_list()
        self.get_current_status()

        if self.current_status == "idling":
            if not self.is_idling:
                self.is_idling = True
                return True
            return False

        self.is_idling = False

        if not self.scenario_list:
            return False
            # self.scenario_list.append(
            #     ScenarioInfo(
            #         (
            #             self.current_status_scenario
            #             if self.current_status != "idling"
            #             else "idling"
            #         ),
            #         jst_ts(self.current_status_since),
            #     )
            # )

        latest = self.scenario_list[-1]

        if latest == self.current_scenario:
            return False

        self.current_scenario = latest

        return True
