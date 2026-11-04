from .abstract_event_generator import AbstractEventGenerator


class RepeatEventGenerator(AbstractEventGenerator):
    def __init__(self, config):
        self.config = config

    def generate(self, scenario, speaker_name, event, history, opts):
        events = [
            {
                "speaker": "robot1",
                "type": "normal",
                "sentence": "話を変えようよ．",
                "interruptable": False,
            }
        ]
        for i in range(event["repeat"]):
            events.extend(
                [
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
            )
        return events
