from __future__ import annotations

from enum import StrEnum
from functools import lru_cache


class ProvenanceCategory(StrEnum):
    LITERAL = "literal"
    LITERAL_TYPE = "literal_type"
    BOOL = "bool"
    ENUM_VALUE = "enum_value"
    MODULE_CONSTANT = "module_constant"
    SAFE_BUILDER = "safe_builder"
    NUMERIC = "numeric"
    UNTYPED_STR = "untyped_str"
    UNKNOWN = "unknown"


_TOKEN_SAFE_CATEGORIES: frozenset[ProvenanceCategory] = frozenset(
    {
        ProvenanceCategory.LITERAL,
        ProvenanceCategory.LITERAL_TYPE,
        ProvenanceCategory.BOOL,
        ProvenanceCategory.ENUM_VALUE,
        ProvenanceCategory.MODULE_CONSTANT,
        ProvenanceCategory.SAFE_BUILDER,
    }
)


class ProvenanceSet(frozenset[ProvenanceCategory]):
    """Interned frozen set of provenance categories.

    Lattice element: the union of categories a value may originate from.
    ``join`` is set union; ``is_safe`` checks every element is token-safe.
    """

    __slots__ = ()

    def join(self, other: ProvenanceSet) -> ProvenanceSet:
        if not other:
            return self
        if not self:
            return other
        if self == other:
            return self
        return make_provenance_set(self | other)

    def is_safe(self, *, allow_numeric: bool = True) -> bool:
        if not self:
            return False
        safe = _TOKEN_SAFE_CATEGORIES
        for cat in self:
            if cat in safe:
                continue
            if cat is ProvenanceCategory.NUMERIC and allow_numeric:
                continue
            return False
        return True


@lru_cache(maxsize=1024)
def _intern(key: frozenset[ProvenanceCategory]) -> ProvenanceSet:
    return ProvenanceSet(key)


def make_provenance_set(
    categories: frozenset[ProvenanceCategory] | set[ProvenanceCategory] | ProvenanceSet,
) -> ProvenanceSet:
    if isinstance(categories, ProvenanceSet):
        return categories
    return _intern(frozenset(categories))


def provenance_of(*categories: ProvenanceCategory) -> ProvenanceSet:
    return _intern(frozenset(categories))


EMPTY: ProvenanceSet = _intern(frozenset())
UNKNOWN: ProvenanceSet = provenance_of(ProvenanceCategory.UNKNOWN)
LITERAL: ProvenanceSet = provenance_of(ProvenanceCategory.LITERAL)
LITERAL_TYPE: ProvenanceSet = provenance_of(ProvenanceCategory.LITERAL_TYPE)
BOOL: ProvenanceSet = provenance_of(ProvenanceCategory.BOOL)
ENUM_VALUE: ProvenanceSet = provenance_of(ProvenanceCategory.ENUM_VALUE)
MODULE_CONSTANT: ProvenanceSet = provenance_of(ProvenanceCategory.MODULE_CONSTANT)
SAFE_BUILDER: ProvenanceSet = provenance_of(ProvenanceCategory.SAFE_BUILDER)
NUMERIC: ProvenanceSet = provenance_of(ProvenanceCategory.NUMERIC)
UNTYPED_STR: ProvenanceSet = provenance_of(ProvenanceCategory.UNTYPED_STR)


def join(*sets: ProvenanceSet) -> ProvenanceSet:
    result = EMPTY
    for s in sets:
        result = result.join(s)
    return result
