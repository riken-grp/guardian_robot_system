from .abst_event import AbstEvent


class ObservationEvent(AbstEvent):
    def __init__(self, event_data: dict, scenario: dict):
        super().__init__(event_data, scenario)

    def _proc(self, observations):
        # robot
        return self._process_robot_tern(observations)

    def _process_robot_tern(self, observations):
        speaker_name = self.scenario.config["robot_list"][
            self.scenario.config["robots"][self.data["actor"]]
        ]["name_alias"]
        com = {"command": "observation"}
        com["name"] = speaker_name
        com["orig_name"] = self.data["actor"]
        com.update(self.data)
        return [com]
