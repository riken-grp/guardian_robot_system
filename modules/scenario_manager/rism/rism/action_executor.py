import time
from logging import getLogger
from typing import List

from bson import ObjectId
from pyindy.mongo import (EyeManager, GestureManager, NavigationManager,
                          ObservationManager, RecallManager, ROSCommandManager,
                          UtteranceManager)


class ActionManager:
    def __init__(self, config: dict) -> None:
        self.config: dict = config
        self.action_managers: dict = {}  # ActionManagers
        self._logger = getLogger(__name__)

        self.default_behavior = self.config["scenario_ignore_is_playing"]

    def is_playing(
        self,
        only_utterance=False,
    ):
        if len(self.action_managers) > 0:
            actor, am = list(self.action_managers.items())[0]

            try:
                if only_utterance and "utterance" in am:
                    return am["utterance"].get_num_playing() > 0

                total_playing = 0
                for name, flag in self.default_behavior.items():
                    if name in am:
                        if not flag:
                            total_playing += am[name].get_num_playing()
                return total_playing > 0
            except Exception as e:
                self._logger.error(f"Error in is_playing: {e}")
                return False

        return False

    def execute(self, actions: List[dict]) -> None:
        for action in actions:
            if "command" not in action:
                # TTS and Gesture
                if action["actor"] not in self.action_managers:
                    self._generate_action_manager(action)
                # action execute
                self._insert(action)

    def immediate_execute(self, action: dict) -> None:
        # TTS and Gesture
        if action["actor"] not in self.action_managers:
            self._generate_action_manager(action)

        self._insert(action)

    def reset_action_queue(self):
        for actor, manager in self.action_managers.items():
            self._logger.info("db reset")
            num_utterance = manager["utterance"].cancel_all(actor)
            num_gesture = manager["gesture"].cancel_all(actor)
            num_navigation = manager["navigation"].cancel_all(actor)
            num_eye = manager["eye"].cancel_all(actor)
            num_mem = manager["recall"].cancell_all(actor)
            self._logger.info(
                f"utterance:{num_utterance}, gesture:{num_gesture}, navigation:{num_navigation}, eye:{num_eye}, recall:{num_mem}"
            )

    def _generate_action_manager(self, contents: dict) -> None:
        speaker_alias = contents["name"]
        port = None

        for key, value in self.config["robot_list"].items():
            if "name_alias" in value and value["name_alias"] == speaker_alias:
                robot_id = key
                host = value["host"]
                port = value["port"]
                dbname = value["action_dbname"]
                break

        if port is None:
            raise ValueError("no port number is specified")

        self.action_managers[contents["actor"]] = {
            "utterance": UtteranceManager(host, port, robot_id, dbname),
            "gesture": GestureManager(host, port, robot_id, dbname),
            "navigation": NavigationManager(host, port, robot_id, dbname),
            "eye": EyeManager(host, port, robot_id, dbname),
            "ros_command": ROSCommandManager(host, port, robot_id, dbname),
            "observation": ObservationManager(host, port, robot_id, dbname),
            "recall": RecallManager(host, port, robot_id, dbname),
        }

    def _insert(self, contents):
        if "navigation" in contents:
            navigation = contents["navigation"]
            ret = self.action_managers[contents["actor"]]["navigation"].insert(
                navigation
            )
            time.sleep(0.1)
            if "navigation" in contents["navigation"]:
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['navigation']['navigation']}へ向かいます．"
                )
            elif "location_name" in contents["navigation"]:
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['navigation']['location_name']}へ向かいます．"
                )
            elif "rotate" in contents["navigation"]:
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['navigation']['rotate']}だけ回ります．"
                )
            elif "move" in contents["navigation"]:
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['navigation']['move']}だけ動きます．"
                )
            else:
                print(f"{contents['name']}さんが，動きます．")

        if "eye" in contents:
            eye = contents["eye"]
            ret = self.action_managers[contents["actor"]]["eye"].insert(eye)
            print(
                f"{contents['name']}さんが，目を「{contents['eye']['image']}」にしました．"
            )

        if "gesture" in contents:
            gesture = contents["gesture"]
            gesture["gesture"] = contents["gesture"]["command"]
            try:
                ret = self.action_managers[contents["actor"]]["gesture"].insert(gesture)
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['gesture']['command']}」をしました．"
                )
            except Exception as e:
                self._logger.error(f"Error in gesture insert: {e}")

        if "recall" in contents:
            recall = contents["recall"]
            try:
                ret = self.action_managers[contents["actor"]]["recall"].insert(recall)
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['recall']['query']}」の事を考えました。"
                )
            except Exception as e:
                self._logger.error(f"Error in recall insert: {e}")

        if "utterance" in contents:
            utterance = {"text": contents["utterance"]["sentence"]}
            if "file" in contents["utterance"]:
                utterance["file"] = contents["utterance"]["file"]
            if "english" in contents["utterance"]:
                utterance["english"] = contents["utterance"]["english"]
            try:
                ret = self.action_managers[contents["actor"]]["utterance"].insert(
                    utterance
                )
            except Exception as e:
                self._logger.error(f"Error in recall insert: {e}")
            if "command" in contents and contents["command"] == "skip":
                _id = ret.inserted_id
                try:
                    self.action_managers[contents["actor"]]["utterance"].set_status(
                        _id, "skipped"
                    )
                    print(
                        f"{contents['scenario']}: {contents['name']}さんが，音声認識を無視していました。なぜなら、「{contents['utterance']['sentence']}」です。"
                    )
                except Exception as e:
                    self._logger.error(f"Error in setting utterance status: {e}")
            else:
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['utterance']['sentence']}」と言いました．"
                )

        if "ros_command" in contents:
            command = contents["ros_command"]
            try:
                ret = self.action_managers[contents["actor"]]["ros_command"].insert(
                    command
                )
                print(
                    f"{contents['scenario']}: {contents['name']}さんが，「{contents['ros_command']['data']}」をしました．"
                )
            except Exception as e:
                self._logger.error(f"Error in ros_command insert: {e}")

        return ret

    def observation_insert(self, contents):
        try:
            ret = self.action_managers[contents["actor"]]["observation"].insert(
                contents
            )
            print(
                f"{contents['name']}さんが，「{contents['trigger']}」の観測を開始しました．"
            )
        except Exception as e:
            self._logger.error(f"Error in observation insert: {e}")
        return ret.inserted_id

    def observation_update(self, observation_id, actor, name, found):
        query = {"_id": ObjectId(observation_id)}
        data = {"found": found, "status": "done"}
        print(f"{name}さんが，「{found}」を発見しました．")
        try:
            ret = self.action_managers[actor]["observation"].update_many(
                query, {"$set": data}
            )
        except Exception as e:
            self._logger.error(f"Error in observation update: {e}")

    def observation_timeout(self, observation_id, actor, name, trigger):
        query = {"_id": ObjectId(observation_id)}
        data = {"status": "timeout", "found": None}
        try:
            ret = self.action_managers[actor]["observation"].update_many(
                query, {"$set": data}
            )
            print(f"{name}さんが，{trigger}を発見できませんでした．")
        except Exception as e:
            self._logger.error(f"Error in observation timeout: {e}")

    def observation_mismatch(self, observation_id, actor, name, trigger):
        query = {"_id": ObjectId(observation_id)}
        data = {"status": "mismatched", "found": None}
        try:
            ret = self.action_managers[actor]["observation"].update_many(
                query, {"$set": data}
            )
            print(f"{name}さんが，{trigger}を発見しましたが，内容が違いました．")
        except Exception as e:
            self._logger.error(f"Error in observation mismatch: {e}")

    def dump(self):
        # TODO: implement
        return ""

    def cancel_all(self):
        if len(self.action_managers) > 0:
            actor, ams = list(self.action_managers.items())[0]
            name, am = list(ams.items())[0]
            try:
                am.cancel_all()
            except Exception as e:
                self._logger.error(f"Error in cancel_all: {e}")

    def stop_all(self):
        if len(self.action_managers) > 0:
            actor, ams = list(self.action_managers.items())[0]
            name, am = list(ams.items())[0]
            try:
                am.stop_all()
            except Exception as e:
                self._logger.error(f"Error in stop_all: {e}")
