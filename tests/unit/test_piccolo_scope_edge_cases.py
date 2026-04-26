"""Regression tests for piccolo_imports scope construction."""

from __future__ import annotations

import ast

from piccolo_sql_guard.analysis.piccolo_imports import build_piccolo_scope


def _scope(src: str):
    return build_piccolo_scope(ast.parse(src))


def test_type_checking_import_does_not_activate_scope() -> None:
    src = """
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from piccolo import Table
"""
    scope = _scope(src)
    assert not scope.has_piccolo_imports()


def test_attribute_base_from_unrelated_module_is_not_a_table_subclass() -> None:
    # ``othermod`` is not a Piccolo module; ``othermod.Table`` must not
    # promote ``Bogus`` into ``table_subclasses``.
    src = """
import othermod
class Bogus(othermod.Table):
    pass
"""
    scope = _scope(src)
    assert "Bogus" not in scope.table_subclasses


def test_attribute_base_via_piccolo_alias_is_a_table_subclass() -> None:
    src = """
import piccolo
class Real(piccolo.Table):
    pass
"""
    scope = _scope(src)
    assert "Real" in scope.table_subclasses


def test_from_import_table_still_matches_bare_name_base() -> None:
    src = """
from piccolo import Table
class Real(Table):
    pass
"""
    scope = _scope(src)
    assert "Real" in scope.table_subclasses
