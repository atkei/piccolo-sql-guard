from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from piccolo_sql_guard.analysis.ast_parser import is_type_checking_guard

_MAX_REEXPORT_DEPTH = 4


@dataclass(frozen=True)
class ImportedName:
    """A single resolved import binding: local_name → (source_fqn, original_name)."""

    local_name: str
    source_fqn: str
    original_name: str


@dataclass
class ModuleImports:
    """All resolved import bindings for one module."""

    fqn: str
    bindings: list[ImportedName] = field(default_factory=list)
    star_imports: list[str] = field(default_factory=list)

    def lookup(self, local_name: str) -> ImportedName | None:
        for b in self.bindings:
            if b.local_name == local_name:
                return b
        return None


def fqn_from_path(path: Path, source_roots: list[Path]) -> str:
    """Derive a dotted module FQN from a file path.

    Strips the longest matching ``source_roots`` prefix, then walks up until
    no ``__init__.py`` is found in the parent.
    """
    path = path.resolve()
    for root in sorted(source_roots, key=lambda r: len(r.parts), reverse=True):
        root = root.resolve()
        try:
            relative = path.relative_to(root)
            parts = list(relative.with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            return ".".join(parts)
        except ValueError:
            continue

    # Fall back: walk up until parent has no __init__.py
    candidate = path
    fallback_parts: list[str] = []
    if candidate.suffix == ".py":
        stem = candidate.stem
        if stem != "__init__":
            fallback_parts.append(stem)
        candidate = candidate.parent
    while (candidate / "__init__.py").exists():
        fallback_parts.append(candidate.name)
        candidate = candidate.parent
    fallback_parts.reverse()
    return ".".join(fallback_parts) if fallback_parts else path.stem


def collect_module_imports(
    tree: ast.Module,
    current_fqn: str,
) -> ModuleImports:
    """Walk a module AST and collect all import bindings.

    ``TYPE_CHECKING`` blocks are skipped (runtime-invisible).
    Conditional imports inside ``try/except`` use the first branch.
    """
    imports = ModuleImports(fqn=current_fqn)
    _walk_imports(tree.body, imports, current_fqn, in_type_checking=False)
    return imports


def _walk_imports(
    stmts: list[ast.stmt],
    imports: ModuleImports,
    current_fqn: str,
    *,
    in_type_checking: bool,
) -> None:
    for node in stmts:
        if is_type_checking_guard(node):
            continue

        if isinstance(node, ast.ImportFrom):
            _handle_import_from(node, imports, current_fqn)
        elif isinstance(node, ast.Import):
            _handle_import(node, imports)
        elif isinstance(node, ast.If):
            _walk_imports(
                node.body, imports, current_fqn, in_type_checking=in_type_checking
            )
            _walk_imports(
                node.orelse, imports, current_fqn, in_type_checking=in_type_checking
            )
        elif isinstance(node, ast.Try):
            _walk_imports(
                node.body, imports, current_fqn, in_type_checking=in_type_checking
            )
            for handler in node.handlers:
                _walk_imports(
                    handler.body,
                    imports,
                    current_fqn,
                    in_type_checking=in_type_checking,
                )
            _walk_imports(
                node.orelse, imports, current_fqn, in_type_checking=in_type_checking
            )


def _handle_import_from(
    node: ast.ImportFrom,
    imports: ModuleImports,
    current_fqn: str,
) -> None:
    module = node.module or ""
    level = node.level or 0

    if level > 0:
        package_fqn = _resolve_relative(current_fqn, level)
        base_fqn = f"{package_fqn}.{module}" if module else package_fqn
    else:
        base_fqn = module

    for alias in node.names:
        if alias.name == "*":
            imports.star_imports.append(base_fqn)
            continue
        local = alias.asname or alias.name
        # `from . import X` → X is a submodule of the package
        if level > 0 and not module:
            source_fqn = f"{base_fqn}.{alias.name}" if base_fqn else alias.name
        else:
            source_fqn = base_fqn
        imports.bindings.append(
            ImportedName(
                local_name=local,
                source_fqn=source_fqn,
                original_name=alias.name,
            )
        )


def _handle_import(node: ast.Import, imports: ModuleImports) -> None:
    for alias in node.names:
        local = alias.asname or alias.name.split(".", 1)[0]
        imports.bindings.append(
            ImportedName(
                local_name=local,
                source_fqn=alias.name,
                original_name=alias.name,
            )
        )


def _resolve_relative(current_fqn: str, level: int) -> str:
    """Resolve a relative import anchor to an absolute package FQN.

    level=1 means "current package" (strip the module name).
    level=2 means "parent package" (strip module + one package component).
    """
    parts = current_fqn.split(".")
    # Drop `level` trailing components: level=1 strips the module name,
    # level=2 strips module + one package directory, etc.
    anchor_parts = parts[: max(0, len(parts) - level)]
    return ".".join(anchor_parts)


def resolve_reexports(
    name: str,
    source_fqn: str,
    module_exports: dict[str, ModuleImports],
    depth: int = 0,
    _visited: frozenset[tuple[str, str]] | None = None,
) -> ImportedName | None:
    """Follow re-exports up to _MAX_REEXPORT_DEPTH hops.

    Returns the final ``ImportedName`` whose ``source_fqn`` points to a
    non-re-exporting module, or ``None`` if unresolvable.
    """
    if _visited is None:
        _visited = frozenset()
    key = (source_fqn, name)
    if key in _visited or depth > _MAX_REEXPORT_DEPTH:
        return None
    _visited = _visited | {key}

    mod_imports = module_exports.get(source_fqn)
    if mod_imports is None:
        return None
    binding = mod_imports.lookup(name)
    if binding is None:
        return None
    if binding.source_fqn == source_fqn:
        return None
    # If the binding itself re-exports, follow it
    inner = module_exports.get(binding.source_fqn)
    if inner is not None and inner.lookup(binding.original_name) is not None:
        return resolve_reexports(
            binding.original_name,
            binding.source_fqn,
            module_exports,
            depth + 1,
            _visited,
        )
    return binding
