"""template_event_generator.py - 定型文から1つ選んで話す Event Generator（LLM不要）"""
import random
from logging import getLogger
from typing import Any, Dict, List

from .abstract_event_generator import AbstractEventGenerator
from .generator_utils import fill_placeholders, has_unfilled_placeholders, make_speak_event, speak_option


class TemplateEventGenerator(AbstractEventGenerator):
    """
    定型文のリストから1つ選び、{変数} を埋めて話す。

    LLM を使わないので、すぐ答えられ、LLM が使えないときの代わりにもなる。
    {変数} が埋められない文は、埋められる文があればそちらを選ぶ。
    同じ actor では、直前と同じ文は（他に候補があれば）選ばない。

    使用例:
        {"type": "action", "actor": "robot1",
         "speak": {"type": "generate", "option": {
             "generator": "TemplateEventGenerator",
             "templates": ["{greeting}！ゆっくりしていってくださいね。",
                           "{greeting}。何かあれば声をかけてくださいね。"]}}}

    使える {変数}: {greeting} {now} {heard} {triggered[名前]} {wait_for.contents.text} など
    """

    def __init__(self, config: Dict[str, Any]):
        self._logger = getLogger(__name__)
        self.config = config
        self._last_text: Dict[str, str] = {}

    def generate(self, actor: str, event: Dict[str, Any], history: List[Dict[str, str]],
                 observations: Dict[str, Any]) -> List[Dict[str, Any]]:
        option = speak_option(event)
        templates = [t for t in option.get("templates", []) if isinstance(t, str) and t]
        if not templates:
            self._logger.warning("[TemplateEventGenerator] no templates; using fallback_text")
            return [make_speak_event(actor, event, option.get("fallback_text", ""))]

        filled = [fill_placeholders(t, observations) for t in templates]
        complete = [t for t in filled if not has_unfilled_placeholders(t)]
        candidates = complete or filled
        fresh = [t for t in candidates if t != self._last_text.get(actor)]
        text = random.choice(fresh or candidates)
        self._last_text[actor] = text
        self._logger.info(f"[TemplateEventGenerator] actor={actor}, text='{text}'")
        return [make_speak_event(actor, event, text)]
