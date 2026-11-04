import time

from .abst_event import AbstEvent


class IdlingEvent(AbstEvent):
    def __init__(self, event_data: dict, scenario: dict):
        super().__init__(event_data, scenario)

    def _proc(self, observations):
        # start waiting
        if self.timeout is None:
            self.timeout = self.data["timeout"]
            self.person_wait_start = time.time()

        # wait until timeout
        if self.timeout < time.time() - self.person_wait_start:
            self.timeout = None
            self.scenario.done_event()
            return None

        return [{"command": "waiting"}]
