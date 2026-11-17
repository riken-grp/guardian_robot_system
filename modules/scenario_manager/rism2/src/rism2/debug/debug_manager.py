"""
Debug Manager for RISM2

シナリオデバッグ機能を管理するクラス
"""

import logging
import time
from typing import Dict, Any


class DebugManager:
    """
    デバッグ機能を管理するクラス

    主な機能:
    - イベント実行前後の状態ダンプ
    - プレースホルダー置換の可視化
    - LLMプロンプト・レスポンスのログ出力
    - パフォーマンス測定
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初期化

        Args:
            config: デバッグ設定
            logger: ロガー
        """
        self.config = config.get("debug_mode", {})
        self.enabled = self.config.get("enabled", False)
        self.logger = logger

        # デバッグ設定
        self.show_llm_prompts = self.config.get("show_llm_prompts", False)
        self.show_llm_responses = self.config.get("show_llm_responses", False)
        self.show_state_dump = self.config.get("show_state_dump", True)

        # パフォーマンス測定用
        self.event_timings = []
        self.current_event_start_time = None

    def is_enabled(self) -> bool:
        """デバッグモードが有効かどうか"""
        return self.enabled

    def dump_state_before_event(self, event_index: int, event: Dict[str, Any], current_state: Dict[str, Any],
                                finished_events: list, dialogue_history: list):
        """
        イベント実行前の状態をダンプ

        Args:
            event_index: イベントインデックス
            event: イベントデータ
            current_state: 現在の状態
            finished_events: 完了イベントリスト
            dialogue_history: 会話履歴
        """
        if not self.enabled or not self.show_state_dump:
            return

        self.logger.info("=" * 60)
        self.logger.info(f"[DEBUG] Event #{event_index} (type: {event.get('type', 'unknown')}, actor: {event.get('actor', 'N/A')})")
        self.logger.info("=" * 60)

        self.logger.info("[BEFORE STATE]")
        self._dump_current_state(current_state)
        self.logger.info(f"  finished_events: {len(finished_events)} event(s)")
        self.logger.info(f"  dialogue_history: {len(dialogue_history)} utterance(s)")

        self.logger.info("")
        self.logger.info("[EVENT DETAILS]")
        self._dump_event_details(event)

        # パフォーマンス測定開始
        self.current_event_start_time = time.time()

    def dump_state_after_event(self, event_index: int, event: Dict[str, Any], current_state: Dict[str, Any],
                               finished_events: list, dialogue_history: list):
        """
        イベント実行後の状態をダンプ

        Args:
            event_index: イベントインデックス
            event: イベントデータ
            current_state: 現在の状態
            finished_events: 完了イベントリスト
            dialogue_history: 会話履歴
        """
        if not self.enabled or not self.show_state_dump:
            return

        self.logger.info("")
        self.logger.info("[AFTER STATE]")
        self._dump_current_state(current_state)
        self.logger.info(f"  finished_events: {len(finished_events)} event(s)")

        # 会話履歴の変更を表示
        if dialogue_history:
            self.logger.info(f"  dialogue_history: {len(dialogue_history)} utterance(s)")
            if len(dialogue_history) > 0:
                latest = dialogue_history[-1]
                self.logger.info(f"    Latest: {latest.get('speaker', 'unknown')}: \"{latest.get('text', '')[:50]}...\"")

        # 実行時間を記録
        if self.current_event_start_time:
            execution_time = time.time() - self.current_event_start_time
            self.event_timings.append((event_index, event.get('type', 'unknown'), execution_time))
            self.logger.info("")
            self.logger.info(f"[EXECUTION TIME] {execution_time:.2f}s")
            self.current_event_start_time = None

        self.logger.info("=" * 60)
        self.logger.info("")

    def _dump_current_state(self, current_state: Dict[str, Any]):
        """現在の状態を表示"""
        if not current_state:
            self.logger.info("  (empty)")
            return

        # 重要なフィールドのみ表示
        important_fields = [
            "interpreter_status",
            "current_scenario_id",
            "current_scenario_name",
            "current_event_index",
            "current_event_type",
            "current_actor",
            "is_interrupted",
            "interrupt_depth",
            "processing"
        ]

        for field in important_fields:
            if field in current_state:
                value = current_state[field]
                if isinstance(value, dict):
                    self.logger.info(f"  {field}:")
                    for k, v in value.items():
                        self.logger.info(f"    {k}: {v}")
                else:
                    self.logger.info(f"  {field}: {value}")

    def _dump_event_details(self, event: Dict[str, Any]):
        """イベント詳細を表示"""
        event_type = event.get('type', 'unknown')

        if event_type == 'action':
            # アクションの詳細を表示
            action_types = ['speak', 'gesture', 'navigation', 'eye', 'ros_command']
            for action_type in action_types:
                if action_type in event:
                    action_data = event[action_type]
                    self.logger.info(f"  {action_type}:")
                    self.logger.info(f"    type: {action_data.get('type', 'unknown')}")
                    if 'option' in action_data:
                        option = action_data['option']
                        # テキストは短縮表示
                        if 'text' in option:
                            text = option['text']
                            display_text = text[:100] + "..." if len(text) > 100 else text
                            self.logger.info(f"    text: \"{display_text}\"")
                        # その他のオプション
                        for key, value in option.items():
                            if key not in ['text']:
                                self.logger.info(f"    {key}: {value}")
        else:
            # その他のイベントタイプは簡潔に表示
            for key, value in event.items():
                if key not in ['type', '_id']:
                    if isinstance(value, (dict, list)):
                        self.logger.info(f"  {key}: {type(value).__name__}(...)")
                    else:
                        self.logger.info(f"  {key}: {value}")

    def reset(self):
        """デバッグデータをリセット"""
        self.event_timings = []
        self.current_event_start_time = None
