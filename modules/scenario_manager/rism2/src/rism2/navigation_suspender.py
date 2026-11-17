"""navigation_suspender.py - 割り込み時のナビゲーション処理

移動中に割り込みが入ったときの、ナビの待機・中断（stop）・再開と、
移動中の扱い（navigation_interrupt_mode）の決定。InterruptManager が使う。
"""
import time
from logging import getLogger
from typing import Dict, Any

from .action_change_notifier import notifier_for
from .navigation_query import get_action_status, get_collection_and_actor, navigation_query
from .constants import NavigationInterruptMode
from .scenario_model import Scenario, ScenarioLike


class NavigationSuspender:
    """割り込み時のナビゲーション処理（待つ・止める・再開する）"""

    STOP_COMMAND_TIMEOUT = 10.0  # navi中断時に stop の処理完了を待つ最大時間（秒）

    def __init__(self, interpreter) -> None:
        """
        Args:
            interpreter: ctx.active_navigations / action_managers / update_current_state /
                default_navigation_interrupt_mode を持つもの（InterruptRuntime）
        """
        self.interpreter = interpreter
        self._logger = getLogger(__name__)

    def wait_for_navigations_completion(self, timeout: float = 30.0) -> bool:
        """
        実行中のnavigationが完了するまで待機

        Args:
            timeout: 最大待機時間（秒）

        Returns:
            全navigationが完了した場合True
        """
        self._logger.info(f"Waiting for navigation completion (timeout: {timeout}s)")

        start_time = time.time()

        while time.time() - start_time < timeout:
            all_completed = True

            for actor_id, managers_dict in self.interpreter.action_managers.items():
                collection, nav_actor = get_collection_and_actor(managers_dict.get("navigation"))
                if collection is None or nav_actor is None:
                    continue

                # 待機中・実行中のnavigationをチェック
                playing_count = collection.count_documents(
                    navigation_query(nav_actor, ("is_playing", "waiting"))
                )

                if playing_count > 0:
                    all_completed = False
                    break

            if all_completed:
                return True

            time.sleep(0.1)

        self._logger.warning(f"Navigation completion timeout ({timeout}s)")
        return False

    def suspend_active_navigations(self) -> Dict[str, Any]:
        """
        実行中のnavigationを中断（DB上でキャンセル）

        各アクターの is_playing / waiting 状態のナビゲーションを cancelled に更新し、送り直すために覚えておく。
        DB 上で実行中の移動がないアクター（外側の割り込みがもう止めた、など）は、止めていないので覚えない。

        Returns:
            {actor: nav_info} 形式の中断前ナビゲーションデータ（resume用）
        """
        suspended_nav_data: Dict[str, Any] = {}

        for actor, nav_info in list(self.interpreter.ctx.active_navigations.items()):
            # resume用のデータ
            saved = nav_info.copy() if isinstance(nav_info, dict) else {"destination": nav_info}

            managers_dict = self.interpreter.action_managers.get(actor)
            if not managers_dict:
                self._logger.warning(f"No action_managers for actor {actor}, skipping cancel")
                suspended_nav_data[actor] = saved
                continue

            collection, nav_actor = get_collection_and_actor(managers_dict.get("navigation"))
            if collection is None or nav_actor is None:
                self._logger.warning(f"No navigation manager for actor {actor}, skipping cancel")
                suspended_nav_data[actor] = saved
                continue

            try:
                playing = collection.count_documents(navigation_query(nav_actor, ("is_playing",)))
                waiting = collection.count_documents(navigation_query(nav_actor, ("waiting",)))
                if playing + waiting == 0:
                    # 実行中の移動がない（外側の割り込みがもう止めた、など）。止めていないので、送り直さない
                    self._logger.info(f"No running navigation for {actor}, nothing to suspend")
                    continue
                # 移動中なら action_ctl に stop を送ってロボットを止める
                # （DBのstatus変更だけでは実行中のnaviは止まらない）
                if playing > 0:
                    self._send_stop_command(managers_dict.get("ros_command"), nav_actor)

                for status in ("is_playing", "waiting"):
                    result = collection.update_many(
                        navigation_query(nav_actor, (status,)),
                        {"$set": {"status": "cancelled"}}
                    )
                    if result.modified_count > 0:
                        self._logger.info(
                            f"Suspended {result.modified_count} '{status}' navigation(s) for {actor}"
                        )
                suspended_nav_data[actor] = saved
            except Exception as e:
                self._logger.error(f"Error suspending navigation for {actor}: {e}", exc_info=True)
                suspended_nav_data[actor] = saved

        if suspended_nav_data:
            self._logger.info(f"Suspended navigations for actors: {list(suspended_nav_data.keys())}")

        return suspended_nav_data

    def _send_stop_command(self, ros_manager: Any, actor_name: str) -> None:
        """
        action_ctl に stop を送って実行中のアクションを止める

        Args:
            ros_manager: ros_command 用のアクションマネージャー
            actor_name: ロボット名（topic名に使用）
        """
        if ros_manager is None:
            self._logger.warning(f"No ros_command manager for {actor_name}, cannot send stop")
            return
        stop_cmd = {
            "type": "normal",
            "topic": f"/{actor_name}/robot/action_ctl",
            "topic_type": "std_msgs/msg/String",
            "data": "stop"
        }
        try:
            ret = ros_manager.insert(stop_cmd)
            if ret and hasattr(ret, "inserted_id"):
                self._logger.info(f"Sent stop to {actor_name} for navigation suspend ({ret.inserted_id})")
            else:
                self._logger.error(f"Failed to send stop to {actor_name}: insert returned {ret}")
                return
        except Exception as e:
            self._logger.error(f"Error sending stop to {actor_name}: {e}", exc_info=True)
            return

        # stop はロボット側で数秒かけて処理され、その間に実行中のアクションをすべて止める。
        # 割り込みの発話まで止められないよう、処理が終わるまで待ってから割り込みを始める
        start_time = time.time()
        notifier = notifier_for(get_collection_and_actor(ros_manager)[0])
        with notifier.watching(ret.inserted_id) as changed:
            while time.time() - start_time < self.STOP_COMMAND_TIMEOUT:
                try:
                    status = get_action_status(ros_manager, ret.inserted_id)
                except Exception as e:
                    self._logger.error(f"Error checking stop command status: {e}")
                    return
                if status not in ("waiting", "is_playing"):
                    self._logger.info(
                        f"Stop processed by {actor_name} (status: {status}, "
                        f"waited: {time.time() - start_time:.1f}s)"
                    )
                    return
                notifier.pause(changed)
        self._logger.warning(
            f"Stop command not processed by {actor_name} within {self.STOP_COMMAND_TIMEOUT}s"
        )

    def resume_interrupted_navigations(self, suspended_nav_data: Dict[str, Any] = None) -> None:
        """
        中断したnavigationを再開

        Args:
            suspended_nav_data: suspend_active_navigations() が返した {actor: nav_info} dict
        """
        data = suspended_nav_data if suspended_nav_data else {}

        for actor, nav_info in data.items():
            managers_dict = self.interpreter.action_managers.get(actor)
            if not managers_dict:
                self._logger.warning(f"No action_managers for actor {actor}, skipping resume")
                continue

            nav_manager = managers_dict.get("navigation")
            if not nav_manager:
                self._logger.warning(f"No navigation manager for actor {actor}, skipping resume")
                continue

            # ナビゲーションオプションを取り出す
            nav_option = nav_info.get("navigation_data", {}).get("option") if isinstance(nav_info, dict) else None
            if not nav_option:
                destination = nav_info.get("destination") if isinstance(nav_info, dict) else nav_info
                if destination:
                    nav_option = {"destination": destination} if isinstance(destination, str) else {"navigation": destination}
                else:
                    self._logger.warning(f"No navigation data to resume for {actor}, skipping")
                    continue

            try:
                ret = nav_manager.insert(nav_option)
                if ret and hasattr(ret, "inserted_id"):
                    new_action_id = str(ret.inserted_id)
                    # active_navigations の action_id を更新
                    if actor in self.interpreter.ctx.active_navigations:
                        if isinstance(self.interpreter.ctx.active_navigations[actor], dict):
                            self.interpreter.ctx.active_navigations[actor]["action_id"] = new_action_id
                    # is_navigating フラグを True に更新
                    self.interpreter.update_current_state({
                        "processing": {"is_navigating": True}
                    })
                    self._logger.info(
                        f"Resumed navigation for {actor}: {nav_option} (new action_id: {new_action_id})"
                    )
                else:
                    self._logger.error(f"Failed to resume navigation for {actor}: insert returned {ret}")
            except Exception as e:
                self._logger.error(f"Error resuming navigation for {actor}: {e}", exc_info=True)

    def default_mode_for(self, subscenario: ScenarioLike) -> str:
        """
        サブシナリオから navigation_interrupt_mode のデフォルト値を決定

        priority は実行の順番と重みで、移動中の扱いは決めない。
        important / force_interrupt のときだけnaviを中断し（suspend_and_resume）、
        それ以外は default_navigation_interrupt_mode（デフォルト: parallel）を使う。
        直接決めたいときは navigation_interrupt_mode を書く。

        Args:
            subscenario: サブシナリオ（DB の文書でもよい）

        Returns:
            navigation_interrupt_mode 文字列
        """
        if Scenario.coerce(subscenario).always_interrupts:
            return NavigationInterruptMode.SUSPEND
        return self.interpreter.default_navigation_interrupt_mode
