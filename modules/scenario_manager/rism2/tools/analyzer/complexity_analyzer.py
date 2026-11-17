"""
Complexity Analyzer for RISM2 Scenarios

シナリオの複雑度を分析するモジュール
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime


@dataclass
class ComplexityReport:
    """複雑度分析レポート"""
    scenario_id: str
    scenario_name: str
    metrics: Dict[str, int]
    complexity_score: float
    complexity_level: str
    recommendations: List[str]
    analyzed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return asdict(self)


class ComplexityAnalyzer:
    """シナリオ複雑度分析クラス"""

    # 複雑度スコアの重み
    WEIGHTS = {
        "event_count": 1.0,
        "max_nesting_level": 5.0,
        "branch_count": 3.0,
        "loop_count": 4.0,
        "llm_generation_count": 2.0,
    }

    # 複雑度レベルの閾値
    COMPLEXITY_THRESHOLDS = {
        "Simple": (0, 20),
        "Moderate": (21, 50),
        "Complex": (51, 100),
        "Very Complex": (101, float('inf')),
    }

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        初期化

        Args:
            logger: ロガー（オプション）
        """
        self.logger = logger or logging.getLogger(__name__)

    def analyze_scenario(self, scenario: Dict[str, Any]) -> ComplexityReport:
        """
        シナリオの複雑度を分析

        Args:
            scenario: シナリオデータ

        Returns:
            ComplexityReport: 複雑度分析レポート
        """
        scenario_id = scenario.get("_id", "unknown")
        scenario_name = scenario.get("name", "unnamed")

        self.logger.info(f"Analyzing complexity for scenario: {scenario_name} ({scenario_id})")

        # メトリクスを計算
        metrics = self._calculate_metrics(scenario)

        # 複雑度スコアを計算
        complexity_score = self._calculate_complexity_score(metrics)

        # 複雑度レベルを分類
        complexity_level = self._classify_complexity_level(complexity_score)

        # 推奨事項を生成
        recommendations = self._generate_recommendations(metrics, complexity_score)

        # レポートを作成
        report = ComplexityReport(
            scenario_id=str(scenario_id),
            scenario_name=scenario_name,
            metrics=metrics,
            complexity_score=complexity_score,
            complexity_level=complexity_level,
            recommendations=recommendations,
            analyzed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        self.logger.info(
            f"Complexity analysis complete: {complexity_level} "
            f"(score: {complexity_score:.1f})"
        )

        return report

    def _calculate_metrics(self, scenario: Dict[str, Any]) -> Dict[str, int]:
        """
        シナリオからメトリクスを計算

        Args:
            scenario: シナリオデータ

        Returns:
            Dict[str, int]: メトリクス辞書
        """
        events = scenario.get("events", [])

        metrics = {
            "event_count": 0,
            "max_nesting_level": 0,
            "branch_count": 0,
            "loop_count": 0,
            "llm_generation_count": 0,
            "action_count": 0,
            "observation_wait_count": 0,
        }

        # イベントを再帰的に走査
        self._traverse_events(events, metrics, nesting_level=0)

        return metrics

    def _traverse_events(
        self,
        events: List[Dict[str, Any]],
        metrics: Dict[str, int],
        nesting_level: int
    ) -> None:
        """
        イベントを再帰的に走査してメトリクスを収集

        Args:
            events: イベントリスト
            metrics: メトリクス辞書（更新される）
            nesting_level: 現在のネストレベル
        """
        for event in events:
            event_type = event.get("type", "")

            # イベント数をカウント
            metrics["event_count"] += 1

            # 最大ネストレベルを更新
            if nesting_level > metrics["max_nesting_level"]:
                metrics["max_nesting_level"] = nesting_level

            # イベントタイプ別の処理
            if event_type == "action":
                metrics["action_count"] += 1

                # LLM生成をチェック
                if self._has_llm_generation(event):
                    metrics["llm_generation_count"] += 1

            elif event_type == "wait_for":
                metrics["observation_wait_count"] += 1

            elif event_type == "if":
                metrics["branch_count"] += 1

                # 分岐内のイベントを走査
                for branch in ["true", "false", "failure"]:
                    if branch in event:
                        self._traverse_events(
                            event[branch],
                            metrics,
                            nesting_level + 1
                        )

            elif event_type == "until":
                metrics["loop_count"] += 1
                metrics["branch_count"] += 1  # loop + failure分岐

                # ループ内のイベントを走査
                if "loop" in event:
                    self._traverse_events(
                        event["loop"],
                        metrics,
                        nesting_level + 1
                    )

                # failure分岐を走査
                if "failure" in event:
                    self._traverse_events(
                        event["failure"],
                        metrics,
                        nesting_level + 1
                    )

            elif event_type == "repeat":
                metrics["loop_count"] += 1

                # repeat内のイベントを走査
                if "events" in event:
                    self._traverse_events(
                        event["events"],
                        metrics,
                        nesting_level + 1
                    )

            elif event_type == "random":
                metrics["branch_count"] += 1

                # random内のイベントを走査
                if "events" in event:
                    self._traverse_events(
                        event["events"],
                        metrics,
                        nesting_level + 1
                    )

    def _has_llm_generation(self, event: Dict[str, Any]) -> bool:
        """
        アクションイベントがLLM生成を含むかチェック

        Args:
            event: アクションイベント

        Returns:
            bool: LLM生成を含む場合True
        """
        # speakコマンドをチェック
        speak = event.get("speak", {})
        if isinstance(speak, dict) and speak.get("type") == "generate":
            return True

        # gestureコマンドをチェック
        gesture = event.get("gesture", {})
        if isinstance(gesture, dict) and gesture.get("type") == "generate":
            return True

        # eyeコマンドをチェック
        eye = event.get("eye", {})
        if isinstance(eye, dict) and eye.get("type") == "generate":
            return True

        return False

    def _calculate_complexity_score(self, metrics: Dict[str, int]) -> float:
        """
        メトリクスから複雑度スコアを計算

        Args:
            metrics: メトリクス辞書

        Returns:
            float: 複雑度スコア
        """
        score = 0.0

        for metric_name, weight in self.WEIGHTS.items():
            score += metrics.get(metric_name, 0) * weight

        return score

    def _classify_complexity_level(self, score: float) -> str:
        """
        複雑度スコアからレベルを分類

        Args:
            score: 複雑度スコア

        Returns:
            str: 複雑度レベル（Simple, Moderate, Complex, Very Complex）
        """
        for level, (min_score, max_score) in self.COMPLEXITY_THRESHOLDS.items():
            if min_score <= score <= max_score:
                return level

        return "Unknown"

    def _generate_recommendations(
        self,
        metrics: Dict[str, int],
        score: float
    ) -> List[str]:
        """
        メトリクスと複雑度スコアから推奨事項を生成

        Args:
            metrics: メトリクス辞書
            score: 複雑度スコア

        Returns:
            List[str]: 推奨事項のリスト
        """
        recommendations = []

        # イベント数が多い場合
        if metrics["event_count"] > 30:
            recommendations.append(
                "Consider splitting the scenario into smaller subscenarios "
                f"(current: {metrics['event_count']} events)"
            )

        # ネストレベルが深い場合
        if metrics["max_nesting_level"] > 2:
            recommendations.append(
                f"Reduce nesting level from {metrics['max_nesting_level']} to 2 "
                "for better maintainability"
            )

        # 分岐が多い場合
        if metrics["branch_count"] > 5:
            recommendations.append(
                f"High number of branches ({metrics['branch_count']}) detected. "
                "Consider simplifying the logic or using subscenarios"
            )

        # ループが多い場合
        if metrics["loop_count"] > 3:
            recommendations.append(
                f"High number of loops ({metrics['loop_count']}) detected. "
                "Consider extracting repeated patterns into subscenarios"
            )

        # LLM生成が多い場合
        if metrics["llm_generation_count"] > 5:
            recommendations.append(
                f"High number of LLM generations ({metrics['llm_generation_count']}) detected. "
                "Consider caching or pre-generating common responses"
            )

        # 複雑度スコアが高い場合
        if score > 100:
            recommendations.append(
                f"Very high complexity score ({score:.1f}). "
                "Strongly recommend refactoring into multiple smaller scenarios"
            )

        # 推奨事項がない場合
        if not recommendations:
            recommendations.append(
                "Scenario complexity is within acceptable limits. No specific recommendations."
            )

        return recommendations


def analyze_scenario_file(scenario_file: str) -> ComplexityReport:
    """
    YAMLファイルからシナリオを読み込んで複雑度を分析

    Args:
        scenario_file: シナリオファイルパス（YAML）

    Returns:
        ComplexityReport: 複雑度分析レポート
    """
    import yaml

    with open(scenario_file, 'r', encoding='utf-8') as f:
        scenario = yaml.safe_load(f)

    analyzer = ComplexityAnalyzer()
    return analyzer.analyze_scenario(scenario)


if __name__ == "__main__":
    # デバッグ用：簡単なテスト
    test_scenario = {
        "_id": "test_001",
        "name": "test_scenario",
        "type": "main_scenario",
        "events": [
            {
                "type": "action",
                "actor": "robot1",
                "speak": {
                    "type": "normal",
                    "option": {"text": "Hello"}
                }
            },
            {
                "type": "if",
                "condition": {},
                "true": [
                    {
                        "type": "action",
                        "actor": "robot1",
                        "speak": {
                            "type": "generate",
                            "option": {"prompt": "Generate"}
                        }
                    }
                ],
                "false": [
                    {
                        "type": "action",
                        "actor": "robot1",
                        "speak": {
                            "type": "normal",
                            "option": {"text": "Goodbye"}
                        }
                    }
                ]
            }
        ]
    }

    analyzer = ComplexityAnalyzer()
    report = analyzer.analyze_scenario(test_scenario)

    print("=" * 60)
    print("Complexity Analysis Report")
    print("=" * 60)
    print(f"Scenario: {report.scenario_name} ({report.scenario_id})")
    print(f"Complexity Level: {report.complexity_level}")
    print(f"Complexity Score: {report.complexity_score:.1f}")
    print(f"\nMetrics:")
    for metric, value in report.metrics.items():
        print(f"  {metric}: {value}")
    print(f"\nRecommendations:")
    for i, rec in enumerate(report.recommendations, 1):
        print(f"  {i}. {rec}")
    print("=" * 60)
