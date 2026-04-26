from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


class ParseError(Exception):
    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def parse_file(path: str | Path) -> ast.Module:
    path = Path(path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ParseError(str(path), f"cannot read file: {e}") from e

    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as e:
        raise ParseError(str(path), f"syntax error at line {e.lineno}: {e.msg}") from e


def is_type_checking_guard(node: ast.stmt) -> bool:
    """Return True if *node* is an ``if TYPE_CHECKING:`` guard."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def walk_no_nested_scopes(node: ast.AST) -> Iterator[ast.AST]:
    """Walk ``node`` like ``ast.walk`` but do not descend into nested function
    or class definitions.

    Yields ``node`` itself first. Nested ``FunctionDef`` / ``AsyncFunctionDef``
    / ``ClassDef`` bodies belong to their own analytical scope and must not
    contribute to the enclosing function's return provenance, callees, or
    symbol table.
    """
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield from walk_no_nested_scopes(child)
