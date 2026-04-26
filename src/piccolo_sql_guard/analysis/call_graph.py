from __future__ import annotations

import ast
from collections.abc import Iterator

from piccolo_sql_guard.analysis.ast_parser import walk_no_nested_scopes
from piccolo_sql_guard.analysis.function_summary import (
    FunctionSummary,
    compute_summary,
)
from piccolo_sql_guard.analysis.project_index import (
    ClassEntry,
    FunctionEntry,
    ProjectIndex,
)

_DEFAULT_MAX_ITERATIONS = 5


# ---------------------------------------------------------------------------
# Call graph construction
# ---------------------------------------------------------------------------


def _resolve_call_fqn(
    node: ast.Call,
    fn_entry: FunctionEntry,
    index: ProjectIndex,
) -> str | None:
    """Resolve a Call node to a callee FQN using lightweight heuristics.

    Uses ``fn_entry.module_fqn`` directly so method FQNs (mod.Class.method)
    correctly resolve imports and same-module functions.
    """
    func = node.func
    module_fqn = fn_entry.module_fqn

    if isinstance(func, ast.Name):
        binding = index.resolve_name(func.id, module_fqn)
        if binding is not None:
            return f"{binding.source_fqn}.{binding.original_name}"
        candidate = f"{module_fqn}.{func.id}"
        if index.get_function(candidate) is not None:
            return candidate

    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        obj = func.value.id
        if obj in ("self", "cls") and fn_entry.class_name is not None:
            cls_fqn = f"{module_fqn}.{fn_entry.class_name}"
            return f"{cls_fqn}.{func.attr}"

    return None


def _collect_callees(fn_entry: FunctionEntry, index: ProjectIndex) -> frozenset[str]:
    """Return the set of callee FQNs reachable from *fn_entry*'s own AST.

    Nested function/class bodies belong to their own scope and are not
    attributed to the enclosing function.
    """
    callees: set[str] = set()
    for node in walk_no_nested_scopes(fn_entry.node):
        if not isinstance(node, ast.Call):
            continue
        fqn = _resolve_call_fqn(node, fn_entry, index)
        if fqn is not None and index.has_function(fqn):
            callees.add(fqn)
    return frozenset(callees)


def _collect_callees_cached(
    fqn: str,
    fn_entry: FunctionEntry,
    index: ProjectIndex,
    cache: dict[str, frozenset[str]],
) -> frozenset[str]:
    cached = cache.get(fqn)
    if cached is not None:
        return cached
    callees = _collect_callees(fn_entry, index)
    cache[fqn] = callees
    return callees


def build_call_graph(index: ProjectIndex) -> dict[str, frozenset[str]]:
    """Build a directed call graph: FQN → frozenset of callee FQNs."""
    direct_cache: dict[str, frozenset[str]] = {}
    return {
        fqn: _collect_callees_cached(fqn, fn_entry, index, direct_cache)
        for fqn, fn_entry in index.iter_function_items()
    }


def build_reachable_call_graph(
    index: ProjectIndex,
    seed_fqns: set[str],
) -> dict[str, frozenset[str]]:
    """Build a call graph restricted to the transitive closure of *seed_fqns*."""
    graph: dict[str, frozenset[str]] = {}
    direct_cache: dict[str, frozenset[str]] = {}
    worklist = list(sorted(seed_fqns, reverse=True))

    while worklist:
        fqn = worklist.pop()
        if fqn in graph:
            continue
        fn_entry = index.get_function(fqn)
        if fn_entry is None:
            continue

        callees = _collect_callees_cached(fqn, fn_entry, index, direct_cache)
        graph[fqn] = callees
        for callee in sorted(callees, reverse=True):
            if callee not in graph:
                worklist.append(callee)

    return graph


# ---------------------------------------------------------------------------
# Tarjan's SCC algorithm (iterative)
# ---------------------------------------------------------------------------


