from .chatgpt_scenario_generator import ChatGPTScenarioGenerator
from .default_scenario_generator import DefaultScenarioGenerator


def get_generator(gen_name: str, config: dict):
    return globals()[gen_name](config)
