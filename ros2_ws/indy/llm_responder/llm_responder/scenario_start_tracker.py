#!/usr/bin/env python
# coding: utf-8 -*-

from pymongo import MongoClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.node import Node
from .util.scenario_change_tracker import ScenarioChangeTracker


class ScenarioStartTracker:
    def __init__(self, node: Node, db: MongoClient) -> None:
        self.parent = node
        try:
            self.scenario_checker = ScenarioChangeTracker(db)
        except Exception as e:
            self.logger.error(f"Cannot Check Scenario State: {str(e)}")
            self.scenario_checker = None

        self.current: float = 0
        self.status_str = ""
        self.scenario = ""

        if self.scenario_checker is not None:
            self.checker = self.parent.create_timer(
                1.0, self.callback, MutuallyExclusiveCallbackGroup()
            )
        self.idle_end_ts = 0

    def callback(self):
        if self.scenario_checker is None:
            return

        has_changed = self.scenario_checker.check_scenario_change()

        if not has_changed:
            return

        new_status_str = self.scenario_checker.current_status
        new_scenario_str = (
            self.scenario_checker.current_scenario.name
            if self.scenario_checker.current_scenario is not None
            else ""
        )
        new_timestamp = (
            self.scenario_checker.current_status_since
            if new_status_str == "idling"
            or self.scenario_checker.current_scenario is None
            else self.scenario_checker.current_scenario.date_as_ts()
        )

        if self.status_str == "idling" and self.status_str != new_status_str:
            # Exit Idling
            self.idle_end_ts = new_timestamp

        if new_status_str == "idling" and self.status_str != new_status_str:
            self.parent.get_logger().debug(
                f"[SCENARIO] Idling since {new_timestamp:.9f}"
            )
        elif new_status_str == "running" and self.status_str != new_status_str:
            self.parent.get_logger().debug(
                f'[SCENARIO] Running "{new_scenario_str}" since {new_timestamp:.9f}'
            )
        elif self.status_str != new_status_str:
            self.parent.get_logger().debug(
                f'[SCENARIO] Unknown Status "{new_status_str}"'
                + f" since {new_timestamp:.9f}"
            )

        self.status_str = new_status_str
        self.scenario = new_scenario_str
        self.current = new_timestamp

    @property
    def logger(self):
        return self.parent.get_logger()
