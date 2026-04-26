from __future__ import annotations

import ast

from piccolo_sql_guard.analysis.provenance import (
    BOOL,
    NUMERIC,
    UNKNOWN,
    UNTYPED_STR,
    ProvenanceCategory,
    ProvenanceSet,
    join,
    make_provenance_set,
    provenance_of,
)

_LITERAL_NAMES: frozenset[str] = frozenset({"Literal", "typing.Literal"})
_OPTIONAL_NAMES: frozenset[str] = frozenset({"Optional", "typing.Optional"})
_UNION_NAMES: frozenset[str] = frozenset({"Union", "typing.Union"})
_BOOL_NAMES: frozenset[str] = frozenset({"bool"})
_INT_NAMES: frozenset[str] = frozenset({"int"})
_FLOAT_NAMES: frozenset[str] = frozenset({"float"})
_STR_NAMES: frozenset[str] = frozenset({"str"})


def parse_annotation(
    node: ast.expr | None,
    *,
    enum_classes: frozenset[str] = frozenset(),
) -> ProvenanceSet:
    """Derive a ``ProvenanceSet`` for a parameter/return annotation AST node.

    ``enum_classes`` is a set of in-project class names known to subclass
    ``enum.Enum``. Membership shortcuts to ``{ENUM_VALUE}``.
    """
    if node is None:
        return UNKNOWN

    if isinstance(node, ast.Constant) and node.value is None:
        # ``None`` annotation ⇒ value is only ever None. Not a safe token.
        return UNKNOWN

    if isinstance(node, ast.Name):
        return _primitive(node.id, enum_classes)

    if isinstance(node, ast.Attribute):
        name = _attribute_dotted(node)
        if name is None:
            return UNKNOWN
        if name in _BOOL_NAMES:
            return BOOL
        if name in _INT_NAMES or name in _FLOAT_NAMES:
            return NUMERIC
        if name in _STR_NAMES:
            return UNTYPED_STR
        tail = name.rsplit(".", 1)[-1]
        return _primitive(tail, enum_classes)

    if isinstance(node, ast.Subscript):
        return _parse_subscript(node, enum_classes=enum_classes)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return join(
            parse_annotation(node.left, enum_classes=enum_classes),
            parse_annotation(node.right, enum_classes=enum_classes),
        )

    return UNKNOWN


def _primitive(name: str, enum_classes: frozenset[str]) -> ProvenanceSet:
    if name in _BOOL_NAMES:
        return BOOL
    if name in _INT_NAMES or name in _FLOAT_NAMES:
        return NUMERIC
    if name in _STR_NAMES:
        return UNTYPED_STR
    if name in enum_classes:
        return provenance_of(ProvenanceCategory.ENUM_VALUE)
    return UNKNOWN


def _attribute_dotted(node: ast.Attribute) -> str | None:
    parts: list[str] = [node.attr]
    current: ast.expr = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _parse_subscript(
    node: ast.Subscript,
    *,
    enum_classes: frozenset[str],
) -> ProvenanceSet:
    base = _generic_name(node.value)
    if base is None:
        return UNKNOWN

    slice_node = node.slice

    if base in _LITERAL_NAMES:
        return _literal_values_provenance(slice_node)

    if base in _OPTIONAL_NAMES:
        # ``Optional[X]`` is treated as ``X`` for token-safety purposes.
        # Formatting ``None`` into SQL would be a semantic bug, but it is not
        # an injection vector; upgrading Optional to UNKNOWN would cause
        # false positives on ``Optional[Literal[...]]`` etc.
        return parse_annotation(slice_node, enum_classes=enum_classes)

    if base in _UNION_NAMES:
        if isinstance(slice_node, ast.Tuple):
            parts = [
                parse_annotation(e, enum_classes=enum_classes) for e in slice_node.elts
            ]
            return join(*parts)
        return parse_annotation(slice_node, enum_classes=enum_classes)

    return UNKNOWN


def _generic_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _attribute_dotted(node)
    return None


def _literal_values_provenance(slice_node: ast.expr) -> ProvenanceSet:
    values: list[ast.expr] = (
        list(slice_node.elts) if isinstance(slice_node, ast.Tuple) else [slice_node]
    )
    if not values:
        return UNKNOWN

    categories: set[ProvenanceCategory] = set()
    for v in values:
        cat = _literal_member_category(v)
        if cat is None:
            return UNKNOWN
        categories.add(cat)
    return make_provenance_set(categories)


def _literal_member_category(node: ast.expr) -> ProvenanceCategory | None:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return ProvenanceCategory.LITERAL_TYPE
        if isinstance(value, (int, float)):
            return ProvenanceCategory.NUMERIC
        if isinstance(value, str):
            return ProvenanceCategory.LITERAL_TYPE
        if value is None:
            return None
        return None
    if isinstance(node, ast.Attribute):
        # e.g. MyEnum.FOO — treat as enum literal
        return ProvenanceCategory.ENUM_VALUE
    return None
