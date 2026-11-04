from ...llm_module import LLMModule
from .abstract_event_generator import AbstractEventGenerator


class DefaultEventGenerator(AbstractEventGenerator):
    """対話履歴を元に単純に応答する例"""

    def __init__(self, config):
        self.llm_module = LLMModule(config)

    def generate(self, scenario, speaker_name, event, history, opts):
        prev_speaker = "[SPK2]"  # "相手"が話したと想定
        if len(history) > 0 and "utt" in history[-1]:
            prev_text = history[-1]["utt"]
        else:
            prev_text = ""
        sentence = self.llm_module.generate_utterance(
            event["actor"], prev_speaker, prev_text, history, opts
        )

        if sentence is None:
            return []

        generated = {
            "actor": event["actor"],
            "type": "action",
            "utterance": {"type": "normal", "sentence": sentence},
        }
        if "interruptable" in event:
            generated["interruptable"] = event["interruptable"]

        return [generated]
