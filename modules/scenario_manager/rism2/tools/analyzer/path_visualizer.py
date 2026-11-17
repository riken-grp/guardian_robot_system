"""
Path Visualizer for RISM2 Scenarios

シナリオの実行パスをMermaid形式で可視化するモジュール
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import logging


@dataclass
class GraphNode:
    """グラフノード"""
    id: str
    type: str  # "action", "if", "repeat", "random", "until", "wait_for", "start", "end"
    label: str
    event_index: Optional[int] = None


@dataclass
class GraphEdge:
    """グラフエッジ"""
    from_node: str
    to_node: str
    label: Optional[str] = None  # "true", "false", "failure", etc.
    edge_type: str = "sequential"  # "sequential", "conditional", "loop"


@dataclass
class Graph:
    """グラフ構造"""
    nodes: List[GraphNode]
    edges: List[GraphEdge]

    def add_node(self, node: GraphNode):
        """ノードを追加"""
        self.nodes.append(node)

    def add_edge(self, edge: GraphEdge):
        """エッジを追加"""
        self.edges.append(edge)


class PathVisualizer:
    """シナリオ実行パス可視化クラス"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        初期化

        Args:
            logger: ロガー（オプション）
        """
        self.logger = logger or logging.getLogger(__name__)
        self.node_counter = 0

    def visualize_scenario(self, scenario: Dict[str, Any]) -> str:
        """
        シナリオをMermaid形式で可視化

        Args:
            scenario: シナリオデータ

        Returns:
            str: Mermaid形式のグラフ
        """
        scenario_name = scenario.get("name", "unnamed")
        self.logger.info(f"Visualizing scenario: {scenario_name}")

        # グラフ構造を構築
        graph = self._build_graph(scenario)

        # Mermaid形式に変換
        mermaid = self._generate_mermaid(graph, scenario_name)

        self.logger.info(f"Visualization complete: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

        return mermaid

    def _build_graph(self, scenario: Dict[str, Any]) -> Graph:
        """
        シナリオからグラフ構造を構築

        Args:
            scenario: シナリオデータ

        Returns:
            Graph: グラフ構造
        """
        graph = Graph(nodes=[], edges=[])
        events = scenario.get("events", [])

        # ノードカウンターをリセット
        self.node_counter = 0

        # 開始ノードを追加
        start_node = GraphNode(
            id="Start",
            type="start",
            label=f"Start: {scenario.get('name', 'unnamed')}"
        )
        graph.add_node(start_node)

        # イベントを走査してグラフを構築
        last_node_id = "Start"
        if events:
            last_node_id = self._traverse_events(events, graph, last_node_id)

        # 終了ノードを追加
        end_node = GraphNode(
            id="End",
            type="end",
            label="End"
        )
        graph.add_node(end_node)
        graph.add_edge(GraphEdge(from_node=last_node_id, to_node="End"))

        return graph

    def _traverse_events(
        self,
        events: List[Dict[str, Any]],
        graph: Graph,
        prev_node_id: str
    ) -> str:
        """
        イベントリストを走査してグラフに追加

        Args:
            events: イベントリスト
            graph: グラフ構造
            prev_node_id: 前のノードID

        Returns:
            str: 最後のノードID
        """
        current_node_id = prev_node_id

        for i, event in enumerate(events):
            event_type = event.get("type", "")
            node_id = f"Event{self.node_counter}"
            self.node_counter += 1

            if event_type == "action":
                # アクションノード
                label = self._create_action_label(event)
                node = GraphNode(
                    id=node_id,
                    type="action",
                    label=label,
                    event_index=i
                )
                graph.add_node(node)
                graph.add_edge(GraphEdge(from_node=current_node_id, to_node=node_id))
                current_node_id = node_id

            elif event_type == "if":
                # if分岐ノード
                label = f"if: {event.get('condition', {})}"
                node = GraphNode(
                    id=node_id,
                    type="if",
                    label=label,
                    event_index=i
                )
                graph.add_node(node)
                graph.add_edge(GraphEdge(from_node=current_node_id, to_node=node_id))

                # true/false/failure分岐を処理
                true_last = self._traverse_events(
                    event.get("true", []),
                    graph,
                    node_id
                ) if "true" in event else node_id

                false_last = self._traverse_events(
                    event.get("false", []),
                    graph,
                    node_id
                ) if "false" in event else node_id

                failure_last = self._traverse_events(
                    event.get("failure", []),
                    graph,
                    node_id
                ) if "failure" in event else node_id

                # 分岐後の合流ノードを作成
                merge_node_id = f"Merge{self.node_counter}"
                self.node_counter += 1
                merge_node = GraphNode(
                    id=merge_node_id,
                    type="merge",
                    label="",
                    event_index=None
                )
                graph.add_node(merge_node)

                # 各分岐から合流ノードへのエッジを追加
                if "true" in event:
                    edge = GraphEdge(from_node=node_id, to_node=true_last, label="true", edge_type="conditional")
                    # 最初のエッジを修正（node_id -> true分岐の最初のノード）
                    true_events = event.get("true", [])
                    if true_events:
                        # 既に追加されているエッジを探して、ラベルを追加
                        for e in graph.edges:
                            if e.from_node == node_id and e.label is None:
                                e.label = "true"
                                e.edge_type = "conditional"
                                break
                    graph.add_edge(GraphEdge(from_node=true_last, to_node=merge_node_id))

                if "false" in event:
                    # false分岐のエッジにラベルを追加
                    false_events = event.get("false", [])
                    if false_events:
                        for e in graph.edges:
                            if e.from_node == node_id and e.label is None:
                                e.label = "false"
                                e.edge_type = "conditional"
                                break
                    graph.add_edge(GraphEdge(from_node=false_last, to_node=merge_node_id))

                if "failure" in event:
                    # failure分岐のエッジにラベルを追加
                    failure_events = event.get("failure", [])
                    if failure_events:
                        for e in graph.edges:
                            if e.from_node == node_id and e.label is None:
                                e.label = "failure"
                                e.edge_type = "conditional"
                                break
                    graph.add_edge(GraphEdge(from_node=failure_last, to_node=merge_node_id))

                current_node_id = merge_node_id

            elif event_type == "repeat":
                # repeatループノード
                count = event.get("count", "?")
                label = f"repeat: {count}x"
                node = GraphNode(
                    id=node_id,
                    type="repeat",
                    label=label,
                    event_index=i
                )
                graph.add_node(node)
                graph.add_edge(GraphEdge(from_node=current_node_id, to_node=node_id))

                # ループ内のイベントを処理
                loop_last = self._traverse_events(
                    event.get("events", []),
                    graph,
                    node_id
                )

                # ループバックエッジを追加
                graph.add_edge(GraphEdge(
                    from_node=loop_last,
                    to_node=node_id,
                    label="loop",
                    edge_type="loop"
                ))

                # ループ終了後の次のノードへ
                current_node_id = node_id

            elif event_type == "until":
                # untilループノード
                label = "until: condition"
                node = GraphNode(
                    id=node_id,
                    type="until",
                    label=label,
                    event_index=i
                )
                graph.add_node(node)
                graph.add_edge(GraphEdge(from_node=current_node_id, to_node=node_id))

                # ループ内のイベントを処理
                loop_last = self._traverse_events(
                    event.get("loop", []),
                    graph,
                    node_id
                ) if "loop" in event else node_id

                # failure分岐を処理
                failure_last = self._traverse_events(
                    event.get("failure", []),
                    graph,
                    node_id
                ) if "failure" in event else node_id

                # ループバックエッジを追加
                if "loop" in event:
                    graph.add_edge(GraphEdge(
                        from_node=loop_last,
                        to_node=node_id,
                        label="loop",
                        edge_type="loop"
                    ))

                current_node_id = node_id

            elif event_type == "random":
                # randomノード
                label = "random"
                node = GraphNode(
                    id=node_id,
                    type="random",
                    label=label,
                    event_index=i
                )
                graph.add_node(node)
                graph.add_edge(GraphEdge(from_node=current_node_id, to_node=node_id))

                # random内のイベントを処理（各オプションを順次追加）
                random_events = event.get("events", [])
                for j, random_event in enumerate(random_events):
                    option_last = self._traverse_events(
                        [random_event],
                        graph,
                        node_id
                    )
                    # オプションのラベルを追加
                    for e in graph.edges:
                        if e.from_node == node_id and e.label is None:
                            e.label = f"option_{j + 1}"
                            e.edge_type = "conditional"
                            break

                current_node_id = node_id

            elif event_type == "wait_for":
                # wait_forノード
                label = "wait_for"
                node = GraphNode(
                    id=node_id,
                    type="wait_for",
                    label=label,
                    event_index=i
                )
                graph.add_node(node)
                graph.add_edge(GraphEdge(from_node=current_node_id, to_node=node_id))

                # success/failure分岐を処理
                success_last = self._traverse_events(
                    event.get("success", []),
                    graph,
                    node_id
                ) if "success" in event else node_id

                failure_last = self._traverse_events(
                    event.get("failure", []),
                    graph,
                    node_id
                ) if "failure" in event else node_id

                current_node_id = node_id

            elif event_type == "wait":
                # waitノード
                seconds = event.get("seconds", "?")
                label = f"wait: {seconds}s"
                node = GraphNode(
                    id=node_id,
                    type="wait",
                    label=label,
                    event_index=i
                )
                graph.add_node(node)
                graph.add_edge(GraphEdge(from_node=current_node_id, to_node=node_id))
                current_node_id = node_id

        return current_node_id

    def _create_action_label(self, event: Dict[str, Any]) -> str:
        """
        アクションイベントのラベルを作成

        Args:
            event: アクションイベント

        Returns:
            str: ラベル
        """
        actor = event.get("actor", "?")
        parts = []

        # speakコマンド
        if "speak" in event:
            speak = event["speak"]
            speak_type = speak.get("type", "normal")
            if speak_type == "normal":
                text = speak.get("option", {}).get("text", "")
                parts.append(f"speak: {text[:30]}...")
            elif speak_type == "generate":
                parts.append("speak: [LLM]")
            else:
                parts.append(f"speak: [{speak_type}]")

        # gestureコマンド
        if "gesture" in event:
            gesture = event["gesture"]
            command = gesture.get("option", {}).get("command", "")
            parts.append(f"gesture: {command}")

        # navigationコマンド
        if "navigation" in event:
            navigation = event["navigation"]
            target = navigation.get("option", {}).get("target", "")
            parts.append(f"nav: {target}")

        # その他のコマンド
        for cmd in ["ros_command", "eye"]:
            if cmd in event:
                parts.append(cmd)

        label = " + ".join(parts) if parts else "action"
        return f"{actor}: {label}"

    def _generate_mermaid(self, graph: Graph, scenario_name: str) -> str:
        """
        グラフ構造からMermaid形式の文字列を生成

        Args:
            graph: グラフ構造
            scenario_name: シナリオ名

        Returns:
            str: Mermaid形式のグラフ
        """
        lines = []
        lines.append("```mermaid")
        lines.append("graph TD")

        # ノードを定義
        for node in graph.nodes:
            if node.type == "start":
                lines.append(f"    {node.id}([{node.label}])")
            elif node.type == "end":
                lines.append(f"    {node.id}([{node.label}])")
            elif node.type in ["if", "until", "random", "wait_for"]:
                lines.append(f"    {node.id}{{{node.label}}}")
            elif node.type == "merge":
                # 合流ノードは表示しない（エッジで接続のみ）
                continue
            else:
                lines.append(f"    {node.id}[{node.label}]")

        # エッジを定義
        for edge in graph.edges:
            # 合流ノードをスキップ
            from_node = edge.from_node
            to_node = edge.to_node

            # 合流ノードの場合、その先のノードを探す
            if any(n.id == to_node and n.type == "merge" for n in graph.nodes):
                # 合流ノードの次のノードを探す
                for e in graph.edges:
                    if e.from_node == to_node:
                        to_node = e.to_node
                        break

            if edge.label:
                lines.append(f"    {from_node} -->|{edge.label}| {to_node}")
            else:
                lines.append(f"    {from_node} --> {to_node}")

        lines.append("```")

        return "\n".join(lines)

    def save_visualization(self, mermaid: str, filepath: str):
        """
        Mermaid形式の可視化をファイルに保存

        Args:
            mermaid: Mermaid形式の文字列
            filepath: 保存先ファイルパス
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Scenario Path Visualization\n\n")
            f.write(mermaid)
            f.write("\n")

        self.logger.info(f"Visualization saved to: {filepath}")


if __name__ == "__main__":
    # デバッグ用：簡単なテスト
    test_scenario = {
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
                            "type": "normal",
                            "option": {"text": "True branch"}
                        }
                    }
                ],
                "false": [
                    {
                        "type": "action",
                        "actor": "robot1",
                        "speak": {
                            "type": "normal",
                            "option": {"text": "False branch"}
                        }
                    }
                ]
            },
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

    visualizer = PathVisualizer()
    mermaid = visualizer.visualize_scenario(test_scenario)
    print(mermaid)
