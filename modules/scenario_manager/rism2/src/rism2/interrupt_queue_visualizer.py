"""
Interrupt Queue Visualizer for RISM2

割り込みキューの状態をRichライブラリで可視化するクラス
"""

from typing import Dict, Any
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class InterruptQueueVisualizer:
    """
    割り込みキューの可視化クラス

    Richライブラリを使用してキューの状態を美しく表示します。
    Richが利用できない場合はシンプルなテキスト表示にフォールバックします。
    """

    def __init__(self, use_rich: bool = True):
        """
        初期化

        Args:
            use_rich: Richライブラリを使用するか（デフォルト: True）
        """
        self.use_rich = use_rich and RICH_AVAILABLE
        self.console = Console() if self.use_rich else None

        # 優先度（1〜1000）の範囲ごとの色: (この値以上, 色)
        self.priority_colors = [(1000, "red bold"), (500, "yellow bold"), (100, "green"), (1, "blue")]

    def _priority_color(self, priority: Any) -> str:
        """優先度の値に応じた色"""
        try:
            value = int(priority)
        except (TypeError, ValueError):
            return "white"
        return next((color for minimum, color in self.priority_colors if value >= minimum), "white")

    def display_queue_status(self, status: Dict[str, Any],
                            low_priority_count: int = 0) -> None:
        """
        キュー状態を表示

        Args:
            status: get_status()から取得したキュー状態
            low_priority_count: Low優先度キューのサイズ（オプション）
        """
        if self.use_rich:
            self._display_rich(status, low_priority_count)
        else:
            self._display_plain(status, low_priority_count)

    def _display_rich(self, status: Dict[str, Any],
                     low_priority_count: int = 0) -> None:
        """
        Richライブラリを使用した美しい表示

        Args:
            status: キュー状態
            low_priority_count: Low優先度キューのサイズ
        """
        queue_size = status.get("queue_size", 0)
        timestamp = status.get("timestamp", 0)
        items = status.get("items", [])

        # タイトル作成
        timestamp_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        title = f"[bold cyan]Interrupt Queue Status[/bold cyan] - {timestamp_str}"

        # テーブル作成
        table = Table(title=title, show_header=True, header_style="bold magenta")
        table.add_column("No.", style="cyan", width=4, justify="right")
        table.add_column("Priority", width=10)
        table.add_column("Scenario Name", width=30)
        table.add_column("Age", width=10, justify="right")
        table.add_column("Condition", width=30)

        if queue_size == 0:
            # キューが空の場合
            table.add_row("—", "—", "[dim]Queue is empty[/dim]", "—", "—")
        else:
            # キュー内のアイテムを表示
            for item in items:
                position = str(item["position"])
                priority = item["priority"]
                scenario_name = item["scenario_name"]
                age_seconds = item["age_seconds"]
                condition = self._format_condition(item["condition"])

                # 優先度に応じた色
                priority_color = self._priority_color(priority)
                priority_text = f"[{priority_color}]{priority}[/{priority_color}]"

                # 経過時間のフォーマット
                age_text = self._format_age(age_seconds)

                table.add_row(position, priority_text, scenario_name, age_text, condition)

        # サマリー情報
        summary_lines = []
        summary_lines.append(f"[bold]Priority Queue:[/bold] {queue_size} item(s)")
        if low_priority_count > 0:
            summary_lines.append(f"[bold]Low Priority Queue:[/bold] {low_priority_count} item(s)")
        summary_text = "\n".join(summary_lines)

        # パネルで囲んで表示
        panel = Panel(
            table,
            subtitle=summary_text,
            border_style="cyan",
            padding=(1, 2)
        )

        self.console.print(panel)
        self.console.print()  # 空行

    def _display_plain(self, status: Dict[str, Any],
                      low_priority_count: int = 0) -> None:
        """
        シンプルなテキスト表示（Richが利用できない場合）

        Args:
            status: キュー状態
            low_priority_count: Low優先度キューのサイズ
        """
        queue_size = status.get("queue_size", 0)
        timestamp = status.get("timestamp", 0)
        items = status.get("items", [])

        timestamp_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

        print("=" * 80)
        print(f"Interrupt Queue Status - {timestamp_str}")
        print("=" * 80)

        if queue_size == 0:
            print("Queue is empty")
        else:
            # ヘッダー
            print(f"{'No.':<5} {'Priority':<10} {'Scenario Name':<30} {'Age':<10} {'Condition':<20}")
            print("-" * 80)

            # アイテム
            for item in items:
                position = item["position"]
                priority = item["priority"].upper()
                scenario_name = item["scenario_name"][:28]  # 切り詰め
                age_seconds = item["age_seconds"]
                condition = self._format_condition(item["condition"])[:18]  # 切り詰め

                age_text = self._format_age(age_seconds)

                print(f"{position:<5} {priority:<10} {scenario_name:<30} {age_text:<10} {condition:<20}")

        print("-" * 80)
        print(f"Priority Queue: {queue_size} item(s)")
        if low_priority_count > 0:
            print(f"Low Priority Queue: {low_priority_count} item(s)")
        print("=" * 80)
        print()

    def _format_age(self, age_seconds: float) -> str:
        """
        経過時間をフォーマット

        Args:
            age_seconds: 経過秒数

        Returns:
            フォーマットされた文字列
        """
        if age_seconds < 1:
            return f"{age_seconds*1000:.0f}ms"
        elif age_seconds < 60:
            return f"{age_seconds:.1f}s"
        elif age_seconds < 3600:
            minutes = int(age_seconds / 60)
            seconds = age_seconds % 60
            return f"{minutes}m{seconds:.0f}s"
        else:
            hours = int(age_seconds / 3600)
            minutes = int((age_seconds % 3600) / 60)
            return f"{hours}h{minutes}m"

    def _format_condition(self, condition: Dict[str, Any]) -> str:
        """
        条件をフォーマット

        Args:
            condition: 条件辞書

        Returns:
            フォーマットされた文字列
        """
        if not condition:
            return "—"

        # 主要な条件のみ抽出
        parts = []
        if "mentioned" in condition:
            parts.append(f"mentioned={condition['mentioned']}")
        if "target" in condition:
            target = condition["target"]
            if isinstance(target, list):
                target_str = ", ".join(target[:2])  # 最初の2つのみ
                if len(target) > 2:
                    target_str += "..."
            else:
                target_str = str(target)
            parts.append(f"target={target_str}")
        if "vip_detected" in condition:
            parts.append(f"vip={condition['vip_detected']}")

        if parts:
            return "; ".join(parts)
        else:
            # その他の条件
            return ", ".join(f"{k}={v}" for k, v in list(condition.items())[:2])
