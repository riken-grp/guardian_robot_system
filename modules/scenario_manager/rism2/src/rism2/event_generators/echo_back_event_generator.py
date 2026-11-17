"""echo_back_event_generator.py - ユーザー発話をエコーバックするEvent Generator"""
from logging import getLogger
from typing import Dict, Any, List

from .abstract_event_generator import AbstractEventGenerator
from .generator_utils import heard_text


class EchoBackEventGenerator(AbstractEventGenerator):
    """
    ユーザーの発話（観測データ）をそのままロボットの発話として返すEvent Generator。

    LLM不要。デバッグ・テスト・エコーバック演出に使用。
    観測データが存在しない場合は default_text（デフォルト: "ん"）を返す。

    使用例（シナリオ定義）:
        {
            "type": "generate",
            "actor": "robot1",
            "speak": {
                "type": "generate",
                "option": {
                    "generator": "EchoBackEventGenerator",
                    "default_text": "もう一度おっしゃってください"
                }
            }
        }
    """

    def __init__(self, config: Dict[str, Any]):
        self._logger = getLogger(__name__)
        self.config = config

    def generate(
        self,
        actor: str,
        event: Dict[str, Any],
        history: List[Dict[str, str]],
        observations: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        観測データからユーザー発話を取得してそのまま返す

        Args:
            actor: アクター名
            event: 現在のイベント
            history: 会話履歴（未使用）
            observations: 観測データ（wait_for / triggered）

        Returns:
            単一のactionイベントを含むリスト
        """
        option = event.get("speak", {}).get("option", {})
        default_text = option.get("default_text", "ん")

        observation_text = self._extract_observation_text(observations)
        text = observation_text if observation_text else default_text

        self._logger.info(f"[EchoBackEventGenerator] actor={actor}, text='{text}'")

        return [{
            "type": "action",
            "actor": actor,
            "speak": {
                "type": "normal",
                "option": {"text": text}
            },
            "interruptable": option.get("interruptable", True)
        }]

    def _extract_observation_text(self, observations: Dict[str, Any]) -> str:
        """観測データから聞いた発話を取り出す（wait_for → triggered の順。contents / content の両方を見る）"""
        return heard_text(observations)
