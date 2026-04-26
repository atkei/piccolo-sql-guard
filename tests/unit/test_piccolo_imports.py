import ast

from piccolo_sql_guard.analysis.piccolo_imports import build_piccolo_scope


def parse(src: str) -> ast.Module:
    return ast.parse(src)


def test_detects_table_import() -> None:
    tree = parse("from piccolo.table import Table")
    scope = build_piccolo_scope(tree)
    assert "Table" in scope.table_names
    assert scope.has_piccolo_imports()


def test_detects_querystring_import() -> None:
    tree = parse("from piccolo.querystring import QueryString")
    scope = build_piccolo_scope(tree)
    assert "QueryString" in scope.querystring_names
    assert scope.has_piccolo_imports()


def test_detects_table_alias() -> None:
    tree = parse("from piccolo.table import Table as T")
    scope = build_piccolo_scope(tree)
    assert "T" in scope.table_names
    assert "Table" not in scope.table_names


def test_detects_querystring_alias() -> None:
    tree = parse("from piccolo.querystring import QueryString as QS")
    scope = build_piccolo_scope(tree)
    assert "QS" in scope.querystring_names
    assert "QueryString" not in scope.querystring_names


def test_detects_table_subclass() -> None:
    tree = parse("from piccolo.table import Table\n\nclass MyModel(Table):\n    pass")
    scope = build_piccolo_scope(tree)
    assert "MyModel" in scope.table_subclasses


def test_detects_aliased_table_subclass() -> None:
    tree = parse("from piccolo.table import Table as T\n\nclass Foo(T):\n    pass")
    scope = build_piccolo_scope(tree)
    assert "Foo" in scope.table_subclasses


def test_non_piccolo_class_not_in_subclasses() -> None:
    tree = parse("from piccolo.table import Table\n\nclass Foo(dict):\n    pass")
    scope = build_piccolo_scope(tree)
    assert "Foo" not in scope.table_subclasses


def test_no_piccolo_imports() -> None:
    tree = parse("import os")
    scope = build_piccolo_scope(tree)
    assert not scope.has_piccolo_imports()


def test_non_piccolo_import_skipped() -> None:
    tree = parse("from django.db import models")
    scope = build_piccolo_scope(tree)
    assert not scope.has_piccolo_imports()


def test_custom_piccolo_modules() -> None:
    tree = parse("from mypkg.models import Table")
    scope = build_piccolo_scope(tree, piccolo_modules=["mypkg.models"])
    assert "Table" in scope.table_names
