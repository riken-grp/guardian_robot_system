"""multi_gen_and_select_event_generator.py - 複数Generatorの候補から1つ選択するEvent Generator"""
import random
from logging import getLogger
from typing import Dict, Any, List

from .abstract_event_generator import AbstractEventGenerator


class MultiGenAndSelectEventGenerator(AbstractEventGenerator):
    """
    複数の Event Generator を並列実行し、生成された候補から1つを選んで返す Event Generator。

    選択戦略（selection_strategy）:
        - "random"   : ランダムに選択（デフォルト）
        - "first"    : 最初に成功したGeneratorの結果を使用
        - "weighted" : generators 設定の "weight" キーに応じた確率で選択

    使用例（シナリオ定義）:
        {
            "type": "generate",
            "actor": "robot1",
            "speak": {
                "type": "generate",
                "option": {
                    "generator": "MultiGenAndSelectEventGenerator",
                    "selection_strategy": "weighted",
                    "generators": [
                        {"name": "LlmJPEventGenerator", "weight": 3},
                        {"name": "EchoBackEventGenerator", "weight": 1}
                    ]
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
        複数Generatorで候補を生成し、戦略に従って1つを選択して返す

        Args:
            actor: アクター名
            event: 現在のイベント（speak.option.generators にGenerator設定リストを含む）
            history: 会話履歴
            observations: 観測データ

        Returns:
            選択された1つのGeneratorの結果（イベントリスト）
        """
        # 遅延インポート（循環参照を避けるため）
        from . import get_generator

        option = event.get("speak", {}).get("option", {})
        gen_configs = option.get("generators", [])
        strategy = option.get("selection_strategy", "random")

        if not gen_configs:
            self._logger.warning("[MultiGenAndSelectEventGenerator] No generators configured, returning empty")
            return self._fallback(actor)

        # 各Generatorで候補を生成
        candidates: List[Dict[str, Any]] = []  # {"events": [...], "weight": N}

        for gen_cfg in gen_configs:
            gen_name = gen_cfg.get("name") if isinstance(gen_cfg, dict) else gen_cfg
            weight = gen_cfg.get("weight", 1) if isinstance(gen_cfg, dict) else 1

            if not gen_name:
                continue

            try:
                generator = get_generator(gen_name, self.config)
                result = generator.generate(actor, event, history, observations)
                if result:
                    candidates.append({"events": result, "weight": max(1, weight)})
                    self._logger.debug(f"[MultiGenAndSelectEventGenerator] {gen_name}: {len(result)} event(s)")
            except Exception as e:
                self._logger.warning(f"[MultiGenAndSelectEventGenerator] Generator '{gen_name}' failed: {e}")

        if not candidates:
            self._logger.warning("[MultiGenAndSelectEventGenerator] All generators failed")
            return self._fallback(actor)

        selected = self._select(candidates, strategy)
        self._logger.info(
            f"[MultiGenAndSelectEventGenerator] strategy={strategy}, "
            f"candidates={len(candidates)}, selected={len(selected)} event(s)"
        )
        return selected

    def _select(self, candidates: List[Dict[str, Any]], strategy: str) -> List[Dict[str, Any]]:
        """戦略に従って候補から1つ選択"""
        if strategy == "first":
            return candidates[0]["events"]

        if strategy == "weighted":
            weights = [c["weight"] for c in candidates]
            chosen = random.choices(candidates, weights=weights, k=1)[0]
            return chosen["events"]

        # デフォルト: random
        return random.choice(candidates)["events"]

    def _fallback(self, actor: str) -> List[Dict[str, Any]]:
        """全Generator失敗時のフォールバック"""
        return [{
            "type": "action",
            "actor": actor,
            "speak": {
                "type": "normal",
                "option": {"text": "[生成失敗]"}
            },
            "interruptable": True
        }]
