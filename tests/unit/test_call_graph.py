from __future__ import annotations

from pathlib import Path

from piccolo_sql_guard.analysis.call_graph import (
    build_call_graph,
    compute_all_summaries,
    tarjan_sccs,
)
from piccolo_sql_guard.analysis.project_index import build_project_index
from piccolo_sql_guard.analysis.provenance import (
    LITERAL,
    ProvenanceCategory,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content)
    return f


# ---------------------------------------------------------------------------
# build_call_graph
# ---------------------------------------------------------------------------


class TestBuildCallGraph:
    def test_detects_callee_edge(self, tmp_path: Path) -> None:
        src = """\
def helper() -> str:
    return "FROM t"

def build() -> str:
    return "SELECT * " + helper()
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        graph = build_call_graph(idx)
        build_fqn = next(k for k in graph if "build" in k and "helper" not in k)
        helper_fqn = next(k for k in graph if "helper" in k)
        assert helper_fqn in graph[build_fqn]

    def test_leaf_has_empty_callees(self, tmp_path: Path) -> None:
        src = """\
def leaf() -> str:
    return "SELECT 1"
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        graph = build_call_graph(idx)
        fqn = next(iter(graph))
        assert graph[fqn] == frozenset()

    def test_self_loop_detected(self, tmp_path: Path) -> None:
        src = """\
def recurse(n: int) -> str:
    if n == 0:
        return "done"
    return recurse(n - 1)
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        graph = build_call_graph(idx)
        fqn = next(iter(graph))
        assert fqn in graph[fqn]

    def test_no_cross_module_false_positive(self, tmp_path: Path) -> None:
        src = """\
import os

def build() -> str:
    return os.getcwd()
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        graph = build_call_graph(idx)
        fqn = next(iter(graph))
        # os.getcwd is not in the index, so no edges expected
        assert graph[fqn] == frozenset()


# ---------------------------------------------------------------------------
# tarjan_sccs
# ---------------------------------------------------------------------------


class TestTarjanSccs:
    def test_single_node(self) -> None:
        graph: dict[str, frozenset[str]] = {"A": frozenset()}
        sccs = tarjan_sccs(graph)
        assert sccs == [["A"]]

    def test_acyclic_chain(self) -> None:
        graph: dict[str, frozenset[str]] = {
            "A": frozenset(["B"]),
            "B": frozenset(["C"]),
            "C": frozenset(),
        }
        sccs = tarjan_sccs(graph)
        assert [s[0] for s in sccs] == ["C", "B", "A"]

    def test_self_loop(self) -> None:
        graph: dict[str, frozenset[str]] = {"A": frozenset(["A"])}
        sccs = tarjan_sccs(graph)
        assert len(sccs) == 1
        assert sccs[0] == ["A"]

    def test_mutual_recursion_same_scc(self) -> None:
        graph: dict[str, frozenset[str]] = {
            "A": frozenset(["B"]),
            "B": frozenset(["A"]),
        }
        sccs = tarjan_sccs(graph)
        assert len(sccs) == 1
        assert set(sccs[0]) == {"A", "B"}

    def test_diamond(self) -> None:
        graph: dict[str, frozenset[str]] = {
            "A": frozenset(["B", "C"]),
            "B": frozenset(["D"]),
            "C": frozenset(["D"]),
            "D": frozenset(),
        }
        sccs = tarjan_sccs(graph)
        # D must appear before B and C; B and C before A
        fqns = [s[0] for s in sccs]
        assert fqns.index("D") < fqns.index("A")
        assert fqns.index("B") < fqns.index("A")
        assert fqns.index("C") < fqns.index("A")

    def test_all_nodes_covered(self) -> None:
        graph: dict[str, frozenset[str]] = {
            "A": frozenset(["B"]),
            "B": frozenset(["C"]),
            "C": frozenset(),
        }
        sccs = tarjan_sccs(graph)
        all_nodes = {n for scc in sccs for n in scc}
        assert all_nodes == {"A", "B", "C"}


# ---------------------------------------------------------------------------
# compute_all_summaries — cross-function resolution
# ---------------------------------------------------------------------------


class TestComputeAllSummaries:
    def test_all_functions_covered(self, tmp_path: Path) -> None:
        src = """\
def a() -> str:
    return "a"

def b() -> str:
    return "b"
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        summaries = compute_all_summaries(idx)
        assert len(summaries) == 2

    def test_cross_function_callee_literal_propagates(self, tmp_path: Path) -> None:
        src = """\
def helper() -> str:
    return "FROM t"

def build() -> str:
    return "SELECT * " + helper()
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        summaries = compute_all_summaries(idx)
        build_fqn = next(k for k in summaries if "build" in k and "helper" not in k)
        assert summaries[build_fqn].return_provenance == LITERAL

    def test_cross_function_unsafe_propagates(self, tmp_path: Path) -> None:
        src = """\
def helper(table: str) -> str:
    return f"FROM {table}"

def build(table: str) -> str:
    return "SELECT * " + helper(table)
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        summaries = compute_all_summaries(idx)
        build_fqn = next(k for k in summaries if "build" in k and "helper" not in k)
        assert not summaries[build_fqn].return_provenance.is_safe()

    def test_safe_builder_end_to_end(self, tmp_path: Path) -> None:
        src = """\
from typing import Literal

_FROM_USER = "FROM projects JOIN users"
_FROM_WORKSPACE = "FROM projects"

def _get_from(scope: Literal["user", "workspace"]) -> str:
    return _FROM_WORKSPACE if scope == "workspace" else _FROM_USER

def build(scope: Literal["user", "workspace"]) -> str:
    return "SELECT * " + _get_from(scope)
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        summaries = compute_all_summaries(idx)
        build_fqn = next(k for k in summaries if "build" in k and "_get" not in k)
        s = summaries[build_fqn]
        assert s.return_provenance.is_safe()
        assert s.resolution == "complete"

    def test_self_recursive_converges(self, tmp_path: Path) -> None:
        src = """\
def recurse(n: int) -> str:
    if n == 0:
        return "done"
    return recurse(n - 1)
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        summaries = compute_all_summaries(idx)
        assert len(summaries) == 1
        # Should terminate without error; return prov includes LITERAL
        fqn = next(iter(summaries))
        assert ProvenanceCategory.LITERAL in summaries[fqn].return_provenance

    def test_mutual_recursion_converges(self, tmp_path: Path) -> None:
        src = """\
def even(n: int) -> str:
    if n == 0:
        return "even"
    return odd(n - 1)

def odd(n: int) -> str:
    if n == 0:
        return "odd"
    return even(n - 1)
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        summaries = compute_all_summaries(idx)
        assert len(summaries) == 2
        for s in summaries.values():
            assert ProvenanceCategory.LITERAL in s.return_provenance

    def test_chain_of_three_resolves(self, tmp_path: Path) -> None:
        src = """\
def a() -> str:
    return "SELECT"

def b() -> str:
    return a() + " *"

def c() -> str:
    return b() + " FROM t"
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        summaries = compute_all_summaries(idx)
        c_fqn = next(k for k in summaries if k.endswith(".c"))
        assert summaries[c_fqn].return_provenance == LITERAL
