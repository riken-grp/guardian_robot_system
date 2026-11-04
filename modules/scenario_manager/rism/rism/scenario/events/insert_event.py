from .abst_event import AbstEvent


class InsertEvent(AbstEvent):
    def __init__(self, event_data: dict, scenario: dict):
        super().__init__(event_data, scenario)

    def _proc(self, observations):
        # insert cybertopic

        return [{"command": "skip"}]
