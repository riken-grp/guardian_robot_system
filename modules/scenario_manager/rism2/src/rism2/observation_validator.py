"""
届いた観測（physical_topic / cyber_topic）を schemas/observation.schema.json で検査し、合わなければ警告する

実行は止めない。同じ問題は1回だけ知らせる。
- イベント名が小文字の snake_case でない（例: "keyword-wake"）→ 警告
- スキーマにないイベント名 → INFO（新しいイベントかもしれないので）
- contents が、そのイベントの形に合わない（例: person_found に distance がない）→ 警告
"""
import json
import re
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "observation.schema.json"
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


class ObservationValidator:
    def __init__(self, schema_path: Path = SCHEMA_PATH):
        self._logger = getLogger(__name__)
        self._validators: Dict[str, Any] = {}
        self._known: set = set()
        self._reported: set = set()
        try:
            import jsonschema
            schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
            self._known = set(schema.get("known_events", []))
            for name in self._known:
                definition = schema["$defs"].get(name, {"$ref": "#/$defs/any"})
                self._validators[name] = jsonschema.Draft202012Validator({**definition, "$defs": schema["$defs"]})
        except Exception as e:
            self._logger.warning(f"Observation schema check disabled: {e}")

    def problems(self, observation: Dict[str, Any]) -> List[str]:
        """合わない箇所（イベント名の書き方と contents の形）"""
        name = observation.get("event")
        if not isinstance(name, str):
            return []
        found = []
        if not SNAKE_CASE.match(name):
            found.append(f"event name '{name}' is not snake_case")
        validator = self._validators.get(name)
        if validator is not None:
            contents = json.loads(json.dumps(observation.get("contents", {}), default=str))
            for e in sorted(validator.iter_errors(contents), key=lambda e: list(e.absolute_path)):
                where = "/".join(str(p) for p in e.absolute_path) or "contents"
                found.append(f"{name}: {where}: {e.message}")
        return found

    def check(self, observation: Dict[str, Any]) -> None:
        """観測を検査し、まだ知らせていない問題を知らせる"""
        if not self._validators:
            return
        name = observation.get("event")
        for problem in self.problems(observation):
            self._report(problem, warning=True)
        if isinstance(name, str) and SNAKE_CASE.match(name) and name not in self._known:
            self._report(f"unknown observation event '{name}' (not in observation.schema.json)", warning=False)

    def _report(self, message: str, warning: bool) -> None:
        if message in self._reported:
            return
        self._reported.add(message)
        log = self._logger.warning if warning else self._logger.info
        log(f"[ObservationCheck] {message}")
