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

# OpenWeatherMap API の HTTP タイムアウト [s]
HTTP_TIMEOUT_SEC = 10


class RegisterDBWeatherNode(MongoDBNode):
    def __init__(self, name="RegisterDBWeatherNode"):
        super().__init__(name)
        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)
        self.JST = tz.gettz("Asia/Tokyo")
        self.mgr = None

        config = load_config()
        if "openweathermap_token" not in config or "city" not in config:
            # 設定が無い場合はノードを落とさず (launch 全体を道連れにせず) 天気取得を無効化する
            self.get_logger().error(
                "robot settings have no 'openweathermap_token' / 'city'; "
                "weather registration is disabled"
            )
            return

        config_dict = get_default_config()
        config_dict["language"] = config.get("language", "ja")
        config_dict["connection"]["timeout_secs"] = HTTP_TIMEOUT_SEC
        self.city = config["city"]

        owm = OWM(config["openweathermap_token"], config_dict)
        self.mgr = owm.weather_manager()

        self.timer = self.create_timer(600, self.timer_callback)

    def timer_callback(self):
        if self.mgr is None:
            return
        try:
            self._fetch_and_store()
        except InvalidSSLCertificateError as e:
            self.get_logger().warn(f"weather fetch failed (SSL): {e}")
        except Exception as e:
            # HTTP エラー・タイムアウト・API エラー・DB エラー等でノードを落とさない
            # (on_exit=Shutdown のため，ここで落ちると db_management launch 全体が終了する)
            self.get_logger().warn(f"weather fetch failed: {type(e).__name__}: {e}")

    def _fetch_and_store(self):
        w = self.mgr.weather_at_place(self.city).weather

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
