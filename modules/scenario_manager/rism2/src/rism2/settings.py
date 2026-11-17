"""settings.py - RISM の設定項目（rism_configs.rism_config）の一覧と、起動時の検査

設定の項目・型・既定値・説明はここにだけ書く（docs/CONFIG.md はここから作る）。
起動時に check_and_fill() で設定を検査し、
- 知らない項目（打ち間違いや、もう使っていない項目）と、型の違う値を警告する（実行は止めない）
- 書いていない項目に既定値を入れる（既定値が None の項目は入れない）
"""
from typing import Any, Dict, List, Tuple

NUMBER = (int, float)

# 項目名: (型, 既定値, 説明)。値が dict なら、その下の項目の一覧
SETTINGS: Dict[str, Any] = {
    "latest_N": (int, 100, "観測を読むときの最大件数"),
    "observation_cache_size": (int, 10000, "観測のキャッシュの最大件数"),
    "use_change_streams": (bool, True, "観測を Change Streams で受け取る（false ならポーリング）"),
    "cleanup_topics_on_start": (bool, True, "起動時に、それまでの未使用の観測を使用済みにする"),
    "max_history_length": (int, 10, "LLM に渡す会話履歴の最大件数"),
    "finished_queue_length": (int, 100, "実行したイベントを覚えておく件数"),
    "interruption_probability": (NUMBER, 1.0, "割り込みを発動させる確率（サブシナリオの interruption_probability が優先）"),
    "default_scenario_exit_code": (str, "success", "scenario_exit がないシナリオの終わり方"),
    "default_navigation_interrupt_mode": (str, "parallel", "割り込みで移動をどうするか（parallel / suspend_and_resume / wait_completion）"),
    "internal_state_priority_rules": (list, [], "内部状態による割り込みの優先度の調整規則"),
    "executor": {
        "default_timeout": (NUMBER, 30, "動作の完了待ちと、timeout のない wait_for / if / until の待ち時間（秒）"),
        "default_utterance_timeout": (NUMBER, None, "発話の完了待ち（秒）。なければ default_timeout"),
        "default_gesture_timeout": (NUMBER, None, "ジェスチャーの完了待ち（秒）。なければ default_timeout"),
        "default_navigation_timeout": (NUMBER, None, "移動の完了待ち（秒）。なければ default_timeout"),
        "default_dock_timeout": (NUMBER, 200, "ドッキング（navigation の dock）の完了待ち（秒）"),
        "default_eye_timeout": (NUMBER, None, "目の表示の完了待ち（秒）。なければ default_timeout"),
        "default_ros_command_timeout": (NUMBER, None, "ROS コマンドの完了待ち（秒）。なければ default_timeout"),
        "default_command_event_timeout": (NUMBER, None, "command_event の完了待ち（秒）。なければ default_timeout"),
        "navigation_quick_fail_sec": (NUMBER, 5, "送ってこの秒数以内に失敗した移動は、ロボットに拒否されたとみなして送り直す"),
        "navigation_resends": (int, 2, "すぐ失敗した移動を送り直す回数"),
        "navigation_resend_delay": (NUMBER, 3, "すぐ失敗した移動を送り直すまで待つ秒数"),
    },
    "prefetch": {
        "enabled": (bool, True, "次の LLM 発話を先に作っておく"),
        "wait_timeout": (NUMBER, 30.0, "先に作っている発話を待つ最大秒数"),
    },
    "error_recovery": {
        "default_retry_count": (int, 0, "動作が失敗したときのリトライ回数（イベントの retry がなければ）"),
        "default_retry_delay": (NUMBER, 1.0, "リトライまで待つ秒数"),
        "max_retry_count": (int, 5, "リトライ回数の上限"),
        "min_retry_delay": (NUMBER, 0.1, "リトライまで待つ秒数の下限"),
    },
    "stress_level": {
        "increment": (NUMBER, 0.2, "割り込みがキューに入るたびに増やす量"),
        "decrement": (NUMBER, 0.1, "シナリオが終わるたびに減らす量"),
        "thresholds": (list, [], "閾値を超えたときに入れる割り込み"),
    },
    "debug": {
        "visualize_interrupt_queue": (bool, False, "割り込みキューを画面に表示する"),
        "track_interrupt_queue": (bool, False, "割り込みキューを MongoDB に記録する"),
    },
    "debug_mode": {
        "enabled": (bool, False, "シナリオのデバッグモード"),
        "show_state_dump": (bool, True, "イベントの前後の状態を出す"),
        "show_llm_prompts": (bool, False, "LLM に渡すプロンプトを出す"),
        "show_llm_responses": (bool, False, "LLM の応答を出す"),
    },
    "timezone": {
        "mode": (str, "system", "時刻の扱い（system / explicit）"),
        "explicit": (str, None, "mode が explicit のときのタイムゾーン（例: Asia/Tokyo）"),
    },
}

