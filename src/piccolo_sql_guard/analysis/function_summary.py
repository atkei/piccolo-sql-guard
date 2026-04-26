from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Literal

from piccolo_sql_guard.analysis.ast_parser import walk_no_nested_scopes
from piccolo_sql_guard.analysis.constant_store import (
    ConstantStore,
)
from piccolo_sql_guard.analysis.project_index import (
    ClassEntry,
    FunctionEntry,
    ProjectIndex,
)
from piccolo_sql_guard.analysis.provenance import (
    BOOL,
    EMPTY,
    LITERAL,
    UNKNOWN,
    ProvenanceCategory,
    ProvenanceSet,
    join,
    provenance_of,
)
from piccolo_sql_guard.analysis.type_annotations import parse_annotation

_SELF_PROV = provenance_of(ProvenanceCategory.MODULE_CONSTANT)


@dataclass(frozen=True)
class SinkLocation:
    """Lightweight source location used internally by token sinks."""

    line: int
    column: int
    end_line: int = 0
    end_column: int = 0


ProvEnv = dict[str, ProvenanceSet]


@dataclass(frozen=True)
class TokenSink:
    location: SinkLocation
    provenance: ProvenanceSet
    origin_expr: str


@dataclass(frozen=True)
class FunctionSummary:
    fqn: str
    parameter_provenance: dict[str, ProvenanceSet]
    return_provenance: ProvenanceSet
    token_sinks: tuple[TokenSink, ...]
    depends_on: frozenset[str]
    resolution: Literal["complete", "partial", "unresolved"]


def compute_summary(
    fn_entry: FunctionEntry,
    index: ProjectIndex,
    memo: dict[str, FunctionSummary] | None = None,
    *,
    class_entry: ClassEntry | None = None,
) -> FunctionSummary:
    """Compute a FunctionSummary for *fn_entry*.

    *memo* maps already-computed FQNs to their summaries (used by the M4
    call-graph driver).  When *memo* is None or missing a callee, that call
    resolves to UNKNOWN.
    """
    if memo is None:
        memo = {}

    fn = fn_entry.node
    module_fqn = fn_entry.module_fqn
    mod = index.get_module(module_fqn)
    mod_store = mod.constant_store if mod else ConstantStore()
    enum_classes = mod.enum_classes if mod else frozenset()

    # Parameter provenance from annotations
    param_prov = _extract_param_provenance(fn, enum_classes=enum_classes)

    # Build initial env from params + module constants
    env: ProvEnv = dict(param_prov)

    # Add self / cls as a synthetic safe reference
    if fn_entry.class_name is not None:
        env["self"] = _SELF_PROV
        env["cls"] = _SELF_PROV

    # Class attribute lookup table
    cls_store = class_entry.constant_store if class_entry else ConstantStore()

    # Collect depends_on FQNs as we encounter calls
    depends_on: set[str] = set()

    # Build one shared context so ast_env is populated before sink collection.
    ctx = _Ctx(
        mod_store,
        cls_store,
        enum_classes,
        index,
        memo,
        depends_on,
        fn_entry.fqn,
        fn_entry.module_fqn,
        fn_entry.class_name,
    )

    # Analyze the body flow-insensitively (also populates ctx.ast_env).
    _walk_stmts(fn.body, env, ctx)

    # Single AST walk: collect return provenance and token sinks together
    return_prov, sinks = _collect_returns(fn, env, ctx)

    # Determine resolution quality
    resolution: Literal["complete", "partial", "unresolved"] = "complete"
    if any(not s.provenance.is_safe() for s in sinks):
        resolution = "partial"

    return FunctionSummary(
        fqn=fn_entry.fqn,
        parameter_provenance=param_prov,
        return_provenance=return_prov,
        token_sinks=tuple(sinks),
        depends_on=frozenset(depends_on),
        resolution=resolution,
    )


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------


def _extract_param_provenance(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    enum_classes: frozenset[str],
) -> dict[str, ProvenanceSet]:
    result: dict[str, ProvenanceSet] = {}
    args = fn.args
    all_args = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    if args.vararg:
        all_args.append(args.vararg)
    if args.kwarg:
        all_args.append(args.kwarg)

    for arg in all_args:
        prov = parse_annotation(arg.annotation, enum_classes=enum_classes)
        # *args / **kwargs are always UNKNOWN (design doc §7.5)
        if arg is args.vararg or arg is args.kwarg:
            prov = UNKNOWN
        result[arg.arg] = prov

    return result


# ---------------------------------------------------------------------------
# Body analysis
# ---------------------------------------------------------------------------


