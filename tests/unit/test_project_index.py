from __future__ import annotations

from pathlib import Path

from piccolo_sql_guard.analysis.project_index import build_project_index
from piccolo_sql_guard.analysis.provenance import LITERAL


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class TestProjectIndex:
    def test_register_module_fqn(self, tmp_path: Path) -> None:
        _write(tmp_path, "pkg/__init__.py", "")
        _write(tmp_path, "pkg/service.py", "X = 1\n")
        svc = tmp_path / "pkg" / "service.py"
        idx = build_project_index([svc], source_roots=[])
        fqns = idx.all_module_fqns()
        assert any("service" in fqn for fqn in fqns)

    def test_top_level_function_registered(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "mymod.py", "def build_sql(x: str) -> str:\n    return x\n"
        )
        idx = build_project_index([f], source_roots=[])
        fqns = list(idx._functions.keys())
        assert any("build_sql" in fqn for fqn in fqns)

    def test_class_and_method_registered(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path,
            "svc.py",
            "class Repo:\n    def get(self) -> str:\n        return 'x'\n",
        )
        idx = build_project_index([f], source_roots=[])
        cls_fqns = list(idx._classes.keys())
        fn_fqns = list(idx._functions.keys())
        assert any("Repo" in fqn for fqn in cls_fqns)
        assert any("Repo.get" in fqn for fqn in fn_fqns)

    def test_constant_store_populated(self, tmp_path: Path) -> None:
        f = _write(tmp_path, "constants.py", 'SQL_FRAG = "SELECT *"\n')
        idx = build_project_index([f], source_roots=[])
        fqn = next(fqn for fqn in idx.all_module_fqns() if "constants" in fqn)
        mod = idx.get_module(fqn)
        assert mod is not None
        assert mod.constant_store.get("SQL_FRAG") == LITERAL

    def test_enum_class_detected(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path,
            "enums.py",
            "from enum import Enum\nclass Status(Enum):\n    ACTIVE = 'active'\n",
        )
        idx = build_project_index([f], source_roots=[])
        fqn = next(fqn for fqn in idx.all_module_fqns() if "enums" in fqn)
        mod = idx.get_module(fqn)
        assert mod is not None
        assert "Status" in mod.enum_classes

    def test_idempotent_register(self, tmp_path: Path) -> None:
        f = _write(tmp_path, "mod.py", "X = 1\n")
        idx = build_project_index([f, f], source_roots=[])
        assert len(idx.all_module_fqns()) == 1

    def test_parse_error_returns_stub(self, tmp_path: Path) -> None:
        f = _write(tmp_path, "broken.py", "def (:\n")
        build_project_index([f], source_roots=[])
        # Should not raise; module list may or may not include broken.py

    def test_resolve_name_follows_import(self, tmp_path: Path) -> None:
        _write(tmp_path, "pkg/__init__.py", "from .internal import Foo\n")
        _write(tmp_path, "pkg/internal.py", "Foo = 'foo'\n")
        _write(tmp_path, "user.py", "from pkg import Foo\n")

        idx = build_project_index(
            [
                tmp_path / "user.py",
                tmp_path / "pkg" / "__init__.py",
                tmp_path / "pkg" / "internal.py",
            ],
            source_roots=[],
        )
        user_fqn = next(fqn for fqn in idx.all_module_fqns() if "user" in fqn)
        binding = idx.resolve_name("Foo", user_fqn)
        assert binding is not None

    def test_resolve_name_caches_hits_and_misses(self, tmp_path: Path) -> None:
        _write(tmp_path, "pkg/__init__.py", "from .internal import Foo\n")
        _write(tmp_path, "pkg/internal.py", "Foo = 'foo'\n")
        user = _write(tmp_path, "user.py", "from pkg import Foo\n")

        idx = build_project_index(
            [
                user,
                tmp_path / "pkg" / "__init__.py",
                tmp_path / "pkg" / "internal.py",
            ],
            source_roots=[],
        )
        user_fqn = next(fqn for fqn in idx.all_module_fqns() if "user" in fqn)

        foo = idx.resolve_name("Foo", user_fqn)
        missing = idx.resolve_name("Missing", user_fqn)

        assert foo is not None
        assert missing is None
        assert idx._resolved_name_cache[(user_fqn, "Foo")] == foo
        assert idx._resolved_name_cache[(user_fqn, "Missing")] is None
        assert idx.resolve_name("Foo", user_fqn) == foo
        assert idx.resolve_name("Missing", user_fqn) is None

    def test_register_file_invalidates_resolution_caches(self, tmp_path: Path) -> None:
        _write(tmp_path, "pkg/__init__.py", "from .internal import Foo\n")
        _write(tmp_path, "pkg/internal.py", "Foo = 'foo'\n")
        user = _write(tmp_path, "user.py", "from pkg import Foo\n")
        extra = _write(tmp_path, "extra.py", "from pkg import Foo as Bar\n")

        idx = build_project_index(
            [user, tmp_path / "pkg" / "__init__.py", tmp_path / "pkg" / "internal.py"],
            source_roots=[],
        )
        user_fqn = next(fqn for fqn in idx.all_module_fqns() if "user" in fqn)

        assert idx.resolve_name("Foo", user_fqn) is not None
        assert idx._all_imports_cache is not None
        assert idx._resolved_name_cache

        idx.register_file(extra)

        assert idx._all_imports_cache is None
        assert idx._resolved_name_cache == {}

    def test_source_root_fqn(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        _write(tmp_path, "src/app/__init__.py", "")
        f = _write(tmp_path, "src/app/mod.py", "X = 1\n")
        idx = build_project_index([f], source_roots=[src])
        fqns = idx.all_module_fqns()
        assert any(fqn == "app.mod" for fqn in fqns)

    def test_class_constant_store(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path,
            "repo.py",
            'class ProjectRepo:\n    TABLE = "projects"\n',
        )
        idx = build_project_index([f], source_roots=[])
        cls_fqn = next(fqn for fqn in idx._classes if "ProjectRepo" in fqn)
        cls_entry = idx.get_class(cls_fqn)
        assert cls_entry is not None
        assert cls_entry.constant_store.get("TABLE") == LITERAL