def tarjan_sccs(graph: dict[str, frozenset[str]]) -> list[list[str]]:
    """Compute SCCs in topological order (callees before callers).

    Uses an iterative implementation of Tarjan's algorithm to avoid
    hitting Python's recursion limit on large call graphs.
    """
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    sccs: list[list[str]] = []

    def _visit(v: str) -> tuple[str, Iterator[str]]:
        indices[v] = lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        return v, iter(graph.get(v, frozenset()))

    work: list[tuple[str, Iterator[str]]] = []

    for root in graph:
        if root in indices:
            continue
        work.append(_visit(root))
        while work:
            v, neighbors = work[-1]
            try:
                w = next(neighbors)
                if w not in graph:
                    continue
                if w not in indices:
                    work.append(_visit(w))
                elif w in on_stack:
                    lowlinks[v] = min(lowlinks[v], indices[w])
            except StopIteration:
                work.pop()
                if work:
                    parent, _ = work[-1]
                    lowlinks[parent] = min(lowlinks[parent], lowlinks[v])
                if lowlinks[v] == indices[v]:
                    scc: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == v:
                            break
                    sccs.append(scc)

    # Tarjan's emits SCCs in reverse topological order of the condensation DAG:
    # callees are emitted before callers, which is exactly the processing order
    # we need — no reversal required.
    return sccs


# ---------------------------------------------------------------------------
# Fixed-point driver
# ---------------------------------------------------------------------------


def _find_class_entry(
    fn_entry: FunctionEntry, index: ProjectIndex
) -> ClassEntry | None:
    if fn_entry.class_name is None:
        return None
    cls_fqn = f"{fn_entry.module_fqn}.{fn_entry.class_name}"
    return index.get_class(cls_fqn)


def _compute_scc_fixed_point(
    scc: list[str],
    index: ProjectIndex,
    memo: dict[str, FunctionSummary],
    max_iterations: int,
) -> None:
    """Iterate summary computation for a recursive SCC until fixed point."""
    for _ in range(max_iterations):
        changed = False
        for fqn in scc:
            fn_entry = index.get_function(fqn)
            if fn_entry is None:
                continue
            cls_entry = _find_class_entry(fn_entry, index)
            new_summary = compute_summary(fn_entry, index, memo, class_entry=cls_entry)
            old = memo.get(fqn)
            if old is None or old.return_provenance != new_summary.return_provenance:
                changed = True
            memo[fqn] = new_summary
        if not changed:
            break


def compute_summaries_for_graph(
    index: ProjectIndex,
    graph: dict[str, frozenset[str]],
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> dict[str, FunctionSummary]:
    """Compute FunctionSummary for every function present in *graph*."""
    sccs = tarjan_sccs(graph)
    memo: dict[str, FunctionSummary] = {}

    for scc in sccs:
        has_self_loop = any(fqn in graph.get(fqn, frozenset()) for fqn in scc)
        is_recursive = len(scc) > 1 or has_self_loop

        if not is_recursive:
            fqn = scc[0]
            fn_entry = index.get_function(fqn)
            if fn_entry is not None:
                cls_entry = _find_class_entry(fn_entry, index)
                memo[fqn] = compute_summary(
                    fn_entry, index, memo, class_entry=cls_entry
                )
        else:
            _compute_scc_fixed_point(scc, index, memo, max_iterations)

    return memo


def compute_all_summaries(
    index: ProjectIndex,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> dict[str, FunctionSummary]:
    """Compute FunctionSummary for every function in *index*.

    Builds the call graph, detects SCCs, and processes them in dependency
    order (callees before callers).  Mutually recursive SCCs are iterated to a
    fixed point (up to *max_iterations* rounds).
    """
    graph = build_call_graph(index)
    return compute_summaries_for_graph(index, graph, max_iterations)

 

def compute_reachable_summaries(
    index: ProjectIndex,
    seed_fqns: set[str],
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> dict[str, FunctionSummary]:
    """Compute summaries only for functions reachable from *seed_fqns*."""
    graph = build_reachable_call_graph(index, seed_fqns)
    return compute_summaries_for_graph(index, graph, max_iterations)