@dataclass
class _Ctx:
    mod_store: ConstantStore
    cls_store: ConstantStore
    enum_classes: frozenset[str]
    index: ProjectIndex
    memo: dict[str, FunctionSummary]
    depends_on: set[str]
    current_fqn: str
    module_fqn: str
    class_name: str | None
    # name → original assigned AST expression; used by sink collection to trace
    # through intermediate variables (e.g. `sql = f"..."; return sql`).
    ast_env: dict[str, ast.expr] = field(default_factory=dict)


def _walk_stmts(stmts: list[ast.stmt], env: ProvEnv, ctx: _Ctx) -> None:
    for stmt in stmts:
        _walk_stmt(stmt, env, ctx)


def _walk_stmt(stmt: ast.stmt, env: ProvEnv, ctx: _Ctx) -> None:
    match stmt:
        case ast.Assign(targets=targets, value=value):
            prov = _expr_prov(value, env, ctx)
            for target in targets:
                if isinstance(target, ast.Name):
                    env[target.id] = env.get(target.id, EMPTY).join(prov)
                    ctx.ast_env[target.id] = value
                elif isinstance(target, ast.Tuple):
                    # Tuple unpacking → UNKNOWN for each name (design doc §8.5)
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            env[elt.id] = UNKNOWN

        case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
            prov = _expr_prov(value, env, ctx)
            env[name] = env.get(name, EMPTY).join(prov)
            ctx.ast_env[name] = value

        case ast.AugAssign(target=ast.Name(id=name), op=ast.Add(), value=value):
            prov = _expr_prov(value, env, ctx)
            env[name] = env.get(name, EMPTY).join(prov)
            # Build synthetic concat node so sink tracing can follow through +=
            prev_ast = ctx.ast_env.get(name)
            if prev_ast is not None:
                synthetic = ast.BinOp(left=prev_ast, op=ast.Add(), right=value)
                ast.copy_location(synthetic, value)
                ctx.ast_env[name] = synthetic
            else:
                ctx.ast_env[name] = value

        case ast.If(body=body, orelse=orelse):
            _walk_stmts(body, env, ctx)
            _walk_stmts(orelse, env, ctx)

        case ast.For(target=target, iter=iter_node, body=body, orelse=orelse):
            if isinstance(target, ast.Name):
                it_prov = _iter_element_prov(iter_node, env, ctx)
                env[target.id] = env.get(target.id, EMPTY).join(it_prov)
            _walk_stmts(body, env, ctx)
            _walk_stmts(orelse, env, ctx)

        case ast.With(body=body):
            _walk_stmts(body, env, ctx)

        case ast.AsyncWith(body=body):
            _walk_stmts(body, env, ctx)

        case ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=finalbody):
            _walk_stmts(body, env, ctx)
            for h in handlers:
                _walk_stmts(h.body, env, ctx)
            _walk_stmts(orelse, env, ctx)
            _walk_stmts(finalbody, env, ctx)

        case ast.Match(cases=cases):
            for case_node in cases:
                _walk_stmts(case_node.body, env, ctx)

        case ast.FunctionDef() | ast.AsyncFunctionDef():
            # Nested functions: don't descend, handled separately
            pass

        case ast.ClassDef():
            pass

        case _:
            # Expressions (ast.Expr), return, raise, etc. — no new bindings
            pass


def _iter_element_prov(iter_node: ast.expr, env: ProvEnv, ctx: _Ctx) -> ProvenanceSet:
    """Provenance of each element yielded by an iterable."""
    container_prov = _expr_prov(iter_node, env, ctx)
    # A list/tuple literal's element provenance is the join of all elements
    if isinstance(iter_node, (ast.List, ast.Tuple)):
        if not iter_node.elts:
            return LITERAL
        return join(*(_expr_prov(e, env, ctx) for e in iter_node.elts))
    # Otherwise, the container provenance approximates element provenance
    return container_prov


# ---------------------------------------------------------------------------
# Expression provenance
# ---------------------------------------------------------------------------


def _expr_prov(node: ast.expr, env: ProvEnv, ctx: _Ctx) -> ProvenanceSet:
    if isinstance(node, ast.Constant):
        return _constant_prov(node)

    if isinstance(node, ast.Name):
        local = env.get(node.id)
        if local is not None:
            return local
        # Try module-level constant
        mod_prov = ctx.mod_store.get(node.id)
        if mod_prov != UNKNOWN:
            return mod_prov
        return UNKNOWN

    if isinstance(node, ast.Attribute):
        return _attr_prov(node, env, ctx)

    if isinstance(node, ast.JoinedStr):
        return _fstring_prov(node, env, ctx)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _expr_prov(node.left, env, ctx).join(_expr_prov(node.right, env, ctx))

    if isinstance(node, ast.IfExp):
        return _expr_prov(node.body, env, ctx).join(_expr_prov(node.orelse, env, ctx))

    if isinstance(node, ast.Call):
        return _call_prov(node, env, ctx)

    if isinstance(node, ast.Subscript):
        return _subscript_prov(node, env, ctx)

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        if not node.elts:
            return LITERAL
        return join(*(_expr_prov(e, env, ctx) for e in node.elts))

    if isinstance(node, ast.NamedExpr):
        # Walrus operator :=
        prov = _expr_prov(node.value, env, ctx)
        if isinstance(node.target, ast.Name):
            env[node.target.id] = env.get(node.target.id, EMPTY).join(prov)
        return prov

    if isinstance(node, ast.BoolOp):
        return join(*(_expr_prov(v, env, ctx) for v in node.values))

    return UNKNOWN


