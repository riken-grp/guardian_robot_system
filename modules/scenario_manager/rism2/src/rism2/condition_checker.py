"""condition_checker.py - シナリオの条件と観測の照合

観測は {"tBlackBoard": [観測, ...]} の形で受け取る（ObservationStore.get_recent_observations()）。
各リストは新しい順に並んでいるので、条件に合う観測が複数あれば、新しいものが選ばれる。

条件の書き方（docs/SCENARIO_SCHEMA.md）:
- {"asr": null}                          asr が来ていれば合う
- {"face_detected": {"instance_id": 7}}  contents の値が等しい
- {"person_in_range": {"distance": {"$gte": 3.0, "$lte": 6.0}}}  演算子はすべて満たす
- {"asr": {"text": {"$regex": "はい|うん"}}}、$in / $nin / $ne、$and / $or
"""
import operator
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

Observation = Dict[str, Any]
Observations = Dict[str, List[Observation]]

OPERATORS = {
    "$gt": operator.gt,
    "$lt": operator.lt,
    "$gte": operator.ge,
    "$lte": operator.le,
    "$eq": operator.eq,
    "$ne": operator.ne,
}


def is_match_condition(condition: Dict[str, Any],
                       observations: Observations) -> Tuple[Optional[bool], List[Optional[Observation]]]:
    """
    条件のすべてのキーに合う観測があるか

    Returns:
        (結果, キーごとに合った観測)。結果は
        True: すべてのキーに合う観測がある（条件が空なら観測は []）
        False: あるキーのイベントは来ているが、中身が条件に合わない
        None: あるキーのイベントが来ていない
    """
    if not condition:
        return True, []
    matched = []
    for key, value in condition.items():
        result, obs = _find(observations, key, value)
        matched.append(obs)
        if result is None:
            return None, []
        if not result:
            return False, matched
    return True, matched


def match_any_null_key(condition: Dict[str, Any], observations: Observations) -> Tuple[bool, List[Observation]]:
    """
    wait_for の条件: 値が null のキーがあれば、そのどれか1つのイベントが来れば合う（例: asr か face_detected）

    null のキーがなければ、条件全体（すべてのキー）で照合する。
    """
    null_keys = [key for key, value in condition.items() if value is None]
    if not null_keys:
        result, matched = is_match_condition(condition, observations)
        return bool(result), matched
    obs = first_with_event(observations, null_keys)
    return (True, [obs]) if obs is not None else (False, [])


def first_with_event(observations: Observations, events: Iterable[str]) -> Optional[Observation]:
    """events のどれかのイベントの観測のうち、最初（新しいもの）"""
    events = set(events)
    for obs_list in observations.values():
        for obs in obs_list:
            if obs.get("event") in events:
                return obs
    return None


def _find(observations: Observations, key: str, condition: Any) -> Tuple[Optional[bool], Optional[Observation]]:
    """key のイベントの観測から、条件に合う最初のものを探す（合わない古い観測があっても、その先も見る）"""
    found_event = False
    for obs_list in observations.values():
        for obs in obs_list:
            if obs.get("event") != key:
                continue
            found_event = True
            if _evaluate(obs, condition):
                return True, obs
    return (False, None) if found_event else (None, None)


def _contents(obs: Observation) -> Dict[str, Any]:
    contents = obs.get("contents")
    return contents if isinstance(contents, dict) else {}


def _evaluate(obs: Observation, condition: Any) -> bool:
    """観測1件が条件に合うか"""
    if condition is None:
        return True
    if not isinstance(condition, dict):
        # 値だけの条件は contents.value と比べる
        contents = _contents(obs)
        return "value" in contents and contents["value"] == condition
    return all(_match_field(key, value, obs) for key, value in condition.items())


def _match_field(key: str, expected: Any, obs: Observation) -> bool:
    """条件の1項目（contents のフィールド、または $and / $or）"""
    if key == "$and":
        return all(_evaluate(obs, sub) for sub in expected)
    if key == "$or":
        return any(_evaluate(obs, sub) for sub in expected)

    contents = _contents(obs)
    if key not in contents:
        return False
    actual = contents[key]
    if not isinstance(expected, dict):
        return actual == expected
    # 演算子はすべて満たす（{"$gte": 3, "$lte": 6} は 3 以上かつ 6 以下）
    return bool(expected) and all(_apply(op, param, actual) for op, param in expected.items())


def _apply(op: str, param: Any, actual: Any) -> bool:
    """演算子1つ。比べられない値（null と数値など）は合わないとみなす"""
    try:
        if op in OPERATORS:
            return bool(OPERATORS[op](actual, param))
        if op == "$in":
            return actual in param
        if op == "$nin":
            return actual not in param
        if op == "$regex":
            return isinstance(actual, str) and re.search(param, actual) is not None
    except (TypeError, re.error):
        return False
    return False
