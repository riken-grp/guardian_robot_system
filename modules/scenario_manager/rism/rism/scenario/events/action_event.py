from .abst_event import AbstEvent


class ActionEvent(AbstEvent):
    def __init__(self, event_data: dict, scenario: dict):
        super().__init__(event_data, scenario)

    def _proc(self, observations):
        # robot
        return self._process_robot_tern(observations)

    def _process_robot_tern(self, observations):
        ret = {}
        ret["actor"] = self.data["actor"]
        speaker_name = self.scenario.config["robot_list"][
            self.scenario.config["robots"][self.data["actor"]]
        ]["name_alias"]
        ret["name"] = speaker_name

        ret.update(self._proc_navigation(speaker_name, observations))
        ret.update(self._proc_eye(speaker_name, observations))
        ret.update(self._proc_gesture(speaker_name, observations))
        ret.update(self._proc_utterance(speaker_name, observations))
        ret.update(self._proc_ros_command(speaker_name, observations))
        ret.update(self._proc_recall(speaker_name, observations))

        return [ret]