def _constant_prov(node: ast.Constant) -> ProvenanceSet:
    value = node.value
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, (int, float)):
        return provenance_of(ProvenanceCategory.NUMERIC)
    if isinstance(value, str):
        return LITERAL
    if value is None:
        return UNKNOWN
    return UNKNOWN


def _attr_prov(node: ast.Attribute, env: ProvEnv, ctx: _Ctx) -> ProvenanceSet:
    if isinstance(node.value, ast.Name):
        obj_name = node.value.id
        if obj_name in ("self", "cls"):
            # Look up in class constant store first
            cls_prov = ctx.cls_store.get(node.attr)
            if cls_prov != UNKNOWN:
                return cls_prov
            return UNKNOWN
        # Module-level attribute access, e.g. MyEnum.VALUE
        obj_prov = env.get(obj_name) or ctx.mod_store.get(obj_name)
        if obj_prov and ProvenanceCategory.ENUM_VALUE in obj_prov:
            return obj_prov
        # Try class constant store for class attributes
        cls_prov = ctx.cls_store.get(obj_name)
        if cls_prov != UNKNOWN:
            return cls_prov
    return UNKNOWN


def _fstring_prov(node: ast.JoinedStr, env: ProvEnv, ctx: _Ctx) -> ProvenanceSet:
    result: ProvenanceSet = LITERAL
    for part in node.values:
        if isinstance(part, ast.FormattedValue):
            result = result.join(_expr_prov(part.value, env, ctx))
    return result


def _call_prov(node: ast.Call, env: ProvEnv, ctx: _Ctx) -> ProvenanceSet:
    # str.join(iterable) → provenance of iterable elements
    if isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        if node.args:
            return _expr_prov(node.args[0], env, ctx)
        return UNKNOWN

    # str() / int() / float() conversions on known provenance
    _SCALAR_BUILTINS = frozenset({"str", "int", "float", "bool"})
    if isinstance(node.func, ast.Name) and node.func.id in _SCALAR_BUILTINS:
        if node.args:
            return _expr_prov(node.args[0], env, ctx)
        return UNKNOWN

    # list() / tuple() / sorted() on known iterables
    _CONTAINER_BUILTINS = frozenset({"list", "tuple", "sorted", "frozenset"})
    if isinstance(node.func, ast.Name) and node.func.id in _CONTAINER_BUILTINS:
        if node.args:
            return _expr_prov(node.args[0], env, ctx)
        return UNKNOWN

    # Resolve call to a known summarized function (M4 cross-function)
    callee_fqn = _resolve_callee_fqn(node, env, ctx)
    if callee_fqn is not None:
        ctx.depends_on.add(callee_fqn)
        callee_summary = ctx.memo.get(callee_fqn)
        if callee_summary is not None:
            return callee_summary.return_provenance

    return UNKNOWN


def _resolve_callee_fqn(node: ast.Call, env: ProvEnv, ctx: _Ctx) -> str | None:
    """Try to resolve a Call node to a FQN string."""
    func = node.func
    if isinstance(func, ast.Name):
        binding = ctx.index.resolve_name(func.id, ctx.module_fqn)
        if binding is not None:
            return f"{binding.source_fqn}.{binding.original_name}"
        candidate = f"{ctx.module_fqn}.{func.id}"
        if ctx.index.get_function(candidate) is not None:
            return candidate
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        obj = func.value.id
        if obj in ("self", "cls") and ctx.class_name is not None:
            cls_fqn = f"{ctx.module_fqn}.{ctx.class_name}"
            return f"{cls_fqn}.{func.attr}"
    return None


def _subscript_prov(node: ast.Subscript, env: ProvEnv, ctx: _Ctx) -> ProvenanceSet:
    # dict/list subscript on local variable
    if isinstance(node.value, ast.Name):
        name = node.value.id
        # Try local env as module constant
        raw_prov = env.get(name) or ctx.mod_store.get(name)
        # Try subscript resolution from module constant store
        key_prov = _expr_prov(node.slice, env, ctx)
        mod_result = ctx.mod_store.resolve_subscript(name, key_prov, node.slice)
        if mod_result != UNKNOWN:
            return mod_result
        if raw_prov is not None and raw_prov != UNKNOWN:
            return raw_prov
    return UNKNOWN


