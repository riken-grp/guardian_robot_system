"""event_generate_handler.py - generate（LLM などで発話を作る）イベントの処理"""
import time
from logging import getLogger
from typing import Any, List, Optional, TYPE_CHECKING

from . import event_generators
from .event_model import ActionEvent, EventLike

if TYPE_CHECKING:
    from .event_processor import EventProcessor


class GenerateHandler:
    """speak.type が generate のイベント（Event Generator で作ったイベントを実行する）"""

    def __init__(self, events: "EventProcessor") -> None:
        self.events = events
        self.interpreter = events.interpreter
        self._logger = getLogger(__name__)

    # fallback_text がないときに、生成に失敗したら話す文
    DEFAULT_FALLBACK_TEXT = "[発話生成に失敗しました]"

    def execute_generate_event(self, actor: str, event: EventLike) -> bool:
        """
        type: 'generate'のイベントを実行（Event Generatorを使用）

        先読みした結果があれば使い、なければ（retry 回まで）作る。作れなければ fallback_text を話す。
        """
        event = ActionEvent.coerce(event)
        # 次の発話の先読みは、作った発話を話し始めて会話履歴に入れてから始める（execute_action_event）
        option = event.speak_option
        generator_name = option.get("generator", event_generators.DEFAULT_GENERATOR)

        generator = self._load_generator(generator_name)
        if generator is None:
            if option.get("fallback_text"):
                return self.events.actions.execute_fallback_action(
                    actor, event, option["fallback_text"], "generator load failed")
            return False

        # 先読みした結果があれば使う（生成中なら少し待つ）
        cache_key = self._prefetch_key(event)
        generated_events = self.interpreter.prefetch_manager.take(cache_key)
        cache_hit = generated_events is not None
        if not cache_hit:
            generated_events = self._generate_with_retries(generator, generator_name, actor, event, option, cache_key)
            if generated_events is None:
                return self._fallback(actor, event, option, "all retries failed")
        if not generated_events:
            self._logger.error(
                f"Generator {generator_name} returned no events (empty or None). "
                f"Actor: {actor}, Cache hit: {cache_hit}, Cache key: {cache_key}"
            )
            return self._fallback(actor, event, option, "no events generated")

        self._logger.info(f"Generator {generator_name} generated {len(generated_events)} event(s)")
        if not self._run_generated(generated_events):
            return False

        # 作ったイベントを実行し終えたので、並びの次のイベントを先読みする
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()
        return True

    def _load_generator(self, name: str) -> Any:
        """Event Generator（読み込んでいなければ読み込む）。読み込めなければ None"""
        generators = self.interpreter.event_generators
        if name not in generators:
            try:
                generators[name] = event_generators.get_generator(name, self.interpreter.config)
                self._logger.info(f"Loaded event generator: {name}")
            except Exception as e:
                self._logger.error(f"Failed to load generator {name}: {e}")
                return None
        return generators[name]

    def _generate_with_retries(self, generator: Any, generator_name: str, actor: str, event: ActionEvent,
                               option: dict, cache_key: Any) -> Optional[List[dict]]:
        """
        Event Generator でイベントを作る（option の retry 回まで作り直す）

        Returns:
            作ったイベント。すべて失敗したら None
        """
        retry_config = self.events.actions.extract_retry_config(option)
        retry_count = retry_config.get("retry", 0)
        retry_delay = retry_config.get("retry_delay", 1.0)
        event_id = cache_key if isinstance(cache_key, str) else f"event {cache_key}"
        debug = self.interpreter.debug_manager

        for attempt in range(retry_count + 1):
            if attempt > 0:
                self._logger.info(f"Retrying LLM generation (attempt {attempt}/{retry_count})...")
                time.sleep(retry_delay)
            history = self.events.build_llm_history(actor)
            observations = self._observations_for(option)
            last_attempt = attempt == retry_count

            self.interpreter.update_current_state({"processing": {"is_llm_generating": True}})
            try:
                label = f"RETRY {attempt}" if attempt > 0 else "NORMAL"
                self._logger.info(f"[{label}] Calling {generator_name}.generate() for {event_id}, actor={actor}")
                if debug.is_enabled() and debug.show_llm_prompts:
                    self._logger.info("[DEBUG] Starting LLM generation")
                    self._logger.info(f"[DEBUG] Generator: {generator_name}, Context: "
                                      f"{dict(actor=actor, event_type=event.type, history_length=len(history), observations=observations)}")

                started = time.time()
                generated = generator.generate(actor=actor, event=event.to_dict(), history=history,
                                               observations=observations)
                if debug.is_enabled() and debug.show_llm_responses:
                    self._logger.info(f"[DEBUG] LLM generation completed in {time.time() - started:.2f}s")
                    self._logger.info(f"[DEBUG] Generated {len(generated) if generated else 0} event(s)")
                    for i, gen_event in enumerate(generated or [], 1):
                        self._logger.info(f"[DEBUG]   Event {i}: {gen_event.get('type', 'unknown')}")
            except Exception as e:
                if last_attempt:
                    self._logger.error(f"Generator {generator_name} failed after all retries "
                                       f"({retry_count + 1} attempts). Actor: {actor}, Error: {e}", exc_info=True)
                else:
                    self._logger.warning(f"Generator {generator_name} failed (attempt {attempt + 1}/{retry_count + 1}), "
                                         f"will retry in {retry_delay}s. Error: {e}")
                continue
            finally:
                self.interpreter.update_current_state({"processing": {"is_llm_generating": False}})

            if generated:
                if attempt > 0:
                    self._logger.info(f"LLM generation succeeded on retry {attempt}")
                return generated
            if last_attempt:
                self._logger.error(f"Generator {generator_name} returned no events after all retries "
                                   f"({retry_count + 1} attempts). Actor: {actor}, Event: {event.type}")
            else:
                self._logger.warning(f"Generator {generator_name} returned no events "
                                     f"(attempt {attempt + 1}/{retry_count + 1}), will retry in {retry_delay}s")

        self._logger.error(
            f"All LLM generation attempts failed after {retry_count + 1} attempt(s). "
            f"Event: {event.type}, Actor: {actor}, Generator: {generator_name}, Cache key: {cache_key}"
        )
        return None

    def _observations_for(self, option: dict) -> dict:
        """Event Generator に渡す観測（wait_for の結果、割り込みのきっかけ、use_observations なら最近の観測）"""
        ctx = self.interpreter.ctx
        observations = {"wait_for": ctx.wait_for_result} if ctx.wait_for_result else {}
        if ctx.triggered_observation:
            observations["triggered"] = ctx.triggered_observation
        if option.get("use_observations"):
            observations["recent"] = self.interpreter.scenario_manager.observations.get_recent_observations()
        return observations

    def _run_generated(self, generated_events: List[dict]) -> bool:
        """作ったイベントを順に実行する（実行中の位置は、次の生成イベントの先読みに使う）"""
        ctx = self.interpreter.ctx
        ctx.current_generated_events = generated_events
        try:
            for i, generated_event in enumerate(generated_events):
                ctx.current_generated_index = i
                if not self.events.execute_event(generated_event):
                    self._logger.error("Failed to execute generated event")
                    return False
            return True
        finally:
            ctx.current_generated_events = None
            ctx.current_generated_index = -1

    def _fallback(self, actor: str, event: ActionEvent, option: dict, reason: str) -> bool:
        """作れなかったときに fallback_text（なければ既定の文）を話す"""
        text = option.get("fallback_text")
        if not text:
            text = self.DEFAULT_FALLBACK_TEXT
            self._logger.warning(f"No fallback_text provided, using default: '{text}'")
        self._logger.warning("Using fallback text for failed generation")
        return self.events.actions.execute_fallback_action(actor, event, text, reason)

    def _prefetch_key(self, event: EventLike) -> Any:
        """このイベントの先読みのキャッシュキー（PrefetchManager.key_for）"""
        return self.interpreter.prefetch_manager.key_for(event)
