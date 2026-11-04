from __future__ import annotations

from os import getenv

ROBOT_NAME = getenv("ROBOT_NAME")


DEFAULT_RESPONDER_PARAMS = robot_settings = {
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
    "default_recall_params": {
        "max_n": 1,
        "limit": 1,
        "weight_age": 1,
        "weight_dist": 1,
    },
    "default_scenario_stop": {
        "keywords": ["バイバイ", "ばいばい", "バイバーイ", "ばいばーい"],
        "stop_phrase_length": 15,
        "stop_next_scenario": "",
    },
    "kw_interruptable_scenarios": ["waiting mode Standby"],
    "adintool_ports": [5567],
    "total_asr_timeout": 300,
    "debug_msgs": False,
    "initial_mode": "OFF"
}


def get_default_params(params: dict | None) -> dict:
    responder_params = {}
    if not params:
        responder_params.update(DEFAULT_RESPONDER_PARAMS)
    else:
        responder_params = params
        for k, v in DEFAULT_RESPONDER_PARAMS.items():
            if k not in responder_params:
                responder_params[k] = v
    return responder_params
