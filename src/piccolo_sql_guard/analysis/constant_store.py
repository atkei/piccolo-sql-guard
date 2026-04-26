from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from piccolo_sql_guard.analysis.provenance import (
    LITERAL,
    MODULE_CONSTANT,
    UNKNOWN,
    ProvenanceCategory,
    ProvenanceSet,
    join,
    provenance_of,
)

_MAX_DICT_ELEMENTS = 512


@dataclass
class ConstantStore:
    """Module-level and class-level constant name → ProvenanceSet table.

    Only values that can be fully evaluated at analysis time are stored.
    Everything else is UNKNOWN.
    """

    _constants: dict[str, ProvenanceSet] = field(default_factory=dict)
    _raw: dict[
        str,
        dict[Any, ProvenanceSet] | list[ProvenanceSet] | tuple[ProvenanceSet, ...],
    ] = field(default_factory=dict)

    def get(self, name: str) -> ProvenanceSet:
        return self._constants.get(name, UNKNOWN)

    def set(self, name: str, prov: ProvenanceSet) -> None:
        self._constants[name] = prov

    def set_container(
        self,
        name: str,
        raw: dict[Any, ProvenanceSet] | list[ProvenanceSet] | tuple[ProvenanceSet, ...],
    ) -> None:
        self._raw[name] = raw

    def known_names(self) -> frozenset[str]:
        return frozenset(self._constants)

    def resolve_subscript(
        self,
        container_name: str,
        key_prov: ProvenanceSet,
        key_node: ast.expr | None = None,
    ) -> ProvenanceSet:
        """Resolve a subscript ``container_name[key]``.

        If the container is a known dict constant and the key is a literal or
        Literal-typed value, return the join of the matching values.
        Falls back to join-of-all-values when the key cannot be narrowed.
        """
        raw = self._raw.get(container_name)
        if raw is None:
            return UNKNOWN
        if not isinstance(raw, dict):
            if isinstance(raw, (list, tuple)) and key_node is not None:
                return self._resolve_seq_subscript(raw, key_node)
            return UNKNOWN
        if key_node is not None:
            exact = _eval_constant_key(key_node)
            if exact is not _MISSING:
                value_prov = raw.get(exact)
                return value_prov if value_prov is not None else UNKNOWN
        if ProvenanceCategory.LITERAL_TYPE in key_prov:
            return join(*raw.values()) if raw else UNKNOWN
        return join(*raw.values()) if raw else UNKNOWN

    def _resolve_seq_subscript(
        self,
        seq: list[ProvenanceSet] | tuple[ProvenanceSet, ...],
        key_node: ast.expr,
    ) -> ProvenanceSet:
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, int):
            idx = key_node.value
            try:
                return seq[idx]
            except IndexError:
                return UNKNOWN
        return join(*seq) if seq else UNKNOWN


_MISSING = object()


def _eval_constant_key(node: ast.expr) -> object:
    """Return the Python value of a constant key, or _MISSING."""
    if isinstance(node, ast.Constant):
        return node.value
    return _MISSING


def build_constant_store(tree: ast.Module) -> ConstantStore:
    """Walk a module AST and populate a ConstantStore for top-level assignments."""
    store = ConstantStore()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _process_assignment(store, target.id, node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                _process_assignment(store, node.target.id, node.value)
    return store


def build_class_constant_store(class_def: ast.ClassDef) -> ConstantStore:
    """Walk a ClassDef body and return a ConstantStore for class-level names."""
    store = ConstantStore()
    for node in class_def.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _process_assignment(store, target.id, node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                _process_assignment(store, node.target.id, node.value)
    return store


def expr_provenance(node: ast.expr, store: ConstantStore) -> ProvenanceSet:
    """Determine the ProvenanceSet for a single expression in module/class scope."""
    return _prov(node, store)


def _process_assignment(store: ConstantStore, name: str, value: ast.expr) -> None:
    prov = _prov(value, store)
    store.set(name, prov)
    raw = _eval_raw(value, store)
    if raw is not _MISSING:
        store.set_container(name, raw)  # type: ignore[arg-type]


def _prov(node: ast.expr, store: ConstantStore) -> ProvenanceSet:
    if isinstance(node, ast.Constant):
        return _constant_prov(node)

    if isinstance(node, ast.Name):
        return store.get(node.id)

    if isinstance(node, ast.JoinedStr):
        return _fstring_prov(node, store)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _prov(node.left, store).join(_prov(node.right, store))

    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        if not node.elts:
            return LITERAL
        return join(*(_prov(e, store) for e in node.elts))

    if isinstance(node, ast.Dict):
        if not node.keys:
            return LITERAL
        if len(node.keys) > _MAX_DICT_ELEMENTS:
            return UNKNOWN
        parts: list[ProvenanceSet] = []
        for k, v in zip(node.keys, node.values):
            if k is None:
                return UNKNOWN
            parts.append(_prov(k, store))
            parts.append(_prov(v, store))
        return join(*parts)

    if isinstance(node, ast.Call):
        return _call_prov(node, store)

    if isinstance(node, ast.IfExp):
        return _prov(node.body, store).join(_prov(node.orelse, store))

    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Name):
            key_prov = _prov(node.slice, store)
            return store.resolve_subscript(node.value.id, key_prov, node.slice)
        return UNKNOWN

    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name):
            container = store.get(node.value.id)
            if container != UNKNOWN:
                return container
        return UNKNOWN

    return UNKNOWN


def _constant_prov(node: ast.Constant) -> ProvenanceSet:
    value = node.value
    if isinstance(value, bool):
        return provenance_of(ProvenanceCategory.BOOL)
    if isinstance(value, (int, float)):
        return provenance_of(ProvenanceCategory.NUMERIC)
    if isinstance(value, str):
        return LITERAL
    return MODULE_CONSTANT


def _fstring_prov(node: ast.JoinedStr, store: ConstantStore) -> ProvenanceSet:
    result: ProvenanceSet = LITERAL
    for part in node.values:
        if isinstance(part, ast.FormattedValue):
            result = result.join(_prov(part.value, store))
        # ast.Constant string parts in a JoinedStr are fine literals
    return result


_PURE_CALLABLES = frozenset(
    {
        "frozenset",
        "tuple",
        "dict",
        "list",
        "set",
        "str",
        "int",
        "float",
    }
)


def _call_prov(node: ast.Call, store: ConstantStore) -> ProvenanceSet:
    if isinstance(node.func, ast.Name) and node.func.id in _PURE_CALLABLES:
        if not node.args and not node.keywords:
            return MODULE_CONSTANT
        parts = [_prov(a, store) for a in node.args]
        return join(*parts) if parts else MODULE_CONSTANT
    if isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        if node.args and len(node.args) == 1:
            arg_prov = _prov(node.args[0], store)
            return arg_prov
    return UNKNOWN


def _eval_raw(
    node: ast.expr,
    store: ConstantStore,
) -> (
    dict[Any, ProvenanceSet] | list[ProvenanceSet] | tuple[ProvenanceSet, ...] | object
):
    """Return the 'raw' structured form of a constant, used for subscript resolution."""
    if isinstance(node, ast.Dict):
        if len(node.keys) > _MAX_DICT_ELEMENTS:
            return _MISSING
        result: dict[Any, ProvenanceSet] = {}
        for k, v in zip(node.keys, node.values):
            if k is None:
                return _MISSING
            key = _eval_constant_key(k)
            if key is _MISSING:
                return _MISSING
            result[key] = _prov(v, store)
        return result
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_prov(e, store) for e in node.elts]
    return _MISSING
