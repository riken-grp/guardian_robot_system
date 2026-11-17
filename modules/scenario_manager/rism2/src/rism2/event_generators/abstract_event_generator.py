"""Event Generator 抽象基底クラス"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List


class AbstractEventGenerator(ABC):
    """Event Generator の抽象基底クラス"""

    @abstractmethod
    def generate(
        self,
        actor: str,
        event: Dict[str, Any],
        history: List[Dict[str, str]],
        observations: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        イベントを生成

        Args:
            actor: アクター名
            event: 現在のイベント（type: generateのイベント）
            history: 会話履歴 [{"spk": "[SPK1]", "utt": "text"}, ...]
            observations: 観測データ（wait_for_result等）

        Returns:
            生成されたイベントのリスト
        """
        pass
