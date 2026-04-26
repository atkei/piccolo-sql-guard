import ast

from piccolo_sql_guard.analysis.sql_classification import classify_expr, is_all_literal
from piccolo_sql_guard.models import SqlClassification


def parse_expr(src: str) -> ast.expr:
    tree = ast.parse(src, mode="eval")
    return tree.body  # type: ignore[return-value]


def test_literal_string() -> None:
    expr = parse_expr('"SELECT * FROM foo"')
    assert classify_expr(expr) == SqlClassification.SAFE_LITERAL


def test_fstring() -> None:
    expr = parse_expr('f"SELECT {x}"')
    assert classify_expr(expr) == SqlClassification.UNSAFE_FSTRING


def test_concat_with_variable() -> None:
    expr = parse_expr('"SELECT * FROM " + table_name')
    assert classify_expr(expr) == SqlClassification.UNSAFE_CONCAT


def test_concat_all_literals_is_safe() -> None:
    expr = parse_expr('"SELECT " + "* FROM foo"')
    assert classify_expr(expr) == SqlClassification.SAFE_LITERAL


def test_percent_format() -> None:
    expr = parse_expr('"SELECT %s" % value')
    assert classify_expr(expr) == SqlClassification.UNSAFE_PERCENT_FORMAT


def test_dot_format() -> None:
    expr = parse_expr('"SELECT {}".format(value)')
    assert classify_expr(expr) == SqlClassification.UNSAFE_DOT_FORMAT


def test_unknown_call() -> None:
    expr = parse_expr("get_sql()")
    assert classify_expr(expr) == SqlClassification.UNKNOWN_DYNAMIC


def test_unknown_name() -> None:
    expr = parse_expr("sql_var")
    assert classify_expr(expr) == SqlClassification.UNKNOWN_DYNAMIC


def test_allowlisted_builder() -> None:
    expr = parse_expr("build_user_sql()")
    assert (
        classify_expr(expr, builder_allowlist={"build_*_sql"})
        == SqlClassification.SAFE_BUILDER_CALL
    )


def test_non_allowlisted_call() -> None:
    expr = parse_expr("build_user_sql()")
    assert classify_expr(expr) == SqlClassification.UNKNOWN_DYNAMIC


def test_is_all_literal_string() -> None:
    expr = parse_expr('"hello"')
    assert is_all_literal(expr)


def test_is_all_literal_concat() -> None:
    expr = parse_expr('"a" + "b"')
    assert is_all_literal(expr)


def test_is_all_literal_mixed() -> None:
    expr = parse_expr('"a" + variable')
    assert not is_all_literal(expr)
