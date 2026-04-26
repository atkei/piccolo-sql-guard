from __future__ import annotations

import ast

from piccolo_sql_guard.analysis.ast_parser import walk_no_nested_scopes


def build_symbol_table(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.expr]:
    table: dict[str, ast.expr] = {}

    for node in walk_no_nested_scopes(func_node):
        if node is func_node:
            continue

        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                table[node.targets[0].id] = node.value

        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
                name = node.target.id
                prev = table.get(name)
                if prev is not None:
                    synthetic = ast.BinOp(left=prev, op=ast.Add(), right=node.value)
                    ast.copy_location(synthetic, node)
                    table[name] = synthetic
                else:
                    table[name] = node.value

    return table
