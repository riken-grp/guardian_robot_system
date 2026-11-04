#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rclpy
from dateutil import tz
from pyowm.commons.exceptions import InvalidSSLCertificateError
from pyowm.owm import OWM
from pyowm.utils import formatting
from pyowm.utils.config import get_default_config
from rclpy import qos
from .dbmanager import TopicDBManager
from .mongo_node_base import MongoDBNode
from .mongo_utils import load_config


class RegisterDBWeatherNode(MongoDBNode):
    def __init__(self, name="RegisterDBWeatherNode"):
        super().__init__(name)
        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        config = load_config(mongo_uri, mongo_port)
        config_dict = get_default_config()
        config_dict["language"] = config["language"]
        self.city = config["city"]

        self.JST = tz.gettz("Asia/Tokyo")
        owm = OWM(config["openweathermap_token"], config_dict)
        self.mgr = owm.weather_manager()

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        self.timer = self.create_timer(600, self.timer_callback)

    def timer_callback(self):
        try:
            w = self.mgr.weather_at_place(self.city).weather
        except InvalidSSLCertificateError as e:
            print(e)
            return

        data = {}
        data["location"] = self.city
        data["time"] = formatting.to_date(w.ref_time).astimezone(self.JST).isoformat()
        data["ref_time"] = w.ref_time
        data["weather_code"] = w.weather_code
        data["status"] = w.status
        data["detailed_status"] = w.detailed_status
        t = w.temperature("celsius")
        data["temperature"] = t["temp"]
        data["temperature_min"] = t["temp_min"]
        data["temperature_max"] = t["temp_max"]
        data["temperature_feels_like"] = t["feels_like"]
        data["humidity"] = w.humidity
        data["barometric_pressure"] = w.barometric_pressure()
        data["wind"] = w.wind()
        data["clouds"] = w.clouds
        data["rain"] = w.rain
        data["snow"] = w.snow

        self.dbmanager.insert_weather(data, priority=300)


def main():
    rclpy.init()
    node = RegisterDBWeatherNode()
    rclpy.spin(node)
    rclpy.shutdown()
