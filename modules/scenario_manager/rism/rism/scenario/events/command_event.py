from .abst_event import AbstEvent


class CommandEvent(AbstEvent):
    def __init__(self, event_data: dict, scenario: dict):
        super().__init__(event_data, scenario)

    def _proc(self, observations):
        # robot
        return self._process_command(observations)

    def _process_command(self, observations):
        ret = {}
        ret.update(self.data)
        ret["actor"] = "system"

        return [ret]
