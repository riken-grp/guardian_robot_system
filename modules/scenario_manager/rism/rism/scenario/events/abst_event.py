class AbstEvent:
    def __init__(self, event_data: dict, scenario: dict):
        self.data = event_data
        self.scenario = scenario

        self.type = event_data["type"]
        self.scenario_trigger = scenario.scenario_data["triggered"]

    def proc(self, observations):
        if "subscenario_activate" in self.data and self.data["subscenario_activate"]:
            self.scenario.activate_interaction(observations)
        else:
            self.scenario.deactivate_interaction(observations)

        ret = self._proc(observations)
        return ret

    def _proc_navigation(self, speaker_name, observations):
        ret = {}
        # ロボットによる移動の処理
        if "navigation" in self.data:
            navigation_type = self.data["navigation"]["type"]

            if navigation_type == "normal":
                # TODO ここで移動コマンド
                ret["navigation"] = {}
                ret["navigation"] = self.data["navigation"]
            elif navigation_type == "triggered":
                triggered_data = self.scenario.triggered_contents
                ret["navigation"] = {}
                ret["navigation"] = triggered_data

        return ret

    def _proc_eye(self, speaker_name, observations):
        ret = {}
        # ロボットによる目の処理
        if "eye" in self.data:
            eye_type = self.data["eye"]["type"]
            if eye_type == "generate":
                # ここで内容を生成する
                self.scenario.generate(speaker_name, self.data, observations)
                return {"command": "skip"}
            ret["eye"] = {}
            ret["eye"] = self.data["eye"]

        return ret

    def _proc_gesture(self, speaker_name, observations):
        ret = {}
        # ロボットによるジェスチャの処理
        if "gesture" in self.data:
            gesture_type = self.data["gesture"]["type"]
            if gesture_type == "generate":
                # ここで内容を生成する
                self.scenario.generate(speaker_name, self.data, observations)
                return {"command": "skip"}
            # TODO ここでジェスチャコマンド
            ret["gesture"] = {}
            ret["gesture"] = self.data["gesture"]

        return ret

    def _proc_utterance(self, speaker_name, observations):
        ret = {}
        # ロボットによる発話の処理
        if "utterance" in self.data:
            sentence_type = self.data["utterance"]["type"]
            orig_sentence = self.data["utterance"]["sentence"]

            ret["utterance"] = {}

            if sentence_type == "generate":
                # ここで内容を生成する
                self.scenario.generate(speaker_name, self.data, observations)
                return {"command": "skip"}
            elif sentence_type == "file":
                sentence = orig_sentence
                if "english" in self.data["utterance"]:
                    ret["utterance"]["english"] = self.data["utterance"]["english"]
                ret["utterance"]["file"] = self.data["utterance"]["file"]
            elif sentence_type == "blank":
                # ここで穴埋めして返す
                # 一般化するなら，これもGeneratorにする
                sentence = self._fill_in_blanks(orig_sentence, observations)
                self.data["utterance"]["sentence"] = sentence
                self.data["type"] = "normal"
                self.data["orig_type"] = "blank"
            else:
                # そのまま返す
                if "english" in self.data["utterance"]:
                    ret["utterance"]["english"] = self.data["utterance"]["english"]
                sentence = orig_sentence

            ret["utterance"]["sentence"] = sentence

        return ret

    def _proc_ros_command(self, speaker_name, observations):
        ret = {}
        # ロボットによるROSトピック発行
        if "ros_command" in self.data:
            ret["ros_command"] = self.data["ros_command"]

        return ret

    def _fill_in_blanks(self, target, observations):
        # 例えば
        # targetは "こんにちは．ここに{t[object]}があるよ．{t[color]}色をしているよ．"という形式
        # observationsには，observations["object"]やobservations["color]"があるとする．
        try:
            return target.format(
                observation=observations,
                triggered=self.scenario.triggered_contents,
                buffer=self.scenario.observation_buffer,
            )
        except KeyError as e:
            print(f"KeyError: {e} in target: {target}")
            return "そっか"

    def _proc_recall(self, speaker_name, observations):
        ret = {}

        if "recall" in self.data:
            ret["recall"] = self.data["recall"]
            _type = self.data["recall"]["type"]

            if (
                _type == "normal" and not self.data["recall"]["query"]
            ) or _type == "robot":

                finished_events = self.scenario.scenario_manager.finished_events
                last_utt = ""

                for e in reversed(finished_events):
                    if (
                        "utterance" in e
                        and "sentence" in e["utterance"]
                        and (
                            "add_context" not in e["utterance"]
                            or not e["utterance"]["add_context"]
                        )
                    ):
                        last_utt = e["utterance"]["sentence"]
                        break
                self.data["recall"]["query"] = last_utt
            elif _type == "blank":
                ret["recall"]["query"] = self._fill_in_blanks(
                    ret["recall"]["query"], observations
                )

        return ret
