from .abstract_event_generator import AbstractEventGenerator


class FixedEventGenerator(AbstractEventGenerator):
    def __init__(self, config):
        self.config = config

    def generate(self, scenario, speaker_name, event, history, opts):
        return [
            {
                "speaker": "robot1",
                "type": "normal",
                "sentence": "話を変えようよ．",
                "interruptable": False,
            },
            {
                "speaker": "robot2",
                "type": "generate",
                "sentence": "",
                "interruptable": True,
            },
            {
                "speaker": "robot1",
                "type": "generate",
                "sentence": "",
                "interruptable": True,
            },
        ]
