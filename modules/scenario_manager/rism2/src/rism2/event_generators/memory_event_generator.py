"""memory_event_generator.py - 前に話したことを覚えておき、次の会話で使う Event Generator"""
import datetime
from logging import getLogger
from typing import Any, Dict, List, Optional

from .abstract_event_generator import AbstractEventGenerator
from .generator_utils import generated_text, speak_option, with_speak_option

MEMORY_COLLECTION = "memories"

SUMMARY_PROMPT = "ここまでの会話で相手が話したことを、あとで思い出せるように一文で要約して。"


class MemoryEventGenerator(AbstractEventGenerator):
    """
    会話の要約を覚えておき、次に話すときにプロンプトへ入れる。発話の生成は LlmJPEventGenerator に任せる。

    覚えた内容はシナリオDBの memories コレクションに入る:
        {"person": "山田"（わからなければ null）, "text": "見学に来て、ロボットの研究を見たいと言っていた", "created": 日時}

    使用例（対話の最初: 前に話したことを思い出して話しかける）:
        {"generator": "MemoryEventGenerator", "recall": 3,
         "prompt": "前に話したことがあれば、それに触れながら挨拶して。"}
    使用例（対話の最後: 会話を要約して覚える）:
        {"generator": "MemoryEventGenerator", "recall": 0, "save": true,
         "prompt": "会話のお礼を短く言って。"}

    option:
        recall: 思い出す件数（既定 3、0 なら思い出さない）
        save: true なら、話した後に会話を要約して覚える
        person_field: 割り込みのきっかけの観測（顔認識など）の、人を表すフィールド名（例: "name"）。
            指定するとその人の記憶だけを使う。無ければ全員共通
        summary_hist_len: 要約に使う直近の会話の数（既定 10）
    """

    def __init__(self, config: Dict[str, Any]):
        self._logger = getLogger(__name__)
        self.config = config
        self._collection = None
        self._llm = None

    def _memory_collection(self):
        if self._collection is None:
            from ..database import get_scenario_db_info, shared_client
            info = get_scenario_db_info(self.config.get("demo", {}))
            self._collection = shared_client(info["host"], info["port"])[info["db_name"]][MEMORY_COLLECTION]
        return self._collection

    @staticmethod
    def _person(option: Dict[str, Any], observations: Dict[str, Any]) -> Optional[str]:
        field = option.get("person_field")
        triggered = (observations or {}).get("triggered") or {}
        if not field or not isinstance(triggered, dict):
            return None
        contents = triggered.get("contents") if isinstance(triggered.get("contents"), dict) else {}
        value = contents.get(field, triggered.get(field))
        return str(value) if value not in (None, "") else None

    def recall(self, person: Optional[str], count: int) -> List[Dict[str, Any]]:
        """新しい順に count 件の記憶"""
        if count <= 0:
            return []
        try:
            return list(self._memory_collection().find({"person": person}).sort("created", -1).limit(count))
        except Exception as e:
            self._logger.error(f"[MemoryEventGenerator] could not read memories: {e}")
            return []

    def generate(self, actor: str, event: Dict[str, Any], history: List[Dict[str, str]],
                 observations: Dict[str, Any]) -> List[Dict[str, Any]]:
        option = speak_option(event)
        person = self._person(option, observations)
        memories = self.recall(person, option.get("recall", 3))
        prompt = option.get("prompt", "")
        if not memories and option.get("recall", 3) > 0:
            # 「前回話したことがあれば」という指示で、無い会話を作らないように
            prompt = f"この相手と前に話した記録は無い（初めて話す）。\n{prompt}".strip()
        if memories:
            lines = "\n".join(f"- {m['created']:%m月%d日}: {m['text']}" for m in reversed(memories))
            prompt = f"前回この相手と話した内容:\n{lines}\n{prompt}".strip()
        self._logger.info(f"[MemoryEventGenerator] person={person}, recalled {len(memories)} memory(ies)")
        events = self._llm_generator().generate(actor, with_speak_option(event, prompt=prompt), history, observations)

        if option.get("save"):
            self.save(actor, event, history, observations, person, option.get("summary_hist_len", 10))
        return events

    def save(self, actor: str, event: Dict[str, Any], history: List[Dict[str, str]],
             observations: Dict[str, Any], person: Optional[str], hist_len: int) -> None:
        """会話を LLM で一文に要約して覚える（相手が何も話していなければ覚えない）"""
        if not any(h.get("spk") == "[SPK1]" and h.get("utt") for h in history[-hist_len:]):
            return
        summary_event = with_speak_option(event, prompt=SUMMARY_PROMPT, hitorigoto=True, hist_len=hist_len,
                                          llm_max_tokens=80)
        summary = generated_text(self._llm_generator().generate(actor, summary_event, history, observations))
        if not summary.strip():
            return
        try:
            self._memory_collection().insert_one(
                {"person": person, "text": summary.strip(), "created": datetime.datetime.now()})
            self._logger.info(f"[MemoryEventGenerator] saved memory for person={person}: {summary.strip()}")
        except Exception as e:
            self._logger.error(f"[MemoryEventGenerator] could not save memory: {e}")

    def _llm_generator(self) -> AbstractEventGenerator:
        if self._llm is None:
            from . import get_generator
            self._llm = get_generator("LlmJPEventGenerator", self.config)
        return self._llm
