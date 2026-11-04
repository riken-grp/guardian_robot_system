from .abstract_event_generator import AbstractEventGenerator


class EchoBackEventGenerator(AbstractEventGenerator):
    """Echo back応答する例"""

    def __init__(self, config):
        self.config = config

    def generate(self, scenario, speaker_name, event, history, opts):
        generated = "ん"
        if "registered" in opts:
            if "observation_id" in opts["registered"]:
                generated = opts["registered"][event["observation_id"]]["contents"][
                    "words"
                ]

        return [generated]
