"""knowledge_event_generator.py - 登録した知識だけを使って質問に答える Event Generator"""
from logging import getLogger
from typing import Any, Dict, List

from .abstract_event_generator import AbstractEventGenerator
from .generator_utils import fill_placeholders, heard_text, make_speak_event, speak_option, with_speak_option

KNOWLEDGE_COLLECTION = "knowledge"

ANSWER_INSTRUCTION = (
    "次の情報だけを使って、相手の質問に短く答えて。"
    "情報に無いことは推測せず、わからないと正直に伝えて。"
)


class KnowledgeEventGenerator(AbstractEventGenerator):
    """
    聞いた発話に関係する知識（部屋・人・道順・研究内容など）を選び、それだけを LLM に渡して答える。

    LLM が場所や人について作り話をするのを防ぐ。
    知識はシナリオDBの knowledge コレクション、またはイベントの knowledge に書く:
        {"title": "トイレ", "keywords": ["トイレ", "お手洗い"], "text": "エレベーターの横、右手です。"}
    keywords のどれかが聞いた発話に含まれる知識を、当てはまった数の多い順に top_k 件まで使う。

    使用例:
        {"type": "action", "actor": "robot1",
         "speak": {"type": "generate", "option": {
             "generator": "KnowledgeEventGenerator",
             "prompt": "親しみやすい口調で。",
             "top_k": 3,
             "no_match_text": "すみません、それはわからないです。"}}}

    当てはまる知識が無いとき:
        no_match_text があればそれを話す。
        no_match_generator があれば、その Generator に同じイベントのまま任せる（雑談は LLM に、など）。
        どちらも無ければ「わからないと伝えて」と LLM に頼む。
    """

    def __init__(self, config: Dict[str, Any]):
        self._logger = getLogger(__name__)
        self.config = config
        self._collection = None
        self._llm = None
        self._others: Dict[str, AbstractEventGenerator] = {}

    def _knowledge_collection(self):
        """シナリオDBの knowledge コレクション（最初に使うときにつなぐ）"""
        if self._collection is None:
            from ..database import get_scenario_db_info, shared_client
            info = get_scenario_db_info(self.config.get("demo", {}))
            self._collection = shared_client(info["host"], info["port"])[info["db_name"]][KNOWLEDGE_COLLECTION]
        return self._collection

    def _all_knowledge(self, option: Dict[str, Any]) -> List[Dict[str, Any]]:
        entries = [k for k in option.get("knowledge", []) if isinstance(k, dict)]
        if option.get("use_db", True):
            try:
                entries += list(self._knowledge_collection().find({"status": {"$ne": "inactive"}}))
            except Exception as e:
                self._logger.error(f"[KnowledgeEventGenerator] could not read knowledge: {e}")
        return entries

    def select(self, heard: str, entries: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """聞いた発話に含まれるキーワードの数で知識を選ぶ"""
        scored = []
        for entry in entries:
            keywords = [k for k in entry.get("keywords", []) if isinstance(k, str) and k]
            score = sum(1 for k in keywords if k in heard)
            if score:
                scored.append((score, entry))
        scored.sort(key=lambda s: -s[0])
        return [entry for _, entry in scored[:top_k]]

    def generate(self, actor: str, event: Dict[str, Any], history: List[Dict[str, str]],
                 observations: Dict[str, Any]) -> List[Dict[str, Any]]:
        option = speak_option(event)
        heard = heard_text(observations)
        if not heard and history and history[-1].get("spk") == "[SPK1]":
            heard = history[-1].get("utt", "")
        chosen = self.select(heard, self._all_knowledge(option), option.get("top_k", 3)) if heard else []
        self._logger.info(
            f"[KnowledgeEventGenerator] heard='{heard}', knowledge={[k.get('title') for k in chosen]}")

        if not chosen and option.get("no_match_text"):
            return [make_speak_event(actor, event, fill_placeholders(option["no_match_text"], observations))]
        if not chosen and option.get("no_match_generator"):
            from . import get_generator
            name = option["no_match_generator"]
            if name not in self._others:
                self._others[name] = get_generator(name, self.config)
            return self._others[name].generate(actor, event, history, observations)

        if chosen:
            facts = "\n".join(f"- {k.get('title', '')}: {k.get('text', '')}" for k in chosen)
            instruction = f"{ANSWER_INSTRUCTION}\n情報:\n{facts}"
        else:
            instruction = "相手の質問には答えられない。「すみません、それはわからないです」のように、わからないことだけを一文で伝えて。"
        extra = option.get("prompt", "")
        prompt = f"{instruction}\n{extra}" if extra else instruction
        return self._llm_generator().generate(actor, with_speak_option(event, prompt=prompt), history, observations)

    def _llm_generator(self) -> AbstractEventGenerator:
        if self._llm is None:
            from . import get_generator
            self._llm = get_generator("LlmJPEventGenerator", self.config)
        return self._llm
