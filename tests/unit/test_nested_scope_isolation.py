"""Regression tests: nested function/class bodies must not leak into the
enclosing function's return provenance, callees, or token sinks."""

from __future__ import annotations

from pathlib import Path

from piccolo_sql_guard.analysis.call_graph import build_call_graph
from piccolo_sql_guard.analysis.function_summary import compute_summary
from piccolo_sql_guard.analysis.project_index import build_project_index


def _write(tmp: Path, name: str, source: str) -> Path:
    p = tmp / name
    p.write_text(source, encoding="utf-8")
    return p


def test_nested_function_returns_do_not_leak(tmp_path: Path) -> None:
    source = """
def outer() -> str:
    def inner(col: str) -> str:
        return f"ORDER BY {col}"
    return "SELECT 1"
"""
    file = _write(tmp_path, "mod.py", source)
    index = build_project_index([file], source_roots=[tmp_path])
    outer_fqn = next(
        fqn for fqn, _ in index.iter_function_items() if fqn.endswith(".outer")
    )
    summary = compute_summary(index.get_function(outer_fqn), index, memo={})
    # outer has exactly one (safe literal) return; no unsafe sinks should
    # leak from ``inner``.
    assert summary.token_sinks == ()
    assert summary.return_provenance.is_safe()


def test_nested_function_calls_do_not_leak(tmp_path: Path) -> None:
    source = """
def helper() -> str:
    return "SELECT 1"


def outer() -> str:
    def inner() -> str:
        return helper()
    return "SELECT 2"
"""
    file = _write(tmp_path, "mod.py", source)
    index = build_project_index([file], source_roots=[tmp_path])
    graph = build_call_graph(index)
    outer_fqn = next(fqn for fqn in graph if fqn.endswith(".outer"))
    helper_fqn = next(fqn for fqn in graph if fqn.endswith(".helper"))
    # ``helper`` is only called from the nested ``inner`` function, so it
    # must not appear as a callee of ``outer``.
    assert helper_fqn not in graph[outer_fqn]
