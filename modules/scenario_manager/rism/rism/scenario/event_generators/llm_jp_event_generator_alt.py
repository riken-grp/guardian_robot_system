import copy
import random
import re
import time
from collections import defaultdict
from datetime import datetime
from logging import getLogger
from typing import List, Tuple

from pyindy.mongo.database_manager import PhysicalDBReader
from pyindy.llm.llm_wrapper import getValidatedWrapper
from pyindy.mongo import GestureManager, UtteranceManager, RecallManager
from pyindy.mongo.dialogue_history_manager import DialogueHistoryManager
from pyindy.mongo.internal_state_logger import get_internal_state_logger
from pymongo import MongoClient

from .abstract_event_generator import AbstractEventGenerator


class LlmJPEventGeneratorAlt(AbstractEventGenerator):
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

        self.logger = getLogger(__name__)

        # Hashtag regexp
        # YES, THERE ARE TWO SYMBOLS. 😱
        self.hashtage_regex = r"(?:#|＃)(\S*?)(?=#|＃|\Z)"
        # Command detection regexp
        self.command_regex = (
            r"(^(?:待つ(?:：|\:)|それから(?:？|\?)(?:：|\:)"
            + r"|聞き返し(?:：|\:)|無視(?:：|\:))?)(.+)$"
        )

        # Eye based on hashtag
        self.eyes = defaultdict(lambda: "neutral1.jpg")
        self.eyes.update(
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

        # Database connection for Scenarios
        dbconf = config["db_config"]["scenario_db"]
        client = MongoClient(dbconf["host"], dbconf["port"])
        self.db = client[dbconf["dbname"]][dbconf["col_name"]]

        self._load_managers(r_list)

        self.latest_asr = {k: [] for k, _ in r_list.items()}
        self.latest_asr_id = {k: "-1" for k, _ in r_list.items()}

        internal_state_logger = get_internal_state_logger(config)
        self.internal_coll = (
            internal_state_logger.col
            if internal_state_logger is not None
            else None
        )

        self.fillers = [
            "うん",
            "んん",
            "ふん",
            "ぅん",
            "うぅん",
            "うむ",
            "うん",
        ]
        self.ask = ["フムフム", "それから？", "それで", "なるほど"]

        # For state checking
        self.last_event = []
        self.last_user_uttr = {}
        self.last_memory_id = None

    def generate(self, scenario, speaker_name, event, history, opts):

        self._update_internal_running()

        ev_uttr = event["utterance"]
        robot_name = scenario.config["robots"][event["actor"]]

        # Flags and settings
        is_hitorigoto = "hitorigoto" in ev_uttr and ev_uttr["hitorigoto"]
        timeout = ev_uttr["timeout"] if "timeout" in ev_uttr else 60
        retries = ev_uttr["retries"] if "retries" in ev_uttr else 1
        hist_count = ev_uttr["history"] if "history" in ev_uttr else 10

        t = time.time()
        stop_time = t + timeout

        while t < stop_time - 10:
            t = time.time()
            new_asr = self._load_asr(robot_name, n=hist_count)

            # IF we are generating the response after a 持つ event...
            # AND the user hasn't said anything...
            if "wait_uttr" in ev_uttr and ev_uttr["wait_uttr"] and not new_asr:
                # Return the old response.
                w_resp, w_tags = ev_uttr["wait_uttr"]
                return [self._create_utterance_event(event, w_resp, w_tags)]
            # OTHERWISE continue as usual.

            if new_asr or is_hitorigoto:
                # Add FILLER to Gesture (waiting)
                self._insert_filler(robot_name)

                if is_hitorigoto:
                    hist = self._get_history_prep(
                        self._get_hist(robot_name, hist_count)
                    )
                    res = self._get_hitorigoto_resp(
                        robot_name, hist, ev_uttr, scenario, opts
                    )
                else:
                    hist = self._get_history_roles(robot_name)
                    res = self._get_chat_response(
                        robot_name, hist, ev_uttr, scenario, opts
                    )
                self.logger.info(f"Generated Response: {res}")

                if res != "False":
                    # Process, generate
                    return self._construct_utterance_events(res, event)
                else:
                    if retries <= 0:
                        t = stop_time
                    if random.random() > 0.3:
                        f = random.choice(self.ask)
                        self.ut[robot_name].insert({"text": f})
                retries -= 1

            if random.random() > 0.5:
                self.gt[robot_name].insert(
                    {
                        "duration": 0.5,
                        "gesture": "look_down_s",
                        "command": "look_down_s",
                        "type": "normal",
                    }
                )
                print("insert")
                time.sleep(1.5)
            else:
                time.sleep(0.5)

        # Timed out
        hist = self._get_history_prep(self._get_hist(robot_name, hist_count))
        res = self._get_chat_response(
            robot_name, hist, ev_uttr, scenario, opts, always_respond=True
        )
        return self._construct_utterance_events(res, event)

    def _use_memories_hist(
        self, robot_name, history, ev_uttr, n=3, tol=0.3
    ) -> str:
        if not n:
            return ""

        timeout = ev_uttr["timeout"] / 10 if "timeout" in ev_uttr else 6

        query = self._create_dialogue_string(history).replace(
            "\n\nhistory:\n", ""
        )

        t = time.time()
        stop_time = t + timeout

        # Request memories
        self.rm[robot_name].insert(
            {
                "type": "normal",
                "query": query,
                "max_n": n,
                "limit": tol,
            }
        )
        delay_with_filler = True
        # Wait for memories
        while t < stop_time:
            t = time.time()
            # Check if new memories

            mems = self.pdbr[robot_name].db.find_one(
                filter={"mentioned": False, "event": "memory_recall"},
                sort=[("priority", -1), ("inserted", -1)],
            )
            if not mems:
                if delay_with_filler:
                    self._insert_filler(robot_name)
                    delay_with_filler = False
                time.sleep(1.0)
                continue

            recalled = mems["contents"]["recalled"]
            # We got memories!
            mem_prompt = (
                (
                    "\n覚えているいくつかのことは次のとおりです：「"
                    + "; ".join(m["memory"].strip() for m in recalled)
                    + "」"
                )
                if recalled
                else ""
            )

            self.pdbr[robot_name].set_mentioned(mems)

            return mem_prompt

        # Return memories
        print("Memory Retrieval Timeout")

        return ""

    def _parse_utterance(self, utt: str) -> Tuple[str, str, List[str]]:
        # Get HEAD of string
        m = re.match(self.command_regex, utt)
        if m is None:
            return ("", "", [])
        head = m.group(1).strip()
        utt = m.group(2).strip()

        tags = [
            m.group(1).strip() for m in re.finditer(self.hashtage_regex, utt)
        ]
        tags = [t for t in tags if t]

        utt = re.sub(self.hashtage_regex, "", utt).strip()

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
                "sentence": random.choice(self.fillers),
            },
            "gesture": {
                "type": "normal",
                "command": "nodding",
                "duration": 1,
            },
            "interruptable": False,
        }

    def _insert_filler(self, robot_name):
        filler = random.choice(self.fillers)
        self.ut[robot_name].insert({"text": filler})
        self.gt[robot_name].insert(
            {
                "duration": 1.0,
                "gesture": "look_slight_right",
                "command": "look_slight_right",
                "type": "normal",
            }
        )

    def _attach_action_primitives(self, action: dict, htags: List[str]):
        if not htags:
            return

        if len(htags) > 1:
            self.logger.warning(
                f"Found Hashtags: {htags}."
                + "Only one tag will be used in Gesture Generation."
            )

        for i, t in enumerate(htags):
            if t in self.eyes:
                break

        gest_tag = htags[i]

        action["eye"] = {
            "type": "normal",
            "image": self.eyes[gest_tag],
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

    def _update_internal_running(self) -> None:
        if self.internal_coll is None:
            return
        status = self.internal_coll.find_one(
            filter={"_name": "status", "status": "running"}
        )
        self.scenario_t0 = None if status is None else status["last_update"]

    def _get_hist(self, robot_name: str, n=10) -> list:
        return list(
            self.dia_db[robot_name].col.find().sort("inserted", -1).limit(n)
        )

    def _load_asr(self, robot_name: str, n=10, T=datetime.fromtimestamp(0)):
        new_asr = self._get_hist(robot_name, n)

        if not new_asr:
            return False

        for doc in new_asr:
            if doc["inserted"] < T:
                # Too old
                return False
            if doc["name"] != "asr":
                # Ignore non-asr
                continue
            _id = doc["_id"]
            if self.latest_asr_id[robot_name] == _id:
                # No new asr -- ignore
                return False
            self.latest_asr_id[robot_name] = _id
            self.latest_asr[robot_name] = new_asr
            return True
        return False

    def _get_history_prep(self, hist: list) -> list:
        return [
            {
                "role": "user" if d["name"] == "asr" else "assistant",
                "content": d["text"],
            }
            for d in hist
        ]

    def _get_history_roles(
        self, robot_name: str, enforce_last_user=True
    ) -> list:
        llm_hist = self._get_history_prep(self.latest_asr[robot_name])

        if enforce_last_user and llm_hist[-1]["role"] != "user":
            llm_hist.append(
                {"role": "user", "content": random.choice(self.fillers)}
            )

        return llm_hist

    def _get_chat_response(
        self,
        robot_name: str,
        hist: list,
        ev_uttr: dict,
        scenario,
        opts,
        always_respond=False,
    ) -> str:
        # Get Data from Event

        llm_temp = ev_uttr["temperature"] if "temperature" in ev_uttr else 0.6
        llm_stop = ev_uttr["stop"] if "stop" in ev_uttr else ["\n", "###"]
        llm_timeout = (
            ev_uttr["llm_timeout"] if "llm_timeout" in ev_uttr else 60
        )

        max_tokens = (
            ev_uttr["llm_max_tokens"] if "llm_max_tokens" in ev_uttr else 100
        )

        memories = (
            max(0, ev_uttr["use_memories"]) if "use_memories" in ev_uttr else 0
        )
        preprompt = ev_uttr["prompt"].strip() if "prompt" in ev_uttr else ""
        postprompt = (
            ev_uttr["postprompt"].strip() if "postprompt" in ev_uttr else ""
        )

        if not always_respond:
            preprompt += (
                "+相手の意図や発話の意味があいまいな時は False を返す。"
            )

        pre_turns = []
        post_turns = []

        if memories > 0:
            retrieved = self._use_memories_hist(
                robot_name, hist, ev_uttr, memories
            ).strip()
            if retrieved:
                pre_turns.append(self._create_system_prompt(retrieved))
        if postprompt:
            post_turns.append(self._create_system_prompt(postprompt))

        return self.llm_wrappers[robot_name].get_response(
            scenario.prompt + preprompt,
            pre_turns + hist + post_turns,
            temperature=llm_temp,
            stop=llm_stop,
            retries=1,
            timeout=llm_timeout,
            max_tokens=max_tokens,
        )

    def _get_hitorigoto_resp(
        self, robot_name: str, hist: list, ev_uttr: dict, scenario, opts
    ) -> str:
        llm_temp = ev_uttr["temperature"] if "temperature" in ev_uttr else 0.6
        llm_stop = ev_uttr["stop"] if "stop" in ev_uttr else ["\n", "###"]
        llm_timeout = (
            ev_uttr["llm_timeout"] if "llm_timeout" in ev_uttr else 60
        )

        max_tokens = (
            ev_uttr["llm_max_tokens"] if "llm_max_tokens" in ev_uttr else 100
        )

        memories = (
            max(0, ev_uttr["use_memories"]) if "use_memories" in ev_uttr else 0
        )

        postprompt = (
            ev_uttr["prompt"].strip() if "prompt" in ev_uttr else ""
        ) + (ev_uttr["postprompt"].strip() if "postprompt" in ev_uttr else "")

        sys_prompts = []

        if memories > 0:
            retrieved = self._use_memories_hist(
                robot_name, hist, ev_uttr, memories
            ).strip()
            if retrieved:
                sys_prompts.append(self._create_system_prompt(retrieved))

        if hist:
            hist_as_str = self._create_dialogue_string(hist)
            if hist_as_str:
                sys_prompts.append(self._create_system_prompt(hist_as_str))

        if postprompt:
            sys_prompts.append(self._create_system_prompt(postprompt))

        return self.llm_wrappers[robot_name].get_response(
            scenario.prompt,
            sys_prompts,
            temperature=llm_temp,
            stop=llm_stop,
            retries=1,
            timeout=llm_timeout,
            max_tokens=max_tokens,
        )

    def _construct_utterance_events(self, resp: str, event) -> list:
        cmd, resp, tags = self._parse_utterance(resp)
        if "待つ" in cmd:
            # Generate Wait event?
            wait_event = {
                "actor": event["actor"],
                "type": "command",
                "command": "wait",
                "timeout": 5 + random.triangular(-0.5, 0.5),
                "interruptable": False,
            }

            generated_event = copy.copy(event)
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

        return event_list

    def _load_managers(self, r_list) -> None:
        self.dia_db = {
            k: DialogueHistoryManager(
                o["host"], o["port"], k, o["action_dbname"]
            )
            for k, o in r_list.items()
        }

        self.ut = {
            k: UtteranceManager(o["host"], o["port"], k, o["action_dbname"])
            for k, o in r_list.items()
        }

        self.gt = {
            k: GestureManager(o["host"], o["port"], k, o["action_dbname"])
            for k, o in r_list.items()
        }

        self.rm = {
            k: RecallManager(o["host"], o["port"], k, o["action_dbname"])
            for k, o in r_list.items()
        }

        self.pdbr = {
            k: PhysicalDBReader(o["host"], o["port"], o["action_dbname"])
            for k, o in r_list.items()
        }
