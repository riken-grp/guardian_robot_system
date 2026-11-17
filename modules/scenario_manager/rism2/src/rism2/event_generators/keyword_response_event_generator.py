"""keyword_response_event_generator.py - 聞いた発話のキーワードで決まった答えを返す Event Generator"""
import random
from logging import getLogger
from typing import Any, Dict, List, Optional

from .abstract_event_generator import AbstractEventGenerator
from .generator_utils import fill_placeholders, heard_text, make_speak_event, speak_option


class KeywordResponseEventGenerator(AbstractEventGenerator):
    """
    聞いた発話にキーワードが含まれていれば、決まった答えを返す。当てはまらなければ別の Generator に任せる。

    よくある質問（トイレ、会議室の場所など）に、LLM の作り話なしで正確に答えるために使う。
    responses は上から順に調べ、最初に当てはまったものを使う。

    使用例:
        {"type": "action", "actor": "robot1",
         "speak": {"type": "generate", "option": {
             "generator": "KeywordResponseEventGenerator",
             "responses": [
                 {"keywords": ["トイレ", "お手洗い"], "text": "トイレはエレベーターの横です。"},
                 {"keywords": ["会議室"], "text": ["会議室は奥のドアです。", "奥のドアが会議室です。"]}],
             "fallback_generator": "LlmJPEventGenerator",
             "prompt": "相手の発言に、短く一文で答えて。"}}}

    responses の各要素:
        keywords: キーワードのリスト（どれか1つが含まれれば当てはまる。"match": "all" なら全部）
        text: 答え（リストならランダムに1つ）。{変数} を使える
    当てはまらないとき:
        fallback_generator（既定 LlmJPEventGenerator）に、同じイベントのまま任せる。
        fallback_text があれば、それを話す（fallback_generator より優先）
    """

    def __init__(self, config: Dict[str, Any]):
        self._logger = getLogger(__name__)
        self.config = config
        self._fallbacks: Dict[str, AbstractEventGenerator] = {}

    def _match(self, heard: str, responses: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for response in responses:
            keywords = [k for k in response.get("keywords", []) if isinstance(k, str) and k]
            if not keywords:
                continue
            hits = [k in heard for k in keywords]
            if (all(hits) if response.get("match") == "all" else any(hits)):
                return response
        return None

    def generate(self, actor: str, event: Dict[str, Any], history: List[Dict[str, str]],
                 observations: Dict[str, Any]) -> List[Dict[str, Any]]:
        option = speak_option(event)
        heard = heard_text(observations)
        if not heard and history and history[-1].get("spk") == "[SPK1]":
            heard = history[-1].get("utt", "")
        response = self._match(heard, option.get("responses", [])) if heard else None
        if response is not None:
            text = response.get("text", "")
            if isinstance(text, list):
                text = random.choice(text) if text else ""
            text = fill_placeholders(text, observations)
            self._logger.info(f"[KeywordResponseEventGenerator] heard='{heard}', matched {response.get('keywords')}")
            return [make_speak_event(actor, event, text)]

        if option.get("fallback_text"):
            return [make_speak_event(actor, event, fill_placeholders(option["fallback_text"], observations))]
        name = option.get("fallback_generator", "LlmJPEventGenerator")
        self._logger.info(f"[KeywordResponseEventGenerator] heard='{heard}', no keyword matched; using {name}")
        return self._fallback(name).generate(actor, event, history, observations)

    def _fallback(self, name: str) -> AbstractEventGenerator:
        if name not in self._fallbacks:
            from . import get_generator
            self._fallbacks[name] = get_generator(name, self.config)
        return self._fallbacks[name]
