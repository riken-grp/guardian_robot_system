import random

from . import get_generator
from .abstract_event_generator import AbstractEventGenerator


class MultiGenAndSelectEventGenerator(AbstractEventGenerator):
    """複数のGeneratorによって生成した中から選択して応答する例"""

    def __init__(self, config):
        self.llm_modules = {}
        for name, params in config["generators"].items():
            self.llm_modules[name] = get_generator(name, params)

    def generate(self, scenario, speaker_name, event, history, opts):
        prev_speaker = "[SPK2]"  # "相手"が話したと想定
        if len(scenario.scenario_manager.finished_events) > 0:
            prev_text = scenario.scenario_manager.finished_events[-1]["sentence"]
        else:
            prev_text = ""

        sentences = []
        for name, generator in self.llm_modules.items():
            sentence = self.llm_module.generate_utterance(
                event["speaker"], prev_speaker, prev_text, history, opts
            )
            sentences.append(sentence)

        # 選び方は？
        sentence = random.choice(sentences)

        return [{"speaker": event["speaker"], "type": "normal", "sentence": sentence}]