# ---------------------------------------------------------------------------
# Return provenance + token sink collection (single AST walk)
# ---------------------------------------------------------------------------


def _collect_returns(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    env: ProvEnv,
    ctx: _Ctx,
) -> tuple[ProvenanceSet, list[TokenSink]]:
    """Walk *fn*'s own return statements (excluding nested function bodies).

    Returns in nested ``def``/``class`` belong to their own analytical scope
    and must not be attributed to the enclosing function.
    """
    return_prov = EMPTY
    sinks: list[TokenSink] = []
    for node in walk_no_nested_scopes(fn):
        if isinstance(node, ast.Return) and node.value is not None:
            return_prov = return_prov.join(_expr_prov(node.value, env, ctx))
            _collect_sinks_from_expr(node.value, env, ctx, sinks, frozenset())
    return (return_prov if return_prov != EMPTY else UNKNOWN), sinks


def _collect_sinks_from_expr(
    node: ast.expr,
    env: ProvEnv,
    ctx: _Ctx,
    sinks: list[TokenSink],
    _visited: frozenset[str] = frozenset(),
) -> None:
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                prov = _expr_prov(part.value, env, ctx)
                loc = _sink_location(part)
                try:
                    expr_repr = ast.unparse(part.value)
                except Exception:
                    expr_repr = "<unparseable>"
                sinks.append(
                    TokenSink(location=loc, provenance=prov, origin_expr=expr_repr)
                )

    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left_is_str = _could_be_string(node.left, env, ctx)
        right_is_str = _could_be_string(node.right, env, ctx)
        if left_is_str or right_is_str:
            _collect_sinks_from_expr(node.left, env, ctx, sinks, _visited)
            _collect_sinks_from_expr(node.right, env, ctx, sinks, _visited)

    elif isinstance(node, ast.Name):
        if node.id not in _visited:
            orig = ctx.ast_env.get(node.id)
            if orig is not None:
                # Trace through the original assigned expression.
                _collect_sinks_from_expr(orig, env, ctx, sinks, _visited | {node.id})
            else:
                # Parameter or unannotated var with no assigned expression.
                # Record as a sink when provenance is definitively unsafe
                # (UNTYPED_STR / ENUM-tainted / etc.) but skip bare UNKNOWN to
                # avoid false positives on completely unannotated functions.
                prov = _expr_prov(node, env, ctx)
                if not prov.is_safe() and ProvenanceCategory.UNKNOWN not in prov:
                    loc = _sink_location(node)
                    try:
                        expr_repr = ast.unparse(node)
                    except Exception:
                        expr_repr = "<unparseable>"
                    sinks.append(
                        TokenSink(location=loc, provenance=prov, origin_expr=expr_repr)
                    )

    elif isinstance(node, ast.IfExp):
        _collect_sinks_from_expr(node.body, env, ctx, sinks, _visited)
        _collect_sinks_from_expr(node.orelse, env, ctx, sinks, _visited)

    elif isinstance(node, ast.Call):
        if _is_join_call(node) and node.args:
            _collect_sinks_from_join_arg(node.args[0], env, ctx, sinks, _visited)

        callee_fqn = _resolve_callee_fqn(node, env, ctx)
        if callee_fqn and callee_fqn in ctx.memo:
            callee_summary = ctx.memo[callee_fqn]
            sinks.extend(callee_summary.token_sinks)


def _is_join_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == "join"


def _collect_sinks_from_join_arg(
    node: ast.expr,
    env: ProvEnv,
    ctx: _Ctx,
    sinks: list[TokenSink],
    visited: frozenset[str],
) -> None:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for elt in node.elts:
            _collect_sinks_from_expr(elt, env, ctx, sinks, visited)
        return

    _collect_sinks_from_expr(node, env, ctx, sinks, visited)


def _sink_location(node: ast.AST) -> SinkLocation:
    line = getattr(node, "lineno", 0) or 0
    column = getattr(node, "col_offset", 0) or 0
    end_line = getattr(node, "end_lineno", None) or line
    end_column = getattr(node, "end_col_offset", None)
    if end_column is None:
        end_column = column
    return SinkLocation(
        line=line, column=column, end_line=end_line, end_column=end_column
    )


def _could_be_string(node: ast.expr, env: ProvEnv, ctx: _Ctx) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.Name):
        prov = _expr_prov(node, env, ctx)
        return (
            ProvenanceCategory.LITERAL in prov or ProvenanceCategory.UNTYPED_STR in prov
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _could_be_string(node.left, env, ctx)
    return False
