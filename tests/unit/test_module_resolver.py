from __future__ import annotations

import ast
from pathlib import Path

from piccolo_sql_guard.analysis.module_resolver import (
    ModuleImports,
    collect_module_imports,
    fqn_from_path,
    resolve_reexports,
)


class TestFqnFromPath:
    def test_simple_file_no_root(self, tmp_path: Path) -> None:
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        f = pkg / "service.py"
        f.touch()
        fqn = fqn_from_path(f, [])
        assert fqn == "mypkg.service"

    def test_nested_module(self, tmp_path: Path) -> None:
        (tmp_path / "a" / "b").mkdir(parents=True)
        (tmp_path / "a" / "__init__.py").touch()
        (tmp_path / "a" / "b" / "__init__.py").touch()
        f = tmp_path / "a" / "b" / "mod.py"
        f.touch()
        fqn = fqn_from_path(f, [])
        assert fqn == "a.b.mod"

    def test_source_root_stripped(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        pkg = src / "app" / "services"
        pkg.mkdir(parents=True)
        (src / "app" / "__init__.py").touch()
        (src / "app" / "services" / "__init__.py").touch()
        f = pkg / "query.py"
        f.touch()
        fqn = fqn_from_path(f, [src])
        assert fqn == "app.services.query"

    def test_init_file(self, tmp_path: Path) -> None:
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        fqn = fqn_from_path(pkg / "__init__.py", [])
        assert fqn == "mypkg"

    def test_longest_root_wins(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        deep = src / "app"
        deep.mkdir(parents=True)
        (deep / "__init__.py").touch()
        f = deep / "mod.py"
        f.touch()
        # Two roots: tmp_path and src — src is longer, should win
        fqn = fqn_from_path(f, [tmp_path, src])
        assert fqn == "app.mod"


class TestCollectModuleImports:
    def _collect(self, src: str, current_fqn: str = "mymod") -> ModuleImports:
        tree = ast.parse(src)
        return collect_module_imports(tree, current_fqn)

    def test_from_import(self) -> None:
        imports = self._collect("from pkg.mod import Foo")
        binding = imports.lookup("Foo")
        assert binding is not None
        assert binding.source_fqn == "pkg.mod"
        assert binding.original_name == "Foo"
        assert binding.local_name == "Foo"

    def test_from_import_alias(self) -> None:
        imports = self._collect("from pkg.mod import Foo as Bar")
        assert imports.lookup("Bar") is not None
        assert imports.lookup("Foo") is None
        assert imports.lookup("Bar").source_fqn == "pkg.mod"  # type: ignore

    def test_plain_import(self) -> None:
        imports = self._collect("import piccolo.orm")
        binding = imports.lookup("piccolo")
        assert binding is not None
        assert binding.source_fqn == "piccolo.orm"

    def test_star_import(self) -> None:
        imports = self._collect("from pkg.utils import *")
        assert "pkg.utils" in imports.star_imports

    def test_relative_import_level1(self) -> None:
        imports = self._collect("from . import helpers", "myapp.services.query")
        binding = imports.lookup("helpers")
        assert binding is not None
        assert binding.source_fqn == "myapp.services.helpers"

    def test_relative_import_with_module(self) -> None:
        imports = self._collect("from .sibling import X", "myapp.services.query")
        binding = imports.lookup("X")
        assert binding is not None
        assert binding.source_fqn == "myapp.services.sibling"

    def test_relative_import_level2(self) -> None:
        imports = self._collect("from ..core import Base", "myapp.services.query")
        binding = imports.lookup("Base")
        assert binding is not None
        assert "myapp.core" in binding.source_fqn

    def test_type_checking_block_skipped(self) -> None:
        src = """\
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pkg.mod import Heavy
"""
        imports = self._collect(src)
        assert imports.lookup("Heavy") is None

    def test_missing_name_returns_none(self) -> None:
        imports = self._collect("from pkg import X")
        assert imports.lookup("NotHere") is None

    def test_try_block_import_first_branch(self) -> None:
        src = """\
try:
    from fast_mod import Impl
except ImportError:
    from slow_mod import Impl
"""
        imports = self._collect(src)
        binding = imports.lookup("Impl")
        assert binding is not None
        assert binding.source_fqn == "fast_mod"


class TestResolveReexports:
    def _make_imports(
        self, fqn: str, bindings: list[tuple[str, str, str]]
    ) -> ModuleImports:
        from piccolo_sql_guard.analysis.module_resolver import ImportedName

        mi = ModuleImports(fqn=fqn)
        for local, source, original in bindings:
            mi.bindings.append(
                ImportedName(
                    local_name=local, source_fqn=source, original_name=original
                )
            )
        return mi

    def test_direct_binding(self) -> None:
        pkg_init = self._make_imports("pkg", [("Foo", "pkg.internal", "Foo")])
        all_imports = {"pkg": pkg_init}
        result = resolve_reexports("Foo", "pkg", all_imports)
        assert result is not None
        assert result.source_fqn == "pkg.internal"

    def test_missing_module(self) -> None:
        result = resolve_reexports("X", "nonexistent", {})
        assert result is None

    def test_missing_name_in_module(self) -> None:
        pkg = self._make_imports("pkg", [])
        result = resolve_reexports("Missing", "pkg", {"pkg": pkg})
        assert result is None
