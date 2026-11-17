import random
import re
from collections import defaultdict
from copy import copy
from datetime import datetime
from logging import getLogger
from typing import List, Optional, Tuple

from pyindy.llm.llm_wrapper import getValidatedWrapper
from pyindy.mongo.internal_state_logger import get_internal_state_logger
from pyindy.mongo.dialogue_history_manager import DialogueHistoryManager
from ..database import shared_client, use_shared_client

from .abstract_event_generator import AbstractEventGenerator
from .generator_utils import GREETINGS, describe_recent_observations, fill_placeholders


class LlmJPEventGenerator(AbstractEventGenerator):
    """
    Event Generator that processes dialog responses using an LLM.
    We provide an example of a Scenario at the end of this file.
    """

    # 履歴の話者（[SPK2] がこのロボット、[SPK1] が相手）→ LLM の role
    __roles = {"[SPK2]": "assistant", "[SPK1]": "user"}
    # ハッシュタグ（# と全角の ＃ の両方）
    __ht_re = r"(?:#|＃)(\S*?)(?=#|＃|\Z)"
    # 応答の先頭のコマンド（待つ / それから / 聞き返し / 無視）と本文
    __head_re = (
        r"(^(?:待つ(?:：|\:)|それから(?:？|\?)(?:：|\:)"
        + r"|聞き返し(?:：|\:)|無視(?:：|\:))?)(.+)$"
    )
    # ハッシュタグ → 目の画像（ないタグは neutral1.jpg）
    __eye_dict = defaultdict(lambda: "neutral1.jpg", {
        "smiling": "smile.jpg",
        "excited": "smile.jpg",
        "cheering": "smile.jpg",
        "smile": "smile.jpg",
        "clapping": "smile.jpg",
        "laughing": "smile.jpg",
        "thinking": "sad.jpg",
        "thoughtful": "sad.jpg",
        "sympathizing": "sad.jpg",
        "concerned": "sad.jpg",
        "bowing": "sad.jpg",
        "warning": "sad.jpg",
    })
    # 「それから？」のときの相槌
    __un_un = ["うん", "うん、うん", "う～ん", "うんうん", "うん～"]

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
        self._logger = getLogger(__name__)
        r_list = config["robot_list"]

        # One Wrapper per robot
        self.llm_wrappers = {
            k: getValidatedWrapper(
                r_conf["llm"]["url"],
                r_conf["llm"]["model"],
                r_conf["llm"]["system_prompt"],
                defaults=r_conf["llm"]["defaults"],
                log_db_info=r_conf["llm"].get("log_db", {}),
            )
            for k, r_conf in r_list.items()
        }

        self.last_event = []
        self.last_user_uttr = {}

        # Database connection for Scenarios
        dbconf = config["db_config"]["scenario_db"]
        self.db = shared_client(dbconf["host"], dbconf["port"])[dbconf["dbname"]][dbconf["col_name"]]

        self.dia_db = {
            k: use_shared_client(DialogueHistoryManager(o["host"], o["port"], k, o["action_dbname"]),
                                 o["host"], o["port"], o["action_dbname"], "dialogue_history")
            for k, o in r_list.items()
        }

        internal_state_logger = get_internal_state_logger(config)
        self.internal_coll = internal_state_logger.col if internal_state_logger is not None else None

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
        - `hist_len`: number of most recent history turns to send.
          0 sends no history. Optional, default uses up to 20 turns.
        """
        self._update_internal_running()

        ev_uttr = event["utterance"]
        robot_name = scenario.config["robots"][event["actor"]]
        llm_hist = self._build_history(ev_uttr, history, robot_name)

        # 「待つ」のあとで相手がまだ何も言っていなければ、前に作った発話をそのまま使う
        new_user_uttr = next((d for d in history[::-1] if d["spk"] == "[SPK1]"), {})
        if ev_uttr.get("wait_uttr") and new_user_uttr == self.last_user_uttr:
            w_resp, w_tags = ev_uttr["wait_uttr"]
            return [self._create_utterance_event(event, w_resp, w_tags)]
        self.last_user_uttr = new_user_uttr

        cmd, resp, tags = self._respond(scenario, robot_name, ev_uttr, llm_hist, opts)
        event_list = self._events_for_command(event, cmd, resp, tags)
        self.last_event = event_list or self.last_event
        return event_list

    def _build_history(self, ev_uttr: dict, history: List[dict], robot_name: str) -> List[dict]:
        """
        LLM に渡す会話履歴（{"role", "content"} のリスト）

        use_db_hist なら dialogue_history から、そうでなければシナリオの会話履歴から作る
        （"[SPK1]" は今の generate イベントの actor ではない話者、つまり相手）。
        最後が相手の発話でなければ「うん。」を足す（独り言を除く）。最大 20 件、hist_len があればその件数。
        """
        if ev_uttr.get("use_db_hist"):
            db_hist = list(self.dia_db[robot_name].col.find(
                filter={}, limit=ev_uttr.get("hist_count", 10), sort=[("inserted", -1)]))
            llm_hist = [{"role": "user" if d.get("name") == "asr" else "assistant", "content": d.get("text", "")}
                        for d in db_hist if d.get("text")]
        else:
            llm_hist = [{"role": self.__roles[d["spk"]], "content": d["utt"]} for d in history if d["utt"]]

        if llm_hist and llm_hist[-1]["role"] != "user" and not ev_uttr.get("hitorigoto"):
            llm_hist.append({"role": "user", "content": "うん。"})
        llm_hist = llm_hist[-20:]

        # hist_len を指定したイベントは直近の履歴だけを使う（前の場面の発話に引きずられるのを防ぐ）。0 なら渡さない
        hist_len = ev_uttr.get("hist_len")
        if isinstance(hist_len, int) and not isinstance(hist_len, bool) and hist_len >= 0:
            llm_hist = llm_hist[-hist_len:] if hist_len > 0 else []
        return llm_hist

    def _build_messages(self, hist: List[dict], ev_uttr: dict, opts) -> List[dict]:
        """
        LLM に送るメッセージ

        相手の発話に答えるときは、記憶 + 履歴 + 指示。独り言（または相手の発話がないとき）は、
        記憶・履歴・指示をすべて system にして、指示に従って話させる。
        """
        memories = max(0, ev_uttr.get("use_memories", 0))
        event_prompt = self._event_prompt(ev_uttr, opts)
        if not ev_uttr.get("hitorigoto") and hist and hist[-1]["role"] == "user":
            pre = [self._create_system_prompt(self.__use_memories(opts, memories).strip())] if memories > 0 else []
            post = [self._create_system_prompt(event_prompt.strip())] if event_prompt else []
            return pre + hist + post

        messages = []
        if memories > 0:
            messages.append(self._create_system_prompt(self.__use_memories(opts, memories)))
        if hist:
            messages.append(self._create_system_prompt(self._create_dialogue_string(hist)))
        if event_prompt:
            messages.append(self._create_system_prompt(event_prompt))
        return messages

    @staticmethod
    def _llm_settings(ev_uttr: dict) -> dict:
        """LLM に渡す設定（イベントで指定がなければ既定値）"""
        return {
            "temperature": ev_uttr.get("temperature", 0.6),
            "stop": ev_uttr.get("stop", ["\n", "###"]),
            "timeout": ev_uttr.get("llm_timeout", 60),
            "max_tokens": ev_uttr.get("llm_max_tokens", 100),
        }

    def _respond(self, scenario, robot_name: str, ev_uttr: dict, llm_hist: List[dict], opts):
        """
        発話を作る。前の発話の繰り返しや、どこにも出てこない人の名前なら1回だけ作り直し、それでもだめなら何も言わない

        Returns:
            (コマンド, 発話, ハッシュタグ)
        """
        settings = self._llm_settings(ev_uttr)

        def ask(messages, temperature):
            return self.llm_wrappers[robot_name].get_response(
                scenario.prompt, messages, temperature=temperature, stop=settings["stop"],
                retries=1,  # pyindy の llm_wrapper が毎回 retries 回リクエストを送るため 1
                timeout=settings["timeout"], max_tokens=settings["max_tokens"])

        resp = ask(self._build_messages(llm_hist, ev_uttr, opts), settings["temperature"])
        self._logger.info(f"Generated Response: {resp}")
        cmd, resp, tags = self._parse_utterance(resp)

        # 履歴にある自分の発話をそのまま繰り返した場合（履歴に残っているとまた写すので、それを外して作り直す）
        if self._is_repeated(resp, llm_hist):
            rest = self._without_repeated_opening(resp, llm_hist)
            if rest is not None:
                # 繰り返したのが書き出しの文（「お疲れさまです！」など）だけなら、その文を除いて話す
                self._logger.info(f"Generated response repeats only its opening, saying the rest: {rest}")
                return cmd, rest, tags
            self._logger.info("Generated response repeats a previous utterance, regenerating")
            retry_hist = [d for d in llm_hist if not self._is_repeated(resp, [d])]
            retry_resp = ask(self._build_messages(retry_hist, ev_uttr, opts)
                             + [self._create_system_prompt(self.REPEAT_AVOID_PROMPT)],
                             min(settings["temperature"] + 0.3, 1.0))
            self._logger.info(f"Generated Response (retry): {retry_resp}")
            cmd, resp, tags = self._parse_utterance(retry_resp)
            if self._is_repeated(resp, llm_hist):
                rest = self._without_repeated_opening(resp, llm_hist)
                if rest is None:
                    self._logger.warning("Generated response still repeats a previous utterance, saying nothing")
                    return "", "", []
                self._logger.info(f"Regenerated response repeats only its opening, saying the rest: {rest}")
                resp = rest

        # 指示にも履歴にも出てこない人の名前（LLM が作った名前）を言った場合
        allowed_text = self._event_prompt(ev_uttr, opts) + "".join(d["content"] for d in llm_hist)
        unknown = self._unknown_names(resp, allowed_text)
        if unknown:
            self._logger.info(f"Generated response names unknown people {unknown}, regenerating")
            retry_resp = ask(self._build_messages(llm_hist, ev_uttr, opts), settings["temperature"])
            self._logger.info(f"Generated Response (retry): {retry_resp}")
            cmd, resp, tags = self._parse_utterance(retry_resp)
            unknown = self._unknown_names(resp, allowed_text)
            if unknown:
                self._logger.warning(f"Generated response still names unknown people {unknown}, saying nothing")
                return "", "", []
        return cmd, resp, tags

    def _events_for_command(self, event, cmd: str, resp: str, tags: List[str]) -> List[dict]:
        """LLM の応答の先頭のコマンド（待つ / それから / 聞き返し / 無視）に応じて、実行するイベントを作る"""
        if "待つ" in cmd:
            # 少し待ってから、相手が何も言わなければこの発話を話す
            wait_event = {
                "actor": event["actor"],
                "type": "command",
                "command": "wait",
                "timeout": 5 + random.triangular(-0.5, 0.5),
                "interruptable": True,
            }
            generated_event = copy(event)
            generated_event["utterance"]["wait_uttr"] = [resp, tags]
            return [wait_event, generated_event]
        if "それから" in cmd:
            return [self._create_nodding_event(event)]
        if "聞き返し" in cmd:
            # 前に話した発話を繰り返す
            return [next((e for e in self.last_event[::-1] if "utterance" in e), {})]
        if "無視" in cmd:
            # 発話は Action Executor が記録する
            skipped = self._create_utterance_event(event, resp, tags)
            skipped["command"] = "skip"
            return [skipped]
        return [self._create_utterance_event(event, resp, tags)]

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

        # navigationタグ（#move_to_xxx）をチェック
        nav_tags = [tag for tag in htags if tag.startswith("move_to_")]
        non_nav_tags = [tag for tag in htags if not tag.startswith("move_to_")]

        # navigationタグがある場合はnavigationアクションを追加
        if nav_tags:
            target = nav_tags[0].replace("move_to_", "")
            action["navigation"] = {
                "type": "normal",
                "option": {"target": target}
            }
            self._logger.debug(f"Added navigation to {target} from hashtag #{nav_tags[0]}")

        # gesture/eyeタグがある場合
        if non_nav_tags:
            if len(non_nav_tags) > 1:
                self._logger.warning(
                    f"Found Hashtags: {non_nav_tags}."
                    + " Only first tag will be used in Gesture Generation."
                )

            gest_tag = non_nav_tags[0]

            action["eye"] = {
                "type": "normal",
                "image": self.__eye_dict[gest_tag],
                "duration": 10,
            }

            action["gesture"] = {
                "type": "normal",
                "option": {
                    "command": gest_tag,
                    "offset": 3,  # Why is it 3?
                }
            }

    # 文の区切り（句点などで終わる一続き。最後は句点がなくてもよい）
    SENTENCE_PATTERN = re.compile(r"[^。．！？!?]+[。．！？!?]*")

    def _drop_repeated_sentences(self, resp: str) -> str:
        """
        同じ文の繰り返しを1つにする（「信じたいです。信じたいです。信じ」→「信じたいです。」）

        2回目以降に出てきた文と、前の文の書きかけ（途中で切れた最後の文）を除く。
        """
        kept, seen = [], set()
        for sentence in self.SENTENCE_PATTERN.findall(resp):
            core = re.sub(r"[\s。．！？!?、，…]", "", sentence)
            if not core:
                continue
            unfinished = not re.search(r"[。．！？!?]$", sentence.strip())
            if core in seen or (unfinished and any(s.startswith(core) for s in seen)):
                continue
            seen.add(core)
            kept.append(sentence)
        return "".join(kept).strip()

    # 履歴を「assistant: …」の形で渡すので、LLM がその書き方をまねて発話の頭に付けることがある
    ROLE_PREFIX_PATTERN = re.compile(r"^\s*(?:assistant|user|system)\s*[:：]\s*", re.IGNORECASE)

    def _sanitize_response(self, resp: str) -> str:
        resp = self.ROLE_PREFIX_PATTERN.sub("", resp)
        resp = self._drop_repeated_sentences(resp)

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

    REPEAT_AVOID_PROMPT = "これまでの発言と同じ文は使わず、違う内容を話して。"
    # 先頭がこの文字数だけ一致したら繰り返しとみなす
    REPEAT_PREFIX_LEN = 15

    def _without_repeated_opening(self, text: str, history: List[dict]) -> Optional[str]:
        """
        書き出しの文が履歴の自分の発話にある文と同じなら、その文を除いた残り。残りも繰り返しか短すぎれば None

        充電中のつぶやきでは、LLM が「お疲れさまです！もし〜」のように同じ書き出しを続けがちで、
        先頭の一致だけで繰り返しとみなすと、後半が新しくても何も話さなくなる。
        """
        def core(sentence: str) -> str:
            return re.sub(r"[\s。．！？!?、，…]", "", sentence)

        previous = {core(sentence) for d in history if d["role"] == "assistant"
                    for sentence in self.SENTENCE_PATTERN.findall(d["content"])}
        sentences = self.SENTENCE_PATTERN.findall(text)
        start = 0
        while start < len(sentences) and core(sentences[start]) in previous:
            start += 1
        if start == 0:
            return None
        rest = "".join(sentences[start:]).strip()
        if len(rest) < self.REPEAT_PREFIX_LEN or self._is_repeated(rest, history):
            return None
        return rest

    def _is_repeated(self, text: str, history: List[dict]) -> bool:
        """生成した発話が、履歴にある自分（assistant）の発話の繰り返しかを判定する"""
        text = text.strip()
        if len(text) < self.REPEAT_PREFIX_LEN:
            return False
        prefix = text[:self.REPEAT_PREFIX_LEN]
        return any(
            d["role"] == "assistant" and d["content"].strip().startswith(prefix)
            for d in history
        )

    # 「〇〇さん」「〇〇先生」などの〇〇（漢字・カタカナ・英字の続き）
    NAME_PATTERN = re.compile(r"([一-龥々ァ-ヴーA-Za-z]+)(?:さん|先生|くん|君|ちゃん|様|さま)")
    # 人の名前ではない呼び方
    NOT_NAMES = {"皆", "お客", "客", "研究員", "職員", "学生", "社員", "店員", "所長", "インディー"}

    def _unknown_names(self, text: str, allowed_text: str) -> List[str]:
        """text で呼んでいる人の名前のうち、allowed_text（指示と履歴）に出てこないもの"""
        return [name for name in dict.fromkeys(self.NAME_PATTERN.findall(text))
                if name not in self.NOT_NAMES and name not in allowed_text]

    GREETINGS = GREETINGS

    def _fill_prompt(self, prompt: str, opts=None) -> str:
        """
        プロンプト中の {変数} を置き換える

        {now}（現在時刻、例: 14時05分）、{greeting}（時間帯の挨拶）、{heard}（聞いた発話）、
        {triggered[名前]}（割り込みのきっかけの観測の値）、{wait_for.contents.text} など。
        置き換えられないものはそのまま残す。
        """
        return fill_placeholders(prompt, opts, now=datetime.now())

    def _observation_prompt(self, ev_uttr: dict, opts) -> str:
        """
        use_observations があれば、最近の観測の説明をプロンプトに足す文を作る

        use_observations: イベント名のリスト、または {イベント名: 表示する contents のフィールド名}
        observation_window: 何秒前までの観測を使うか（既定 60）
        """
        spec = ev_uttr.get("use_observations")
        if not spec:
            return ""
        return describe_recent_observations(opts, spec, ev_uttr.get("observation_window", 60))

    def _event_prompt(self, ev_uttr: dict, opts) -> str:
        """イベントの prompt（{変数} を置き換えたもの）と、最近の観測の説明をつなげる"""
        parts = [self._observation_prompt(ev_uttr, opts)]
        if ev_uttr.get("prompt"):
            parts.append(self._fill_prompt(ev_uttr["prompt"], opts))
        return "\n".join(p for p in parts if p)

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
