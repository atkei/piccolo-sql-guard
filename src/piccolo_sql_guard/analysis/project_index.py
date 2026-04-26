from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from piccolo_sql_guard.analysis.constant_store import (
    ConstantStore,
    build_class_constant_store,
    build_constant_store,
)
from piccolo_sql_guard.analysis.module_resolver import (
    ImportedName,
    ModuleImports,
    collect_module_imports,
    fqn_from_path,
    resolve_reexports,
)


@dataclass
class FunctionEntry:
    """A discovered function/method with its AST node and containing module FQN."""

    fqn: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    module_fqn: str
    class_name: str | None = None


@dataclass
class ClassEntry:
    """A discovered class with class-level constant store and enum membership."""

    fqn: str
    node: ast.ClassDef
    module_fqn: str
    constant_store: ConstantStore
    is_enum: bool = False
    base_names: list[str] = field(default_factory=list)


@dataclass
class ModuleEntry:
    """Parsed state for one module."""

    fqn: str
    path: Path
    tree: ast.Module
    constant_store: ConstantStore
    imports: ModuleImports
    enum_classes: frozenset[str] = field(default_factory=frozenset)


@dataclass
class ProjectIndex:
    """Lazy cross-file registry of parsed modules, functions, and classes.

    Files are parsed on first access.  All ASTs are memoized for the lifetime
    of the run.
    """

    source_roots: list[Path] = field(default_factory=list)

    _modules: dict[str, ModuleEntry] = field(default_factory=dict)
    _functions: dict[str, FunctionEntry] = field(default_factory=dict)
    _classes: dict[str, ClassEntry] = field(default_factory=dict)
    _path_to_fqn: dict[Path, str] = field(default_factory=dict)
    _search_roots_cache: list[Path] | None = None
    _local_module_path_cache: dict[str, Path | None] = field(default_factory=dict)
    _all_imports_cache: dict[str, ModuleImports] | None = None
    _resolved_name_cache: dict[tuple[str, str], ImportedName | None] = field(
        default_factory=dict
    )

    def register_file(self, path: Path) -> ModuleEntry:
        """Parse *path* and register all its top-level symbols."""
        resolved = path.resolve()
        if resolved in self._path_to_fqn:
            fqn = self._path_to_fqn[resolved]
            return self._modules[fqn]

        try:
            source = resolved.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(resolved))
        except (OSError, SyntaxError):
            # Return a stub so callers don't crash
            return self._register_stub(resolved)

        return self.register_parsed_file(resolved, tree)

    def register_parsed_file(self, path: Path, tree: ast.Module) -> ModuleEntry:
        """Register *path* using an already-parsed AST."""
        resolved = path.resolve()
        if resolved in self._path_to_fqn:
            fqn = self._path_to_fqn[resolved]
            return self._modules[fqn]

        fqn = fqn_from_path(resolved, self.source_roots)
        constant_store = build_constant_store(tree)
        imports = collect_module_imports(tree, fqn)
        enum_classes = _find_enum_classes(tree)

        entry = ModuleEntry(
            fqn=fqn,
            path=resolved,
            tree=tree,
            constant_store=constant_store,
            imports=imports,
            enum_classes=frozenset(enum_classes),
        )
        self._store_module_entry(resolved, entry)
        self._register_symbols(tree, fqn, enum_classes)
        return entry

    def get_module(self, fqn: str) -> ModuleEntry | None:
        return self._modules.get(fqn)

    def get_function(self, fqn: str) -> FunctionEntry | None:
        return self._functions.get(fqn)

    def get_class(self, fqn: str) -> ClassEntry | None:
        return self._classes.get(fqn)

    def resolve_name(
        self,
        name: str,
        from_module_fqn: str,
    ) -> ImportedName | None:
        """Resolve a local name in *from_module_fqn* to an ``ImportedName``.

        Follows one level of re-export through ``__init__.py`` files.
        """
        key = (from_module_fqn, name)
        if key in self._resolved_name_cache:
            return self._resolved_name_cache[key]

        mod = self._modules.get(from_module_fqn)
        if mod is None:
            self._resolved_name_cache[key] = None
            return None
        binding = mod.imports.lookup(name)
        if binding is None:
            self._resolved_name_cache[key] = None
            return None
        # Follow re-exports
        all_imports = self._all_imports()
        resolved = resolve_reexports(
            binding.original_name, binding.source_fqn, all_imports
        )
        result = resolved or binding
        self._resolved_name_cache[key] = result
        return result

    def has_function(self, fqn: str) -> bool:
        return fqn in self._functions

    def iter_function_items(self) -> list[tuple[str, FunctionEntry]]:
        return list(self._functions.items())

    def all_module_fqns(self) -> list[str]:
        return list(self._modules.keys())

    def _register_stub(self, resolved: Path) -> ModuleEntry:
        fqn = fqn_from_path(resolved, self.source_roots)
        stub_tree = ast.parse("", filename=str(resolved))
        entry = ModuleEntry(
            fqn=fqn,
            path=resolved,
            tree=stub_tree,
            constant_store=ConstantStore(),
            imports=ModuleImports(fqn=fqn),
        )
        self._store_module_entry(resolved, entry)
        return entry

    def _store_module_entry(self, resolved: Path, entry: ModuleEntry) -> None:
        self._modules[entry.fqn] = entry
        self._path_to_fqn[resolved] = entry.fqn
        self._all_imports_cache = None
        self._resolved_name_cache.clear()

    def _all_imports(self) -> dict[str, ModuleImports]:
        if self._all_imports_cache is None:
            self._all_imports_cache = {
                module_fqn: module.imports
                for module_fqn, module in self._modules.items()
            }
        return self._all_imports_cache

    def _register_symbols(
        self,
        tree: ast.Module,
        module_fqn: str,
        enum_classes: set[str],
    ) -> None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_fqn = f"{module_fqn}.{node.name}"
                self._functions[fn_fqn] = FunctionEntry(
                    fqn=fn_fqn,
                    node=node,
                    module_fqn=module_fqn,
                )
            elif isinstance(node, ast.ClassDef):
                cls_fqn = f"{module_fqn}.{node.name}"
                class_store = build_class_constant_store(node)
                is_enum = node.name in enum_classes
                base_names = [_base_name(b) for b in node.bases if _base_name(b)]
                self._classes[cls_fqn] = ClassEntry(
                    fqn=cls_fqn,
                    node=node,
                    module_fqn=module_fqn,
                    constant_store=class_store,
                    is_enum=is_enum,
                    base_names=base_names,
                )
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_fqn = f"{cls_fqn}.{child.name}"
                        self._functions[method_fqn] = FunctionEntry(
                            fqn=method_fqn,
                            node=child,
                            module_fqn=module_fqn,
                            class_name=node.name,
                        )


def _find_enum_classes(tree: ast.Module) -> set[str]:
    enum_classes: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = _base_name(base)
                if name in ("Enum", "StrEnum", "IntEnum", "IntFlag", "Flag"):
                    enum_classes.add(node.name)
                    break
    return enum_classes


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def build_project_index(
    paths: list[Path],
    source_roots: list[Path] | None = None,
) -> ProjectIndex:
    """Build a ProjectIndex by registering all given paths."""
    index = ProjectIndex(source_roots=source_roots or [])
    for path in paths:
        index.register_file(path)
    return index
