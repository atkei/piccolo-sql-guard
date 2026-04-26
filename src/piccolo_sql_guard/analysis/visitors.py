from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal

from piccolo_sql_guard.analysis.piccolo_imports import PiccoloScope
from piccolo_sql_guard.analysis.sql_classification import classify_expr
from piccolo_sql_guard.analysis.symbol_table import build_symbol_table
from piccolo_sql_guard.models import SqlClassification


@dataclass
class CallSite:
    kind: Literal["raw", "querystring"]
    call_node: ast.Call
    template_expr: ast.expr
    resolved_expr: ast.expr
    classification: SqlClassification
    path: str
    enclosing_class: str | None = None


class CallSiteCollector(ast.NodeVisitor):
    def __init__(
        self,
        scope: PiccoloScope,
        path: str,
        builder_allowlist: set[str],
    ) -> None:
        self.scope = scope
        self.path = path
        self.builder_allowlist = builder_allowlist
        self.call_sites: list[CallSite] = []
        self._current_class: str | None = None
        self._symbol_table: dict[str, ast.expr] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_class = self._current_class
        prev_table = self._symbol_table
        if node.name in self.scope.table_subclasses:
            self._current_class = node.name
        self._symbol_table = {}
        self.generic_visit(node)
        self._symbol_table = prev_table
        self._current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        prev_table = self._symbol_table
        self._symbol_table = build_symbol_table(node)
        self.generic_visit(node)
        self._symbol_table = prev_table

    def visit_Call(self, node: ast.Call) -> None:
        self._check_raw_call(node)
        self._check_querystring_call(node)
        self.generic_visit(node)

    def _check_raw_call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr != "raw":
            return
        if not node.args:
            return

        receiver = node.func.value
        if not self._is_table_receiver(receiver):
            return

        template_expr = node.args[0]
        resolved, classification = self._resolve(template_expr)

        self.call_sites.append(
            CallSite(
                kind="raw",
                call_node=node,
                template_expr=template_expr,
                resolved_expr=resolved,
                classification=classification,
                path=self.path,
                enclosing_class=self._current_class,
            )
        )

    def _check_querystring_call(self, node: ast.Call) -> None:
        if not node.args:
            return
        if not self._is_querystring_call(node.func):
            return

        template_expr = node.args[0]
        resolved, classification = self._resolve(template_expr)

        self.call_sites.append(
            CallSite(
                kind="querystring",
                call_node=node,
                template_expr=template_expr,
                resolved_expr=resolved,
                classification=classification,
                path=self.path,
                enclosing_class=self._current_class,
            )
        )

    def _is_querystring_call(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in self.scope.querystring_names
        if isinstance(func, ast.Attribute) and func.attr == "QueryString":
            root = self._attribute_root(func.value)
            return root is not None and root in self.scope.querystring_attribute_roots
        return False

    def _attribute_root(self, expr: ast.expr) -> str | None:
        while isinstance(expr, ast.Attribute):
            expr = expr.value
        if isinstance(expr, ast.Name):
            return expr.id
        return None

    def _is_table_receiver(self, receiver: ast.expr) -> bool:
        if isinstance(receiver, ast.Name):
            if receiver.id in self.scope.table_subclasses:
                return True
            if receiver.id in ("self", "cls") and self._current_class is not None:
                return True
        return False

    def _resolve(self, expr: ast.expr) -> tuple[ast.expr, SqlClassification]:
        if isinstance(expr, ast.Name) and expr.id in self._symbol_table:
            resolved = self._symbol_table[expr.id]
            return resolved, classify_expr(resolved, self.builder_allowlist)
        return expr, classify_expr(expr, self.builder_allowlist)
