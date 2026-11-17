"""
Event Generator で共通に使う処理

- 聞いた発話（asr）の取り出し
- 文やプロンプトの {変数} の置き換え（{greeting} {now} {heard} {triggered[...]} {wait_for...}）
- 最近の観測（物体・人の検出など）をプロンプトに入れるための説明文
"""
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Union

# (この時刻より前, 挨拶) の順に判定する
# 深夜（0〜4時台）は「おはよう」ではなく「こんばんは」
GREETINGS = [(5, "こんばんは"), (10, "おはようございます"), (17, "こんにちは"), (19, "お疲れ様です"), (24, "こんばんは")]

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def greeting_for(now: datetime) -> str:
    """時間帯に応じた挨拶"""
    return next(g for hour, g in GREETINGS if now.hour < hour)


def _contents(obs: Any) -> Dict[str, Any]:
    if not isinstance(obs, dict):
        return {}
    contents = obs.get("contents", obs.get("content"))
    return contents if isinstance(contents, dict) else {}


def heard_text(observations: Optional[Dict[str, Any]]) -> str:
    """
    待っていた観測（wait_for）か、割り込みのきっかけの観測（triggered）から、聞いた発話を取り出す

    Returns:
        発話の文。無ければ空文字
    """
    if not observations:
        return ""
    for key in ("wait_for", "triggered"):
        obs = observations.get(key)
        if not obs:
            continue
        if isinstance(obs.get("content"), str):
            return obs["content"]
        sources = [_contents(obs), obs]
        for source in sources:
            for field in ("text", "words", "utterance", "message"):
                value = source.get(field)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _resolve(expr: str, context: Dict[str, Any]) -> Optional[str]:
    """{triggered[name]} や {wait_for.contents.text} の中身を辿る。見つからなければ None"""
    parts = [p for p in re.split(r"[.\[\]]", expr) if p]
    value: Any = context
    for part in parts:
        part = part.strip("'\"")
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    if value is None or isinstance(value, (dict, list)):
        return None
    return str(value)


def fill_placeholders(text: str, observations: Optional[Dict[str, Any]] = None,
                      now: Optional[datetime] = None) -> str:
    """
    文やプロンプトの {変数} を置き換える

    - {now}: 現在時刻（例: 14時05分）
    - {greeting}: 時間帯の挨拶
    - {heard}: 聞いた発話
    - {triggered[名前]} / {triggered.名前}: 割り込みのきっかけの観測の値（contents の中も見る）
    - {wait_for.contents.text} など: 待っていた観測の値

    置き換えられない {変数} はそのまま残す。
    """
    if not text:
        return text
    now = now or datetime.now()
    observations = observations or {}
    triggered = observations.get("triggered") or {}
    if isinstance(triggered, dict):
        triggered = {**triggered, **_contents(triggered)}
    context = {
        "now": now.strftime("%H時%M分"),
        "greeting": greeting_for(now),
        "heard": heard_text(observations) or None,
        "triggered": triggered,
        "wait_for": observations.get("wait_for") or {},
    }

    def replace(match):
        value = _resolve(match.group(1).strip(), context)
        return match.group(0) if value is None else value

    return _PLACEHOLDER.sub(replace, text)


def has_unfilled_placeholders(text: str) -> bool:
    """置き換えられずに残った {変数} があるか"""
    return bool(_PLACEHOLDER.search(text or ""))


def describe_recent_observations(observations: Optional[Dict[str, Any]],
                                 spec: Union[Dict[str, Optional[str]], Iterable[str]],
                                 window_sec: float = 60, now: Optional[datetime] = None) -> str:
    """
    最近の観測を、LLM に渡す短い説明文にする

    Args:
        observations: generate に渡される観測（"recent" に最近の観測 {"tBlackBoard": [...]} が入る）
        spec: 使うイベント名のリスト、または {イベント名: 表示する contents のフィールド名 (null なら件数だけ)}
        window_sec: この秒数より前の観測は使わない
        now: 現在時刻（テスト用）

    Returns:
        例: "最近の観測:\\n- appear: handbag, cup\\n- face_detected: 2回"。該当なしなら空文字
    """
    recent = (observations or {}).get("recent") or {}
    if isinstance(spec, dict):
        fields = dict(spec)
    else:
        fields = {name: None for name in spec}
    if not fields or not isinstance(recent, dict):
        return ""
    now_ts = (now or datetime.now()).timestamp()
    values: Dict[str, list] = {name: [] for name in fields}
    counts: Dict[str, int] = {name: 0 for name in fields}
    for obs_list in recent.values():
        for obs in obs_list or []:
            name = obs.get("event") if isinstance(obs, dict) else None
            if name not in fields:
                continue
            oid = obs.get("_id")
            if hasattr(oid, "generation_time") and now_ts - oid.generation_time.timestamp() > window_sec:
                continue
            counts[name] += 1
            field = fields[name]
            if field:
                value = _contents(obs).get(field, obs.get(field))
                if value is not None and str(value) not in values[name]:
                    values[name].append(str(value))
    lines = []
    for name in fields:
        if values[name]:
            lines.append(f"- {name}: {', '.join(values[name])}")
        elif counts[name]:
            lines.append(f"- {name}: {counts[name]}回")
    return "最近の観測:\n" + "\n".join(lines) if lines else ""


def make_speak_event(actor: str, event: Dict[str, Any], text: str) -> Dict[str, Any]:
    """
    text を話す action イベントを作る

    元の generate イベントに gesture / eye があれば一緒に実行する。
    """
    generated = {
        "type": "action",
        "actor": actor,
        "interruptable": event.get("interruptable", True),
        "speak": {"type": "normal", "option": {"text": text}},
    }
    for key in ("gesture", "eye"):
        if key in event and isinstance(event[key], dict) and event[key].get("type") != "generate":
            generated[key] = event[key]
    return generated


def speak_option(event: Dict[str, Any]) -> Dict[str, Any]:
    """generate イベントの speak.option"""
    option = (event.get("speak") or {}).get("option")
    return option if isinstance(option, dict) else {}


def with_speak_option(event: Dict[str, Any], **changes: Any) -> Dict[str, Any]:
    """speak.option の一部を変えた generate イベントのコピー（LLM に任せるときに使う）"""
    copied = dict(event)
    speak = dict(event.get("speak") or {"type": "generate"})
    speak["option"] = {**speak_option(event), **changes}
    copied["speak"] = speak
    return copied


def generated_text(events: Any) -> str:
    """generate の結果から、話す文を取り出す（最初の speak）"""
    for generated in events or []:
        if isinstance(generated, dict):
            text = ((generated.get("speak") or {}).get("option") or {}).get("text")
            if isinstance(text, str):
                return text
    return ""
