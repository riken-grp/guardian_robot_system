"""
シナリオDBの文書を schemas/scenario.schema.json（パッケージの中）で検査し、合わない箇所を警告する

実行は止めない。同じ文書（同じ中身）については1回だけ警告する。
"""
import json
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "scenario.schema.json"


class ScenarioSchemaValidator:
    """シナリオ（scenario）とサブシナリオ（subscenario）をスキーマで検査する"""

    def __init__(self, schema_path: Path = SCHEMA_PATH):
        self._logger = getLogger(__name__)
        self._validators: Dict[str, Any] = {}
        self._checked = set()
        try:
            import jsonschema
            schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
            for kind in ("scenario", "subscenario"):
                self._validators[kind] = jsonschema.Draft202012Validator(
                    {"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]})
        except Exception as e:
            # 検査できなくても実行は続ける
            self._logger.warning(f"Scenario schema check disabled: {e}")

    def errors(self, doc: Dict[str, Any], kind: str) -> List[str]:
        """合わない箇所を「場所: 内容」の形で返す"""
        validator = self._validators.get(kind)
        if validator is None or not isinstance(doc, dict):
            return []
        plain = json.loads(json.dumps(doc, default=str))
        return [
            f"{'/'.join(str(p) for p in e.absolute_path) or '(top)'}: {e.message}"
            for e in sorted(validator.iter_errors(plain), key=lambda e: list(e.absolute_path))
        ]

    def check(self, doc: Optional[Dict[str, Any]], kind: str) -> None:
        """合わない箇所があれば警告する（同じ中身の文書は2回目以降は何もしない）"""
        if not isinstance(doc, dict):
            return
        key = (str(doc.get("_id")), json.dumps(doc, default=str, sort_keys=True))
        if key in self._checked:
            return
        self._checked.add(key)
        for error in self.errors(doc, kind):
            self._logger.warning(f"[SchemaCheck] {kind} '{doc.get('name')}': {error}")
