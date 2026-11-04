from __future__ import annotations

from collections import UserDict
from datetime import timedelta
from os import getenv
from typing import NamedTuple

from pymongo.database import Database

ROBOT_NAME = getenv("ROBOT_NAME")


class MemoryLevel(NamedTuple):
    sm_lvl: int
    stm_lvl: int
    ltm_lvl: int


class ForgettingSettings(UserDict):
    def __init__(
        self, a: float, d: float, f_line: float, freq: float, **kwargs
    ):
        super().__init__()
        self.a = a
        self.d = d
        self.f_line = f_line
        self.freq = freq
        self.data.update(**kwargs)

    @property
    def a(self) -> float:
        return self.data["a"]

    @a.setter
    def a(self, val: float) -> None:
        self.data["a"] = val

    @property
    def d(self) -> float:
        return self.data["d"]

    @d.setter
    def d(self, val: float) -> None:
        self.data["d"] = val

    @property
    def f_line(self) -> float:
        return self.data["f_line"]

    @f_line.setter
    def f_line(self, val: float) -> None:
        self.data["f_line"] = val

    @property
    def freq(self) -> float:
        return self.data["freq"]

    @freq.setter
    def freq(self, val: float) -> None:
        self.data["freq"] = val

    @classmethod
    def default_settings_header(cls, module_name: str) -> dict:
        return {}

    @classmethod
    def default_sterm_settings(cls, module_name: str = "") -> dict:
        return {
            "robot_name": ROBOT_NAME,
            "memory_type": "short_term",
            "module_name": module_name,
            "a": 0.25,
            "d": 0.66,
            "f_line": 0.10,
            "freq": 180,
            "sentence_base": 6,
            "summ_lengths": [8, 6, 4, 2]
        }

    @classmethod
    def default_lterm_settings(cls, module_name: str = "") -> dict:
        return {
            "robot_name": ROBOT_NAME,
            "memory_type": "long_term",
            "module_name": module_name,
            "a": 0.5,
            "d": 0.25,
            "f_line": 0.10,
            "freq": 180,
            "sentence_base": 10,
            "summ_lengths": [12, 8, 5, 3],
            "time_scale": timedelta(minutes=15).total_seconds(),
            "time_intv": timedelta(minutes=10).total_seconds(),
        }

    @classmethod
    def load_from_db(
        cls, db: Database, mem_type: str, module_name: str
    ) -> ForgettingSettings:
        settings = db.module_settings.find_one(
            filter={
                "robot_name": ROBOT_NAME,
                "memory_type": mem_type,
                "module_name": module_name,
            },
            projection={
                "_id": False,
                "robot_name": False,
                "memory_type": False,
                "module_name": False,
            },
        )

        if not settings:  # Load default settings
            settings = (
                cls.default_sterm_settings(module_name)
                if "short" in mem_type
                else (
                    cls.default_lterm_settings(module_name)
                    if "long" in mem_type
                    else {}
                )
            )
            # And save them to the database
            db.module_settings.insert_one(settings)

            del settings["robot_name"]
            del settings["memory_type"]
            del settings["module_name"]

        return ForgettingSettings(**settings)


DEFAULT_MEMORY_PARAMS = robot_settings = {
    "robot_name": ROBOT_NAME,
    "robot_alias": "インディー",
    "llm": {
        "url": "https://api.openai.com/v1",
        "api_key": "NONE",
        "model": "gpt-4o-mini",
        "lang": "ja",
        "system_prompt": "あなたは理化学研究所ガーディアンロボットプロジェクトによって開発されたロボット、インディーです。"
        + "\nあなたは場の状況に応じて気が利く返しをするロボットとしてデザインされています。"
        + "\n自分のことを指すときは「ワタシ」を使います。"
        + "\nロボットは音声対話を行うため、返答は1文か2文で行うことが望ましいです。"
        + "\n気が利いているとユーザに感じさせるために、時間や温度などの体感に関する表現については、比喩表現を多用してください。"
        + "\n相手から質問をされていない場合に限り、あなたから質問をしてみてください。",
        "prompts_coll": "llm_prompts",
        "defaults": {"temperature": 0.8},
        "not_log_db": {  # Rename this field in the DB to enable
            "host": "localhost",
            "port": 9010,
            "dbname": "llm_log",
            "coll": "llm_log",
        },
    },
    "embed_api": {
        "url": "https://api.openai.com/v1",
        "api_key": "NONE",
        "model": "text-embedding-3-small",
        "embed_db": f"~/.chromadb/{ROBOT_NAME}/memorydb",
    },
    "mem_eval": False,
    "memory_level": {"sm_lvl": 2, "stm_lvl": 2, "ltm_lvl": 2},
    "default_forgetting": {
        "short_term": ForgettingSettings.default_sterm_settings(),
        "long_term": ForgettingSettings.default_lterm_settings(),
    },
    "debug_msgs": False,
}


def get_default_params(params: dict | None) -> dict:
    memory_params = {}
    if not params:
        memory_params.update(DEFAULT_MEMORY_PARAMS)
    else:
        memory_params = params
        for k, v in DEFAULT_MEMORY_PARAMS.items():
            if k not in memory_params:
                memory_params[k] = v
    return memory_params
