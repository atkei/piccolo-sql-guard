from __future__ import annotations

from piccolo_sql_guard.analysis.provenance import (
    BOOL,
    EMPTY,
    LITERAL,
    LITERAL_TYPE,
    MODULE_CONSTANT,
    NUMERIC,
    SAFE_BUILDER,
    UNKNOWN,
    UNTYPED_STR,
    ProvenanceCategory,
    ProvenanceSet,
    join,
    make_provenance_set,
    provenance_of,
)


class TestProvenanceSet:
    def test_empty_is_not_safe(self) -> None:
        assert EMPTY.is_safe() is False

    def test_singleton_literal_is_safe(self) -> None:
        assert LITERAL.is_safe() is True

    def test_unknown_is_unsafe(self) -> None:
        assert UNKNOWN.is_safe() is False

    def test_untyped_str_is_unsafe(self) -> None:
        assert UNTYPED_STR.is_safe() is False

    def test_numeric_safe_when_allowed(self) -> None:
        assert NUMERIC.is_safe(allow_numeric=True) is True

    def test_numeric_unsafe_when_disallowed(self) -> None:
        assert NUMERIC.is_safe(allow_numeric=False) is False

    def test_safe_categories(self) -> None:
        for s in (LITERAL, LITERAL_TYPE, BOOL, MODULE_CONSTANT, SAFE_BUILDER):
            assert s.is_safe() is True

    def test_mixed_safe_and_unsafe_is_unsafe(self) -> None:
        mixed = LITERAL.join(UNKNOWN)
        assert mixed.is_safe() is False

    def test_join_is_union(self) -> None:
        result = LITERAL.join(BOOL)
        assert set(result) == {
            ProvenanceCategory.LITERAL,
            ProvenanceCategory.BOOL,
        }

    def test_join_idempotent(self) -> None:
        assert LITERAL.join(LITERAL) is LITERAL

    def test_join_commutative(self) -> None:
        assert LITERAL.join(BOOL) == BOOL.join(LITERAL)

    def test_join_associative(self) -> None:
        a, b, c = LITERAL, BOOL, NUMERIC
        assert a.join(b).join(c) == a.join(b.join(c))

    def test_join_with_empty_is_identity(self) -> None:
        assert LITERAL.join(EMPTY) == LITERAL
        assert EMPTY.join(LITERAL) == LITERAL

    def test_interning_returns_same_instance(self) -> None:
        a = provenance_of(ProvenanceCategory.LITERAL, ProvenanceCategory.BOOL)
        b = provenance_of(ProvenanceCategory.BOOL, ProvenanceCategory.LITERAL)
        assert a is b

    def test_make_provenance_set_accepts_set(self) -> None:
        s = make_provenance_set({ProvenanceCategory.LITERAL})
        assert s == LITERAL
        assert isinstance(s, ProvenanceSet)

    def test_make_provenance_set_accepts_frozenset(self) -> None:
        s = make_provenance_set(frozenset({ProvenanceCategory.BOOL}))
        assert s == BOOL

    def test_join_variadic(self) -> None:
        result = join(LITERAL, BOOL, NUMERIC)
        assert set(result) == {
            ProvenanceCategory.LITERAL,
            ProvenanceCategory.BOOL,
            ProvenanceCategory.NUMERIC,
        }

    def test_join_no_args_is_empty(self) -> None:
        assert join() == EMPTY
