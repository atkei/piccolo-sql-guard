from __future__ import annotations

import ast
import fnmatch

from piccolo_sql_guard.models import SqlClassification


def is_all_literal(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return is_all_literal(expr.left) and is_all_literal(expr.right)
    return False


def classify_expr(
    expr: ast.expr,
    builder_allowlist: set[str] | None = None,
) -> SqlClassification:
    if builder_allowlist is None:
        builder_allowlist = set()

    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return SqlClassification.SAFE_LITERAL

    if isinstance(expr, ast.JoinedStr):
        return SqlClassification.UNSAFE_FSTRING

    if isinstance(expr, ast.BinOp):
        if isinstance(expr.op, ast.Add):
            if is_all_literal(expr):
                return SqlClassification.SAFE_LITERAL
            return SqlClassification.UNSAFE_CONCAT
        if isinstance(expr.op, ast.Mod) and _looks_like_string(expr.left):
            return SqlClassification.UNSAFE_PERCENT_FORMAT

    if isinstance(expr, ast.Call):
        if (
            isinstance(expr.func, ast.Attribute)
            and expr.func.attr == "format"
            and _looks_like_string(expr.func.value)
        ):
            return SqlClassification.UNSAFE_DOT_FORMAT
        func_name = _get_call_name(expr)
        if func_name and _matches_allowlist(func_name, builder_allowlist):
            return SqlClassification.SAFE_BUILDER_CALL

    return SqlClassification.UNKNOWN_DYNAMIC


def _looks_like_string(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return True
    if isinstance(expr, ast.JoinedStr):
        return True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _looks_like_string(expr.left) or _looks_like_string(expr.right)
    return False


def _get_call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _matches_allowlist(name: str, allowlist: set[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in allowlist)
