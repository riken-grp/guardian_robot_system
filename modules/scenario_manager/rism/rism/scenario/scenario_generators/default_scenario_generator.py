from ...llm_module import LLMModule
from .abstract_scenario_generator import AbstractScenarioGenerator


class DefaultScenarioGenerator(AbstractScenarioGenerator):
    def __init__(self, config):
        self.config = config
        self.llm_module = LLMModule(config)

    def generate(self, config, observations):
        return self.llm_module.generate_scenario(observations)
