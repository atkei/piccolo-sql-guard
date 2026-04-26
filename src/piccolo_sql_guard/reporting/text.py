from __future__ import annotations

from piccolo_sql_guard.models import Diagnostic


def render_text(diagnostics: list[Diagnostic]) -> str:
    lines = [
        f"{d.path}:{d.line}:{d.column}: {d.rule_code} {d.message}" for d in diagnostics
    ]
    return "\n".join(lines)
