from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass, field

from piccolo_sql_guard.analysis.ast_parser import is_type_checking_guard


@dataclass
class PiccoloScope:
    piccolo_names: set[str] = field(default_factory=set)
    querystring_names: set[str] = field(default_factory=set)
    querystring_attribute_roots: set[str] = field(default_factory=set)
    table_names: set[str] = field(default_factory=set)
    table_subclasses: set[str] = field(default_factory=set)
    # Maps locally-bound module aliases (e.g. ``piccolo`` in ``import piccolo``)
    # to the Piccolo module path they refer to. Used to verify that
    # ``mod.Table`` base references actually resolve to Piccolo.
    _piccolo_module_aliases: set[str] = field(default_factory=set)

    def has_piccolo_imports(self) -> bool:
        return bool(self.piccolo_names)


def build_piccolo_scope(
    tree: ast.Module,
    piccolo_modules: list[str] | None = None,
) -> PiccoloScope:
    if piccolo_modules is None:
        piccolo_modules = ["piccolo"]

    scope = PiccoloScope()

    def is_piccolo_module(module: str) -> bool:
        return any(module == m or module.startswith(m + ".") for m in piccolo_modules)

    # Collect imports and class definitions without descending into
    # ``if TYPE_CHECKING:`` guards, since those are runtime-invisible and
    # must not trigger Piccolo scope activation.
    class_defs: list[ast.ClassDef] = []
    _walk_module(
        tree.body,
        scope,
        class_defs,
        is_piccolo_module,
        in_type_checking=False,
    )

    # Build a (class_name → base specifications) map where each base is either
    # a bare name or a (alias, attr) tuple so we can verify the alias points to
    # a Piccolo module before matching.
    class_bases: dict[str, list[tuple[str | None, str]]] = {}
    for cdef in class_defs:
        specs: list[tuple[str | None, str]] = []
        for b in cdef.bases:
            spec = _base_spec(b)
            if spec is not None:
                specs.append(spec)
        class_bases[cdef.name] = specs

    # Fixed-point expansion: a class is a Table subclass if any base either
    # matches ``scope.table_names`` (direct import) via a bare name, or is a
    # ``<piccolo_alias>.Table`` attribute reference, or transitively inherits
    # from another known Table subclass.
    changed = True
    while changed:
        changed = False
        for cls_name, specs in class_bases.items():
            if cls_name in scope.table_subclasses:
                continue
            for alias, attr in specs:
                if alias is None:
                    if attr in scope.table_names or attr in scope.table_subclasses:
                        scope.table_subclasses.add(cls_name)
                        changed = True
                        break
                else:
                    if attr == "Table" and alias in scope._piccolo_module_aliases:
                        scope.table_subclasses.add(cls_name)
                        changed = True
                        break

    return scope


def _walk_module(
    stmts: list[ast.stmt],
    scope: PiccoloScope,
    class_defs: list[ast.ClassDef],
    is_piccolo_module: Callable[[str], bool],
    *,
    in_type_checking: bool,
) -> None:
    for node in stmts:
        if is_type_checking_guard(node):
            continue

        if isinstance(node, ast.ImportFrom):
            if node.module and is_piccolo_module(node.module):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    scope.piccolo_names.add(local_name)
                    if alias.name == "Table":
                        scope.table_names.add(local_name)
                    if alias.name == "QueryString":
                        scope.querystring_names.add(local_name)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                if is_piccolo_module(alias.name):
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    scope.piccolo_names.add(local_name)
                    scope.querystring_attribute_roots.add(local_name)
                    scope._piccolo_module_aliases.add(local_name)

        elif isinstance(node, ast.ClassDef):
            class_defs.append(node)
            _walk_module(
                node.body,
                scope,
                class_defs,
                is_piccolo_module,
                in_type_checking=in_type_checking,
            )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _walk_module(
                node.body,
                scope,
                class_defs,
                is_piccolo_module,
                in_type_checking=in_type_checking,
            )

        elif isinstance(node, ast.If):
            _walk_module(
                node.body,
                scope,
                class_defs,
                is_piccolo_module,
                in_type_checking=in_type_checking,
            )
            _walk_module(
                node.orelse,
                scope,
                class_defs,
                is_piccolo_module,
                in_type_checking=in_type_checking,
            )

        elif isinstance(node, ast.Try):
            _walk_module(
                node.body,
                scope,
                class_defs,
                is_piccolo_module,
                in_type_checking=in_type_checking,
            )
            for handler in node.handlers:
                _walk_module(
                    handler.body,
                    scope,
                    class_defs,
                    is_piccolo_module,
                    in_type_checking=in_type_checking,
                )
            _walk_module(
                node.orelse,
                scope,
                class_defs,
                is_piccolo_module,
                in_type_checking=in_type_checking,
            )
            _walk_module(
                node.finalbody,
                scope,
                class_defs,
                is_piccolo_module,
                in_type_checking=in_type_checking,
            )


def _base_spec(node: ast.expr) -> tuple[str | None, str] | None:
    """Return a normalized base-class spec.

    - ``Foo``       → ``(None, "Foo")``
    - ``mod.Foo``   → ``("mod", "Foo")``
    - anything else → ``None``
    """
    if isinstance(node, ast.Name):
        return (None, node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return (node.value.id, node.attr)
    return None
