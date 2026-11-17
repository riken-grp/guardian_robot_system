"""scenario_selector.py - 次に実行するシナリオと、割り込むサブシナリオを選ぶ"""
import logging
import time
from logging import getLogger
from typing import Any, Dict, List, Optional, Tuple

from .condition_checker import is_match_condition
from .interrupt_queue import InterruptPriority
from .scenario_model import Scenario
from .time_based_condition import TimeBasedCondition


class ScenarioSelector:
    """
    観測と条件を照合し、priority を重みにして選ぶ

    - メインシナリオ: next_scenarios または全アクティブシナリオから（予約キューがあればそれを優先）
    - サブシナリオ: 条件に合うものを優先度順に並べ、同時に合ったものから1つを選ぶ
    """

    def __init__(self, scenarios, observations):
        """
        Args:
            scenarios: ScenarioRepository
            observations: ObservationStore
        """
        self._logger = getLogger(__name__)
        self.scenarios = scenarios
        self.observations = observations
        # シナリオキュー: ユーザ指示で明示的に積まれたシナリオIDのFIFOキュー
        self.scenario_queue: List[str] = []
        self._last_no_match_log_time = 0.0

    def _select_from_candidates(
        self,
        candidates: List[Scenario],
        source_name: str = "scenarios"
    ) -> Optional[str]:
        """
        候補シナリオリストから条件マッチング + 重み付きランダムで1件を選択する共通ヘルパー

        Args:
            candidates: 既にロード済みのシナリオのリスト
            source_name: ログメッセージ用のソース名（例: "next scenarios", "matching scenarios"）

        Returns:
            選択されたシナリオID文字列、候補がない場合はNone
        """
        eligible = self._eligible(candidates, self.observations.get_recent_observations())
        if not eligible:
            self._logger.warning(f"No matching scenarios found in {source_name}")
            return None

        # priority を重みにして1つ選ぶ
        weights = [scenario.priority for scenario, _ in eligible]
        self._logger.debug(f"Candidates: {len(eligible)}, Weights: {weights}")
        for i, (scenario, weight) in enumerate(zip([s for s, _ in eligible], weights)):
            self._logger.debug(f"  [{i}] {scenario.name} (priority={weight})")
        selected_index = InterruptPriority.pick(weights)
        selected, selected_matched_obs = eligible[selected_index]

        # 条件に合った観測を使用済みにする
        self.observations.update_mentioned_observations(selected_matched_obs)

        self._logger.info(
            f"Selected scenario from {source_name}: {selected.id} "
            f"(name: {selected.name}, priority: {selected.priority}, "
            f"index: {selected_index}/{len(eligible)})"
        )
        return selected.id_str

    def _eligible(self, candidates: List[Scenario], observations) -> List[Tuple[Scenario, List[Any]]]:
        """
        選べる候補と、その条件に合った観測

        condition があって観測が合うシナリオを優先する。1つもなければ、condition のないシナリオ。
        """
        matched, unconditional = [], []
        for scenario in candidates:
            if not scenario.condition:
                unconditional.append((scenario, []))
                continue
            is_match, matched_obs = is_match_condition(scenario.condition, observations)
            if is_match:
                matched.append((scenario, matched_obs))
        if matched:
            self._logger.debug(f"Using {len(matched)} scenarios with matching conditions")
            return matched
        if unconditional:
            self._logger.debug(f"No matching conditions, using {len(unconditional)} scenarios without conditions")
        return unconditional

    def add_to_scenario_queue(self, scenario_id: str) -> None:
        """
        シナリオキューにシナリオIDを追加（FIFO）

        Args:
            scenario_id: キューに追加するシナリオのID文字列
        """
        self.scenario_queue.append(scenario_id)
        self._logger.info(
            f"[ScenarioSelector] Queued scenario: {scenario_id} "
            f"(queue length: {len(self.scenario_queue)})"
        )

    def _pop_from_scenario_queue(self) -> Optional[str]:
        """キューの先頭からシナリオIDを取り出す（空ならNone）"""
        if self.scenario_queue:
            scenario_id = self.scenario_queue.pop(0)
            self._logger.info(
                f"[ScenarioSelector] Dequeued scenario: {scenario_id} "
                f"(remaining: {len(self.scenario_queue)})"
            )
            return scenario_id
        return None

    def select_next_scenario(self, next_scenario_ids: List[str]) -> Optional[str]:
        """
        next_scenariosリストから条件マッチング + 重み付きランダムで次シナリオを選択
        conditionにマッチするシナリオがあれば、それらを優先して選択
        シナリオキューが空でない場合はキューから優先選択

        Args:
            next_scenario_ids: 候補シナリオIDのリスト

        Returns:
            選択されたシナリオID、候補がない場合はNone
        """
        # シナリオキューが非空ならキューを優先
        queued = self._pop_from_scenario_queue()
        if queued is not None:
            return queued

        # IDリストから各シナリオをロード（[[id1, id2]] のような入れ子リストも平坦化して扱う）
        candidates = []
        # next_scenariosで明示的に指定されたシナリオはinactiveでも候補にする
        for scenario_id in self._flatten_scenario_ids(next_scenario_ids):
            scenario = self.scenarios.load_scenario(scenario_id, include_inactive=True)
            if scenario:
                candidates.append(scenario)

        return self._select_from_candidates(candidates, "next scenarios")

    @staticmethod
    def _flatten_scenario_ids(scenario_ids: List[Any]) -> List[str]:
        """
        入れ子になったシナリオIDリストを平坦化する

        Args:
            scenario_ids: シナリオIDのリスト（入れ子リストを含んでもよい）

        Returns:
            平坦化したシナリオIDのリスト
        """
        flattened = []
        for item in scenario_ids:
            if isinstance(item, (list, tuple)):
                flattened.extend(ScenarioSelector._flatten_scenario_ids(item))
            else:
                flattened.append(item)
        return flattened

    def find_matching_scenario(self) -> Optional[str]:
        """
        全アクティブシナリオから条件に合致するものを探す
        conditionにマッチするシナリオがあれば、それらを優先して選択
        シナリオキューが空でない場合はキューから優先選択

        Returns:
            マッチしたシナリオのID、なければNone
        """
        # シナリオキューが非空ならキューを優先
        queued = self._pop_from_scenario_queue()
        if queued is not None:
            return queued

        # 全アクティブシナリオを取得
        scenarios = self.scenarios.get_active_scenarios()
        self._logger.debug(f"find_matching_scenario: Got {len(scenarios)} active scenarios")

        return self._select_from_candidates(scenarios, "matching scenarios")

    def find_matching_subscenarios(
        self,
        time_context: Optional[Dict[str, Any]] = None
    ) -> List[tuple[Scenario, List[Dict[str, Any]]]]:
        """
        条件に合致するサブシナリオを検索

        Args:
            time_context: 時間ベース条件用のコンテキスト（オプション）
                {
                    "scenario_start_time": datetime,
                    "last_utterance_time": datetime,
                    "last_observation_time": datetime
                }

        Returns:
            (サブシナリオ, マッチした観測データ) のタプルのリスト（優先度順）
        """
        observations = self.observations.get_recent_observations()
        self._log_observations(observations)
        subscenarios = self.scenarios.get_active_subscenarios()
        self._logger.debug(f"[INTERRUPT_MATCH] Checking {len(subscenarios)} active subscenarios")

        matched = []
        for subscenario in subscenarios:
            matched_obs = self._match(subscenario, observations, time_context)
            if matched_obs is not None:
                matched.append((subscenario, matched_obs))
        matched.sort(key=lambda x: -x[0].priority)

        self._log_no_match(subscenarios, matched, observations)
        self._logger.debug(f"Found {len(matched)} matching subscenarios")
        return matched

    def _match(self, subscenario: Scenario, observations: Dict[str, List[Dict[str, Any]]],
               time_context: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """サブシナリオの条件（と time_based）が成り立てば、合った観測。成り立たなければ None"""
        condition = subscenario.condition
        name = subscenario.name or "unknown"
        if not condition:
            # サブシナリオは条件が必須
            self._logger.debug(f"[INTERRUPT_MATCH] Skipping '{name}': no condition")
            return None

        # time_based は観測のイベント名ではないので、観測との照らし合わせから外して下で判定する
        event_condition = {k: v for k, v in condition.items() if k != "time_based"}
        is_match, matched_obs = is_match_condition(event_condition, observations)
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(f"[INTERRUPT_MATCH] Subscenario '{name}': condition={condition}, is_match={is_match}")
        if not is_match:
            return None

        if "time_based" in condition:
            if time_context is None:
                self._logger.warning(f"time_based condition found but no time_context provided for subscenario: {name}")
                return None
            try:
                if not TimeBasedCondition(condition["time_based"], logger=self._logger).check(time_context):
                    return None
            except Exception as e:
                self._logger.error(f"Error checking time_based condition for subscenario {name}: {e}")
                return None
        return matched_obs

    def _log_observations(self, observations: Dict[str, List[Dict[str, Any]]]) -> None:
        """読んだ観測をログに出す（DEBUG のときだけ）"""
        if not self._logger.isEnabledFor(logging.DEBUG):
            return
        obs_count = sum(len(obs_list) for obs_list in observations.values())
        db_info = f"{self.observations.watcher.db_host}:{self.observations.watcher.db_port}"
        self._logger.debug(f"[INTERRUPT_MATCH] Retrieved {obs_count} observations from {db_info} (mentioned=false)")
        for db_name, obs_list in observations.items():
            if obs_list:
                self._logger.debug(f"[INTERRUPT_MATCH] {db_name}: {[obs.get('event', 'unknown') for obs in obs_list]}")

    def _log_no_match(self, subscenarios: List[Scenario], matched: list,
                      observations: Dict[str, List[Dict[str, Any]]]) -> None:
        """どれも合わなかったときの原因を、5秒に1回ログに出す（サブシナリオが1つもなければ INFO）"""
        now = time.time()
        if now - self._last_no_match_log_time <= 5.0:
            return
        self._last_no_match_log_time = now
        if not subscenarios:
            obs_count = sum(len(obs_list) for obs_list in observations.values())
            self._logger.info(
                f"[INTERRUPT_MATCH] No active subscenarios (get_active_subscenarios returned 0), obs_cache={obs_count}"
            )
        elif not matched and self._logger.isEnabledFor(logging.DEBUG):
            # 割り込みがなければずっと5秒ごとに出るので DEBUG（INFO だとログの1割以上がこの行になる）
            cond_keys = [list(s.condition.keys()) for s in subscenarios if s.condition]
            cache_events = sorted({obs.get("event") for obs_list in observations.values()
                                   for obs in obs_list if obs.get("event")})
            self._logger.debug(
                f"[INTERRUPT_MATCH] No match: {len(subscenarios)} subscenario(s) checked, "
                f"conditions={cond_keys}, cache_events={cache_events}"
            )

    def select_subscenario_probabilistically(
        self,
        matched_subscenarios: List[tuple],
        effective_priorities: Optional[List[int]] = None,
    ) -> Optional[tuple]:
        """
        複数のマッチしたサブシナリオから確率的に1つを選択

        優先度（0〜1000）が高いほど選ばれやすい（優先度をそのまま重みにする）。0 はほかに候補がないときだけ選ぶ。

        Args:
            matched_subscenarios: (subscenario, matched_obs) のタプルリスト
            effective_priorities: F6で計算されたeffective priority（int）のリスト。
                                  指定時はこちらの値で重み付けを行う（後方互換: None で従来動作）

        Returns:
            選択された (subscenario, matched_obs) タプル、空リストの場合 None
        """
        if not matched_subscenarios:
            return None
        if len(matched_subscenarios) == 1:
            return matched_subscenarios[0]

        if effective_priorities is not None:
            weights = [self._get_priority_weight(ep) for ep in effective_priorities]
        else:
            weights = [self._get_priority_weight(s.priority) for s, _ in matched_subscenarios]
        selected = matched_subscenarios[InterruptPriority.pick(weights)]

        names = [s.name or "?" for s, _ in matched_subscenarios]
        selected_name = selected[0].name or "?"
        self._logger.info(
            f"[PROBABILISTIC_SELECT] Selected '{selected_name}' from {names} "
            f"(weights: {weights})"
        )
        return selected

    def _get_priority_weight(self, priority) -> float:
        """優先度（0〜1000）を選択確率の重みにする。優先度の値をそのまま使う"""
        if isinstance(priority, bool) or not isinstance(priority, (int, float)):
            return float(InterruptPriority.DEFAULT)
        return float(max(InterruptPriority.MIN, min(InterruptPriority.MAX, int(priority))))
