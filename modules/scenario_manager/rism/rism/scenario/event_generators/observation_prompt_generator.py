from ...llm_module import LLMModule
from .abstract_event_generator import AbstractEventGenerator


class ObservationPromptGenerator(AbstractEventGenerator):
    """観測をを元に応答する例"""

    def __init__(self, config):
        self.llm_module = LLMModule(config)

    def generate(self, scenario, speaker_name, event, history, opts):
        prev_speaker = "[SPK2]"  # "相手"が話したと想定

        prev_text = self._generate_observation_prompt(event, opts)

        print(prev_text, "から次の発話を生成します")
        if len(scenario.scenario_manager.finished_events) > 0:
            prev_text = scenario.scenario_manager.finished_events[-1]["utterance"][
                "sentence"
            ]

        sentence = self.llm_module.generate_utterance(
            event["actor"], prev_speaker, prev_text, history, opts
        )
        print(sentence)
        return [
            {
                "actor": event["actor"],
                "type": "action",
                "utterance": {"type": "normal", "sentence": sentence},
            }
        ]

    def _generate_observation_prompt(self, event, observations):
        prompt = "現在得られている情報は"

        data = []
        for name, obs in observations.items():
            for o in obs:
                data.append(f"{o['event']}，")

        if len(data) == 0:
            prompt += "ありません。"
        else:
            prompt += "，" + "".join(data) + "です。"
        return prompt
