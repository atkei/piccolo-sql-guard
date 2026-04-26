from __future__ import annotations

import ast

from piccolo_sql_guard.analysis.provenance import (
    BOOL,
    NUMERIC,
    UNKNOWN,
    UNTYPED_STR,
    ProvenanceCategory,
)
from piccolo_sql_guard.analysis.type_annotations import parse_annotation


def _annotation(source: str) -> ast.expr:
    module = ast.parse(f"x: {source}")
    stmt = module.body[0]
    assert isinstance(stmt, ast.AnnAssign)
    assert stmt.annotation is not None
    return stmt.annotation


class TestParseAnnotation:
    def test_none_node_is_unknown(self) -> None:
        assert parse_annotation(None) == UNKNOWN

    def test_bool(self) -> None:
        assert parse_annotation(_annotation("bool")) == BOOL

    def test_int_is_numeric(self) -> None:
        assert parse_annotation(_annotation("int")) == NUMERIC

    def test_float_is_numeric(self) -> None:
        assert parse_annotation(_annotation("float")) == NUMERIC

    def test_str_is_untyped(self) -> None:
        assert parse_annotation(_annotation("str")) == UNTYPED_STR

    def test_bytes_is_unknown(self) -> None:
        assert parse_annotation(_annotation("bytes")) == UNKNOWN

    def test_literal_str(self) -> None:
        prov = parse_annotation(_annotation('Literal["user", "workspace"]'))
        assert prov == frozenset({ProvenanceCategory.LITERAL_TYPE})

    def test_literal_int(self) -> None:
        prov = parse_annotation(_annotation("Literal[1, 2, 3]"))
        assert prov == frozenset({ProvenanceCategory.NUMERIC})

    def test_literal_mixed_str_int(self) -> None:
        prov = parse_annotation(_annotation('Literal["a", 1]'))
        assert prov == frozenset(
            {
                ProvenanceCategory.LITERAL_TYPE,
                ProvenanceCategory.NUMERIC,
            }
        )

    def test_literal_single_value(self) -> None:
        prov = parse_annotation(_annotation('Literal["only"]'))
        assert prov == frozenset({ProvenanceCategory.LITERAL_TYPE})

    def test_typing_literal_qualified(self) -> None:
        prov = parse_annotation(_annotation('typing.Literal["a"]'))
        assert prov == frozenset({ProvenanceCategory.LITERAL_TYPE})

    def test_optional_str(self) -> None:
        # ``Optional[X]`` is treated as ``X`` for token-safety purposes;
        # ``None`` flowing into SQL is a semantic bug, not an injection vector.
        prov = parse_annotation(_annotation("Optional[str]"))
        assert prov == frozenset({ProvenanceCategory.UNTYPED_STR})

    def test_optional_literal_stays_safe(self) -> None:
        prov = parse_annotation(_annotation('Optional[Literal["ASC", "DESC"]]'))
        assert prov == frozenset({ProvenanceCategory.LITERAL_TYPE})
        assert prov.is_safe()

    def test_union_pipe_syntax(self) -> None:
        prov = parse_annotation(_annotation("str | None"))
        # None annotation ⇒ UNKNOWN side; str ⇒ UNTYPED_STR
        assert ProvenanceCategory.UNTYPED_STR in prov
        assert ProvenanceCategory.UNKNOWN in prov

    def test_union_bracket_syntax(self) -> None:
        prov = parse_annotation(_annotation("Union[bool, int]"))
        assert prov == frozenset(
            {
                ProvenanceCategory.BOOL,
                ProvenanceCategory.NUMERIC,
            }
        )

    def test_literal_qualified_attribute_uses_tail(self) -> None:
        prov = parse_annotation(_annotation("typing.Literal[1]"))
        assert prov == frozenset({ProvenanceCategory.NUMERIC})

    def test_uuid_is_unknown(self) -> None:
        assert parse_annotation(_annotation("UUID")) == UNKNOWN

    def test_typevar_like_name_is_unknown(self) -> None:
        assert parse_annotation(_annotation("T")) == UNKNOWN

    def test_enum_class_is_enum_value(self) -> None:
        prov = parse_annotation(
            _annotation("MyEnum"),
            enum_classes=frozenset({"MyEnum"}),
        )
        assert prov == frozenset({ProvenanceCategory.ENUM_VALUE})

    def test_enum_class_not_known_is_unknown(self) -> None:
        assert parse_annotation(_annotation("MyEnum")) == UNKNOWN

    def test_literal_with_enum_member(self) -> None:
        prov = parse_annotation(_annotation("Literal[Color.RED, Color.BLUE]"))
        assert prov == frozenset({ProvenanceCategory.ENUM_VALUE})

    def test_literal_with_none_is_unknown(self) -> None:
        # Literal[None] is not a safe token — render would produce "None"
        assert parse_annotation(_annotation("Literal[None]")) == UNKNOWN

    def test_none_constant_annotation_is_unknown(self) -> None:
        # `x: None` case
        assert parse_annotation(_annotation("None")) == UNKNOWN

    def test_bool_pipe_literal(self) -> None:
        prov = parse_annotation(_annotation('bool | Literal["a"]'))
        assert prov == frozenset(
            {
                ProvenanceCategory.BOOL,
                ProvenanceCategory.LITERAL_TYPE,
            }
        )

    def test_unknown_subscript_form(self) -> None:
        # List[str] — generic we don't model
        assert parse_annotation(_annotation("List[str]")) == UNKNOWN