# 設定ではなく、起動時に組み立てるもの（検査しない）
NOT_SETTINGS = {"_id", "robots", "robot_list", "demo", "demo_list"}

# 以前の名前（新しい名前で読む）
RENAMED = {
    ("executor", "resumed_navigation_quick_fail_sec"): "navigation_quick_fail_sec",
    ("executor", "resumed_navigation_resends"): "navigation_resends",
    ("executor", "resumed_navigation_resend_delay"): "navigation_resend_delay",
}


def _type_name(expected: Any) -> str:
    if expected is NUMBER:
        return "number"
    return expected.__name__


def _has_type(value: Any, expected: Any) -> bool:
    if isinstance(value, bool):
        return expected is bool
    return isinstance(value, expected)


def check_and_fill(config: Dict[str, Any]) -> List[str]:
    """
    設定を検査し、書いていない項目に既定値を入れる（config を書き換える）

    Returns:
        警告の文（知らない項目、型の違う値）
    """
    warnings: List[str] = []
    _check_section(config, SETTINGS, "", warnings)
    return warnings


def _check_section(values: Dict[str, Any], spec: Dict[str, Any], prefix: str, warnings: List[str]) -> None:
    section = prefix.rstrip(".")
    for key in list(values):
        if not prefix and key in NOT_SETTINGS:
            continue
        if (section, key) in RENAMED:
            new = RENAMED[(section, key)]
            warnings.append(f"{prefix}{key} is renamed to {prefix}{new}")
            values.setdefault(new, values[key])
            continue
        if key not in spec:
            warnings.append(f"unknown setting {prefix}{key} (not read by RISM)")
            continue
        item, value = spec[key], values[key]
        if isinstance(item, dict):
            if isinstance(value, dict):
                _check_section(value, item, f"{prefix}{key}.", warnings)
            else:
                warnings.append(f"{prefix}{key} should be a mapping, got {type(value).__name__}")
        elif value is not None and not _has_type(value, item[0]):
            warnings.append(f"{prefix}{key} should be {_type_name(item[0])}, got {type(value).__name__}: {value!r}")
    for key, item in spec.items():
        if isinstance(item, dict):
            if key not in values:
                values[key] = {}
            if isinstance(values[key], dict):
                _check_section_defaults(values[key], item)
        elif key not in values and item[1] is not None:
            values[key] = _copy(item[1])


def _check_section_defaults(values: Dict[str, Any], spec: Dict[str, Any]) -> None:
    for key, item in spec.items():
        if isinstance(item, dict):
            values.setdefault(key, {})
            if isinstance(values[key], dict):
                _check_section_defaults(values[key], item)
        elif key not in values and item[1] is not None:
            values[key] = _copy(item[1])


def _copy(value: Any) -> Any:
    return list(value) if isinstance(value, list) else dict(value) if isinstance(value, dict) else value


def settings_rows() -> List[Tuple[str, str, Any, str]]:
    """(項目名, 型, 既定値, 説明) の一覧（docs/CONFIG.md 用）"""
    rows = []

    def walk(spec: Dict[str, Any], prefix: str) -> None:
        for key, item in spec.items():
            if isinstance(item, dict):
                walk(item, f"{prefix}{key}.")
            else:
                rows.append((f"{prefix}{key}", _type_name(item[0]), item[1], item[2]))

    walk(SETTINGS, "")
    return rows


def settings_markdown_table() -> str:
    """docs/CONFIG.md の表"""
    def fmt(v: Any) -> str:
        if v is None:
            return "（なし）"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return f'"{v}"'
        return str(v)
    lines = ["| 項目 | 型 | 既定値 | 説明 |", "|---|---|---|---|"]
    lines += [f"| `{name}` | {typ} | {fmt(default)} | {desc} |" for name, typ, default, desc in settings_rows()]
    return "\n".join(lines)


if __name__ == "__main__":
    print(settings_markdown_table())
