from abc import ABC, abstractmethod


class AbstractScenarioGenerator(ABC):
    @abstractmethod
    def generate(self, config, observations):
        pass
