from __future__ import annotations

import ast

from piccolo_sql_guard.analysis.constant_store import (
    build_class_constant_store,
    build_constant_store,
    expr_provenance,
)
from piccolo_sql_guard.analysis.provenance import (
    LITERAL,
    NUMERIC,
    UNKNOWN,
    ProvenanceCategory,
)


def _module(src: str) -> ast.Module:
    return ast.parse(src)


def _class_node(src: str, class_name: str = "C") -> ast.ClassDef:
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise ValueError(f"class {class_name!r} not found")


class TestBuildConstantStore:
    def test_string_literal(self) -> None:
        store = build_constant_store(_module('X = "hello"'))
        assert store.get("X") == LITERAL

    def test_int_literal(self) -> None:
        store = build_constant_store(_module("X = 42"))
        assert ProvenanceCategory.NUMERIC in store.get("X")

    def test_bool_literal(self) -> None:
        store = build_constant_store(_module("X = True"))
        assert ProvenanceCategory.BOOL in store.get("X")

    def test_unknown_for_function_call(self) -> None:
        store = build_constant_store(_module("X = some_func()"))
        assert store.get("X") == UNKNOWN

    def test_unknown_for_missing_name(self) -> None:
        store = build_constant_store(_module(""))
        assert store.get("NOPE") == UNKNOWN

    def test_string_concat(self) -> None:
        store = build_constant_store(_module('A = "foo"\nB = A + " bar"'))
        assert store.get("B") == LITERAL

    def test_fstring_all_literal(self) -> None:
        store = build_constant_store(_module('A = "x"\nB = f"col_{A}"'))
        assert store.get("B") == LITERAL

    def test_fstring_with_unknown(self) -> None:
        store = build_constant_store(_module('B = f"col_{some_var}"'))
        assert ProvenanceCategory.UNKNOWN in store.get("B")

    def test_dict_constant(self) -> None:
        store = build_constant_store(_module('D = {"a": "ASC", "b": "DESC"}'))
        prov = store.get("D")
        assert prov == LITERAL

    def test_list_constant(self) -> None:
        store = build_constant_store(_module('L = ["SELECT", "FROM"]'))
        assert store.get("L") == LITERAL

    def test_frozenset_call(self) -> None:
        store = build_constant_store(_module('F = frozenset(["a", "b"])'))
        assert store.get("F") == LITERAL

    def test_ternary_both_literal(self) -> None:
        store = build_constant_store(_module('X = "a" if cond else "b"'))
        assert store.get("X") == LITERAL

    def test_ternary_one_unknown(self) -> None:
        store = build_constant_store(_module('X = "a" if cond else some_var'))
        prov = store.get("X")
        assert ProvenanceCategory.UNKNOWN in prov

    def test_annotated_assignment(self) -> None:
        store = build_constant_store(_module('X: str = "hello"'))
        assert store.get("X") == LITERAL

    def test_literal_prov_for_empty_dict(self) -> None:
        # An empty literal container has no elements to be tainted by —
        # treat it as safe LITERAL rather than MODULE_CONSTANT.
        store = build_constant_store(_module("D = {}"))
        assert store.get("D") == LITERAL

    def test_join_prov_literal_is_literal(self) -> None:
        store = build_constant_store(_module('A = "x"\nB = "y"\nC = A + B'))
        assert store.get("C") == LITERAL


class TestSubscriptResolution:
    def test_dict_exact_key(self) -> None:
        store = build_constant_store(
            _module('D = {"asc": "ASC", "desc": "DESC"}\nV = D["asc"]')
        )
        assert store.get("V") == LITERAL

    def test_dict_missing_key(self) -> None:
        store = build_constant_store(_module('D = {"a": "X"}\nV = D["nope"]'))
        assert store.get("V") == UNKNOWN

    def test_dict_subscript_via_resolve_subscript(self) -> None:
        store = build_constant_store(_module('D = {"a": "X", "b": "Y"}'))
        key_prov = LITERAL
        key_node = ast.Constant(value="a")
        result = store.resolve_subscript("D", key_prov, key_node)
        assert result == LITERAL

    def test_list_subscript_by_index(self) -> None:
        store = build_constant_store(_module('L = ["SELECT", "FROM"]'))
        key_node = ast.Constant(value=0)
        result = store.resolve_subscript("L", NUMERIC, key_node)
        assert result == LITERAL

    def test_unknown_container(self) -> None:
        store = build_constant_store(_module(""))
        result = store.resolve_subscript("MISSING", LITERAL)
        assert result == UNKNOWN


class TestClassConstantStore:
    def test_class_string_attr(self) -> None:
        cls = _class_node('class C:\n    TABLE = "projects"\n')
        store = build_class_constant_store(cls)
        assert store.get("TABLE") == LITERAL

    def test_class_int_attr(self) -> None:
        cls = _class_node("class C:\n    LIMIT = 100\n")
        store = build_class_constant_store(cls)
        assert ProvenanceCategory.NUMERIC in store.get("LIMIT")

    def test_class_unknown_dynamic(self) -> None:
        cls = _class_node("class C:\n    X = compute()\n")
        store = build_class_constant_store(cls)
        assert store.get("X") == UNKNOWN

    def test_class_annotated_assignment(self) -> None:
        cls = _class_node('class C:\n    TABLE: str = "t"\n')
        store = build_class_constant_store(cls)
        assert store.get("TABLE") == LITERAL


class TestExprProvenance:
    def test_name_lookup(self) -> None:
        store = build_constant_store(_module('A = "x"'))
        node = ast.parse("A", mode="eval").body
        assert expr_provenance(node, store) == LITERAL

    def test_constant_str(self) -> None:
        store = build_constant_store(_module(""))
        node = ast.parse('"hello"', mode="eval").body
        assert expr_provenance(node, store) == LITERAL

    def test_constant_int(self) -> None:
        store = build_constant_store(_module(""))
        node = ast.parse("42", mode="eval").body
        prov = expr_provenance(node, store)
        assert ProvenanceCategory.NUMERIC in prov
