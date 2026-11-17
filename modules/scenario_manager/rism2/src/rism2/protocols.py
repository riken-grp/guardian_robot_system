"""protocols.py - 部品が ScenarioInterpreter に求めるもの

部品は ScenarioInterpreter を直接 import せず、使うものだけを並べたこれらの Protocol を通して使う
（循環 import を避け、どの部品が何に頼っているかをはっきりさせる）。
ScenarioInterpreter はすべてを暗黙に満たす。
"""
from typing import Any, Dict, Protocol

from .execution_context import ExecutionContext


class EventRuntime(Protocol):
    """EventProcessor と各 Handler が使うもの"""
    config: Dict[str, Any]
    executor_config: Dict[str, Any]
    max_history_length: int
    ctx: ExecutionContext
    internal_state: Dict[str, Any]

    scenario_manager: Any
    action_managers: Dict[str, Dict[str, Any]]
    event_generators: Dict[str, Any]
    condition_waiter: Any
    debug_manager: Any
    interrupt_queue: Any
    prefetch_manager: Any
    wait_state: Any  # WaitStateTracker（待ち状態を current_state に出す）

    def update_current_state(self, updates: Dict[str, Any]) -> None: ...

    def update_internal_state(self, key: str, value: Any) -> None: ...

    def process_pending_interrupts(self, important_only: bool = False) -> bool: ...

    def suspend_navigation(self) -> None: ...


class InterruptRuntime(Protocol):
    """InterruptManager / InterruptDetector / NavigationSuspender が使うもの"""
    config: Dict[str, Any]
    default_navigation_interrupt_mode: str
    ctx: ExecutionContext

    scenario_manager: Any
    action_managers: Dict[str, Dict[str, Any]]
    interrupt_queue: Any
    queue_monitor: Any
    event_processor: Any
    prefetch_manager: Any
    robot_name_for_history: Any  # scenario_history の robot

    def update_current_state(self, updates: Dict[str, Any]) -> None: ...


class PrefetchRuntime(Protocol):
    """PrefetchManager が使うもの"""
    config: Dict[str, Any]
    ctx: ExecutionContext
    event_generators: Dict[str, Any]
    event_processor: Any

    def update_current_state(self, updates: Dict[str, Any]) -> None: ...
