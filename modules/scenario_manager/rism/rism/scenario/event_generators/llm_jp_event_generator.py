import random
import re
from collections import defaultdict
from copy import copy, deepcopy
from logging import getLogger
from typing import List, Tuple

from bson.objectid import ObjectId
from pyindy.llm.llm_wrapper import getValidatedWrapper
from pyindy.mongo.internal_state_logger import get_internal_state_logger
from pyindy.mongo.dialogue_history_manager import DialogueHistoryManager
from pymongo import MongoClient

from .abstract_event_generator import AbstractEventGenerator
import pytz


class LlmJPEventGenerator(AbstractEventGenerator):
    """
    Event Generator that processes dialog responses using an LLM.
    We provide an example of a Scenario at the end of this file.
    """

    def __init__(self, config: dict) -> None:
        """
        The `config` object is a list of settings retrieved from the database.
        The object must have a mapping of robots called "robot_list",
        and each value of that mapping must have a mapping called "llm"
        with the following elements:
        - "url": HTTP Address of the LLM.
        - "model": Name of the model being used in generation.
        - "system_prompt": The prompt to preppend to every generation request.
          This will condition the model, i.e. with its training knowledge cutoff.
        """

        # One Wrapper per robot
        r_list = config["robot_list"]
        self.llm_wrappers = {
            k: getValidatedWrapper(
                r_conf["llm"]["url"],
                r_conf["llm"]["model"],
                r_conf["llm"]["system_prompt"],
                defaults=r_conf["llm"]["defaults"],
                log_db_info=(
                    {}
                    if "log_db" not in r_conf["llm"]
                    else r_conf["llm"]["log_db"]
                ),
            )
            for k, r_conf in r_list.items()
        }

        self._logger = getLogger(__name__)
        self.__roles = {"[SPK2]": "assistant", "[SPK1]": "user"}
        # YES, THERE ARE TWO SYMBOLS. 😱
        # Also, this captures some edge cases
        self.__ht_re = r"(?:#|＃)(\S*?)(?=#|＃|\Z)"
        self.__head_re = (
            r"(^(?:待つ(?:：|\:)|それから(?:？|\?)(?:：|\:)"
            + r"|聞き返し(?:：|\:)|無視(?:：|\:))?)(.+)$"
        )

        self.__eye_dict = defaultdict(lambda: "neutral1.jpg")
        self.__eye_dict.update(
            {
                "smiling": "smile.jpg",
                "excited": "smile.jpg",
                "cheering": "smile.jpg",
                "smile": "smile.jpg",
                "clapping": "smile.jpg",
                "cheering": "smile.jpg",
                "laughing": "smile.jpg",
                "thinking": "sad.jpg",
                "thoughtful": "sad.jpg",
                "sympathizing": "sad.jpg",
                "concerned": "sad.jpg",
                "bowing": "sad.jpg",
                "warning": "sad.jpg",
            }
        )

        self.__un_un = ["うん", "うん、うん", "う～ん", "うんうん", "うん～"]

        self.last_event = []

        self.last_user_uttr = {}

        # Database connection for Scenarios
        dbconf = config["db_config"]["scenario_db"]
        client = MongoClient(dbconf["host"], dbconf["port"])
        self.db = client[dbconf["dbname"]][dbconf["col_name"]]

        self.dia_db = {
            k: DialogueHistoryManager(
                o["host"], o["port"], k, o["action_dbname"]
            )
            for k, o in r_list.items()
        }

        internal_state_logger = get_internal_state_logger(config)
        self.internal_coll = (
            internal_state_logger.col
            if internal_state_logger is not None
            else None
        )

        self.__pymongo_tz = pytz.timezone("UTC")

    def generate(self, scenario, speaker_name, event, history, opts):
        """
        Generates a response based on the triggered event.
        The triggered event contains all necessary settings:
        - `generator`: Used to load the object that contains this function.
        - `prompt`: used to condition the next answer. Can be left blank.
        - `use_memories`: number of memories to include in the response. Defaults to 0.
        - `temperature`: control word diversity in response generation.
          Higher means more diverse but also potentially more nonsensical,
          while lower produces consistent yet boring output.
          Optional, with a default value of 0.6.
        - `stop`: token(s) that cause generation to stop when encountered.
          Optional, default value is ["\n","###"]
        """
        self._update_internal_running()

        ev_uttr = event["utterance"]
        robot_name = scenario.config["robots"][event["actor"]]
        is_hitorigoto = "hitorigoto" in ev_uttr and ev_uttr["hitorigoto"]

        if "loop" in ev_uttr:
            ev_copy = deepcopy(event)
            loops = ev_copy["utterance"]["loop"]
            return [self._create_dialogue_turn(ev_copy) for _ in range(loops)]

        memories = (
            0
            if "use_memories" not in ev_uttr
            else max(0, ev_uttr["use_memories"])
        )

        if "use_db_hist" in ev_uttr and ev_uttr["use_db_hist"]:
            hist_count = (
                10 if "hist_count" not in ev_uttr else ev_uttr["hist_count"]
            )

            db_hist = list(
                self.dia_db[robot_name].col.find(
                    filter={}, limit=hist_count, sort=[("inserted", -1)]
                )
            )

            llm_hist = [
                {
                    "role": "user" if d["name"] == "asr" else "assistant",
                    "content": d["text"],
                }
                for d in db_hist
            ]
        else:
            """
            NOTE:
            History is created from Scenario.generate
            The "[SPK1]" actor is the one that did not trigger the current event.
            The current event is a "generate" event assigned to "robot1"
            We assume, then, that "[SPK1]" is the user.
            """
            # Formatting history for LLM API
            llm_hist = [
                {"role": self.__roles[d["spk"]], "content": d["utt"]}
                for d in history
                if d["utt"]  # Skip empty history?
            ]

        if (
            llm_hist[-1]["role"] != "user" and
            not is_hitorigoto
        ):
            llm_hist.append({"role": "user", "content": "うん。"})

        new_user_uttr = {}
        for d in history[::-1]:
            if d["spk"] == "[SPK1]":
                new_user_uttr = d
                break

        # IF we are generating after a 持つ event...
        # AND the user hasn't said anything...
        if (
            "wait_uttr" in ev_uttr
            and ev_uttr["wait_uttr"]
            and new_user_uttr == self.last_user_uttr
        ):
            # Return the old response.
            w_resp, w_tags = ev_uttr["wait_uttr"]
            return [self._create_utterance_event(event, w_resp, w_tags)]
        # OTHERWISE continue as usual.
        self.last_user_uttr = new_user_uttr

        # Dialog History sent to LLM must be less than 20 entries
        if len(llm_hist) > 20:
            llm_hist = llm_hist[-20:]

        # self._logger.debug(f"Dialog History: {llm_hist}")

        # self._logger.debug(f"Finished Events: {scenario.finished_events}")

        llm_temp = ev_uttr["temperature"] if "temperature" in ev_uttr else 0.6

        llm_stop = ev_uttr["stop"] if "stop" in ev_uttr else ["\n", "###"]

        llm_timeout = (
            ev_uttr["llm_timeout"] if "llm_timeout" in ev_uttr else 60
        )

        max_tokens = (
            ev_uttr["llm_max_tokens"] if "llm_max_tokens" in ev_uttr else 100
        )

        retries = 5

        if not is_hitorigoto and llm_hist and llm_hist[-1]["role"] == "user":

            preprompt = []
            postprompt = []
            if memories > 0:
                preprompt.append(
                    self._create_system_prompt(
                        self.__use_memories(opts, memories).strip()
                    )
                )
            if "prompt" in ev_uttr and ev_uttr["prompt"]:
                postprompt.append(
                    self._create_system_prompt(ev_uttr["prompt"].strip())
                )

            resp = self.llm_wrappers[robot_name].get_response(
                scenario.prompt,
                preprompt + llm_hist + postprompt,
                temperature=llm_temp,
                stop=llm_stop,
                retries=retries,
                timeout=llm_timeout,
                max_tokens=max_tokens,
            )
        else:  # Indy is talking to itself --> Turn into Instruct prompt
            # Add 'system' role prompts
            sys_prompts = []
            if memories > 0:
                sys_prompts.append(
                    self._create_system_prompt(
                        self.__use_memories(opts, memories)
                    )
                )
            if llm_hist:
                sys_prompts.append(
                    self._create_system_prompt(
                        self._create_dialogue_string(llm_hist)
                    )
                )
            if "prompt" in ev_uttr and ev_uttr["prompt"]:
                sys_prompts.append(
                    self._create_system_prompt(ev_uttr["prompt"])
                )

            resp = self.llm_wrappers[robot_name].get_response(
                scenario.prompt,
                sys_prompts,
                temperature=llm_temp,
                stop=llm_stop,
                retries=retries,
                timeout=llm_timeout,
                max_tokens=max_tokens,
            )

        self._logger.info(f"Generated Response: {resp}")
        cmd, resp, tags = self._parse_utterance(resp)

        if "待つ" in cmd:
            # Generate Wait event?
            wait_event = {
                "actor": event["actor"],
                "type": "command",
                "command": "wait",
                "timeout": 5 + random.triangular(-0.5, 0.5),
                "interruptable": True,
            }

            generated_event = copy(event)
            generated_event["utterance"]["wait_uttr"] = [resp, tags]

            event_list = [
                wait_event,
                generated_event,
            ]

            self.last_event = event_list if event_list else self.last_event

            return event_list  # not part of the looping options

        elif "それから" in cmd:
            event_list = [self._create_nodding_event(event)]
        elif "聞き返し" in cmd:
            last_event = {}
            for e in self.last_event[::-1]:
                if "utterance" in e:
                    last_event = e
                    break
            # TODO: Test. Particularly when combined with the utterance.
            event_list = [last_event]
        elif "無視" in cmd:
            # The utterance is recorded in the Action Executor.
            new_uttr_event = self._create_utterance_event(event, resp, tags)
            new_uttr_event["command"] = "skip"  # This might skip it?
            event_list = [new_uttr_event]
        else:  # Default
            event_list = [self._create_utterance_event(event, resp, tags)]

        self.last_event = event_list if event_list else self.last_event

        """
        loop-related stuff
          ev_uttr["loop"]  <-- Numper of loops
          ev_uttr["loopback_id"]  <-- Id of previous event
        """

        if (
            "loop" in ev_uttr
            and "loopback_id" in ev_uttr
            and "_id" in event
            and ev_uttr["loop"] > 0
        ):
            event_loop = self._retrieve_event_loop(
                scenario, ev_uttr["loopback_id"], event["_id"]
            )
            if event_loop:
                event_loop[-1]["utterance"]["loop"] = ev_uttr["loop"] - 1
                event_list += event_loop

        return event_list

    def __use_memories(self, observations, to_use) -> str:
        if to_use == 0:
            return ""

        physical_obs = list(
            filter(
                lambda d: d["event"] == "memory_recall",
                observations["physical"],
            )
        )

        if not physical_obs:
            return "\nこの会話の関係な思い出を特に覚えられません。"

        observed = physical_obs[-1]
        observed["mentioned"] = True

        return (
            "\n覚えているいくつかのことは次のとおりです：「"
            + " ".join(
                m["memory"].strip()
                for i, m in enumerate(observed["contents"]["recalled"])
                if i < to_use
            )
            + "」"
        )

    def _parse_utterance(self, utt: str) -> Tuple[str, str, List[str]]:
        # Get HEAD of string
        m = re.match(self.__head_re, utt)
        if m is None:
            return ("", "", [])
        head = m.group(1).strip()
        utt = m.group(2).strip()

        tags = [m.group(1).strip() for m in re.finditer(self.__ht_re, utt)]
        tags = [t for t in tags if t]

        utt = re.sub(self.__ht_re, "", utt).strip()

        return (head, self._sanitize_response(utt), tags)

    def _create_utterance_event(self, event, resp, tags) -> dict:
        generated = {
            "actor": event["actor"],
            "type": "action",
            "utterance": {"type": "normal", "sentence": resp},
            "interruptable": True,
        }

        self._attach_action_primitives(generated, tags)
        return generated

    def _create_nodding_event(self, event) -> dict:
        return {
            "actor": event["actor"],
            "type": "action",
            "utterance": {
                "type": "normal",
                "sentence": random.choice(self.__un_un),
            },
            "gesture": {
                "type": "normal",
                "command": "nodding",
                "duration": 1,
            },
            "interruptable": False,
        }

    def _attach_action_primitives(self, action: dict, htags: List[str]):
        if not htags:
            return

        if len(htags) > 1:
            self._logger.warning(
                f"Found Hashtags: {htags}."
                + "Only first tag will be used in Gesture Generation."
            )

        gest_tag = htags[0]

        action["eye"] = {
            "type": "normal",
            "image": self.__eye_dict[gest_tag],
            "duration": 10,
        }

        action["gesture"] = {
            "type": "normal",
            "command": gest_tag,
            "offset": 3,  # Why is it 3?
        }

    def _sanitize_response(self, resp: str) -> str:
        # Pattern 1: 4 repetitions into 1
        repeat4pattern = r"(\S+)\1\1\1"
        m = re.match(repeat4pattern, resp, re.I)
        while m:
            resp = re.sub(repeat4pattern, r"\1", resp)
            m = re.match(repeat4pattern, resp, re.I)

        # Pattern 2: Emoji, etc.
        # Based off: https://stackoverflow.com/a/33417311
        emojiPattern = (
            "["
            + "\U00002600-\U000027bf"  # symbols & dingbats
            + "\U0001f600-\U0001f64f"  # emoticons
            + "\U0001f300-\U0001f5ff"  # symbols & pictographs
            + "\U0001f680-\U0001f6ff"  # transport & map symbols
            + "\U0001f1e0-\U0001f1ff"  # flags (iOS)
            + "\U0001f900-\U0001f9ff"  # supp. symbols
            + "\U0001fa70-\U0001faff"  # supp. symbols ext. A
            + "]+"
        )

        resp = re.sub(emojiPattern, "", resp, flags=re.UNICODE)

        # RESERVED FOR FUTURE HEURISTICS/PATTERNS

        return resp

    def _retrieve_event_loop(
        self, scenario, start_event_id: ObjectId, end_event_id: ObjectId
    ) -> List[dict]:
        curr_scenario = self.db.find_one(
            filter={
                "events._id": {"$exists": True, "$eq": scenario.scenario_id}
            }
        )

        if curr_scenario is None:
            return []

        event_loop = []
        for e in curr_scenario["events"]:
            if "_id" in e and e["_id"] == start_event_id:
                event_loop.append(e)
            elif "_id" in e and e["_id"] == end_event_id:
                event_loop.append(e)
                break
            elif event_loop:
                event_loop.append(e)

        return event_loop

    def _create_system_prompt(self, prompt: str) -> dict:
        return {
            "role": "system",
            "content": "\n" + prompt.strip(),
        }

    def _create_dialogue_string(self, history: List[dict]) -> str:
        return (
            "\n\nhistory:\n"
            + "\n".join(
                f"{dt['role']}: {dt['content']}"
                for dt in history
                if dt["role"] != "system"
            )
            + "\n\n"
        )

    def _create_dialogue_turn(self, event) -> dict:
        _id = ObjectId()
        ev_uttr = event["utterance"]
        interruptable = event["interruptable"]
        timeout = ev_uttr["timeout"] if "timeout" in ev_uttr else 10
        response_prompt = ev_uttr["prompt"] if "prompt" in ev_uttr else ""
        temperature = (
            ev_uttr["temperature"] if "temperature" in ev_uttr else 0.8
        )
        use_memories = (
            ev_uttr["use_memories"] if "use_memories" in ev_uttr else 0
        )
        recall_limit = (
            ev_uttr["recall_limit"] if "recall_limit" in ev_uttr else 0.3
        )
        use_db_hist = (
            ev_uttr["use_db_hist"] if "use_db_hist" in ev_uttr else False
        )

        retVal = {
            "_id": _id,
            "actor": "robot1",
            "interruptable": interruptable,
            "type": "observation",
            "trigger": [{"asr": None}],
            "timeout": timeout,
            "success": [
                {
                    "actor": "robot1",
                    "type": "action",
                    "interruptable": interruptable,
                    "recall": {
                        "type": "blank",
                        "query": f"{{buffer[{str(_id)}][contents][words]}}",
                        "max_n": use_memories,
                        "limit": recall_limit,
                    },
                },
                {
                    "actor": "robot1",
                    "interruptable": interruptable,
                    "type": "action",
                    "utterance": {
                        "type": "generate",
                        "generator": "LlmJPEventGenerator",
                        "prompt": response_prompt,
                        "sentence": "",
                        "temperature": temperature,
                        "use_memories": use_memories,
                        "use_db_hist": use_db_hist,
                    },
                },
            ],
            "failure": [
                self._create_utterance_event(
                    event=event,
                    resp=random.choice(
                        [
                            "まだ聞いていらっしゃいますか？",
                            "お話、続いていますでしょうか？",
                            "少々、間が空きましたが...",
                        ]
                    ),
                    tags=["concerned"],
                ),
                event,
            ],
        }
        return retVal

    def _update_internal_running(self) -> None:
        if self.internal_coll is None:
            return
        status = self.internal_coll.find_one(
            filter={"_name": "status", "status": "running"}
        )
        self.scenario_t0 = None if status is None else status["last_update"]


# SAMPLE SCENARIO: User speaks, Indy responds speaking like an Edo-period samurai.
# {
# 	_id:ObjectId('XYZ'),
# 	name:'llm-jp sample scenario',
# 	status: 'active',
# 	priority: 1,
# 	event: [
#         {
# 			actor: 'person',
# 			interruptable: false,
# 			type: 'asr',
# 			timeout: 10,
# 		}、
# 		{
# 			actor: 'robot1',
# 			utterance: {
# 				type: 'generate',
# 				sentence: '',
# 				generator: 'LlmJPEventGenerator',
#               prompt: '江戸時代の侍っぽいで答えて下さい。'
#               temperature: 0.6,
#               stop: ["\n","###"]
# 			},
# 			interruptable: false,
# 			type: 'action'
# 		},
# 	]
# }
