from __future__ import annotations

import json

from piccolo_sql_guard.models import Diagnostic


def render_json(diagnostics: list[Diagnostic]) -> str:
    items = []
    for d in diagnostics:
        item: dict[str, object] = {
            "path": d.path,
            "line": d.line,
            "column": d.column,
            "end_line": d.end_line,
            "end_column": d.end_column,
            "rule_code": d.rule_code,
            "message": d.message,
            "severity": d.severity.value,
        }
        if d.symbol is not None:
            item["symbol"] = d.symbol
        items.append(item)
    return json.dumps(items, indent=2)
