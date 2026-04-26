from __future__ import annotations

from pathlib import Path

from piccolo_sql_guard.analysis.function_summary import (
    FunctionSummary,
    compute_summary,
)
from piccolo_sql_guard.analysis.project_index import build_project_index
from piccolo_sql_guard.analysis.provenance import (
    BOOL,
    LITERAL,
    UNKNOWN,
    UNTYPED_STR,
    ProvenanceCategory,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content)
    return f


def _summary(tmp_path: Path, src: str, fn_name: str = "build") -> FunctionSummary:
    f = _write(tmp_path, "mod.py", src)
    idx = build_project_index([f], source_roots=[])
    fqn = next(k for k in idx._functions if fn_name in k)
    fn_entry = idx.get_function(fqn)
    assert fn_entry is not None
    return compute_summary(fn_entry, idx)


class TestParamProvenance:
    def test_literal_param(self, tmp_path: Path) -> None:
        src = """\
def build(order_by: "Literal['asc', 'desc']") -> str:
    return f"ORDER BY {order_by}"
"""
        # Can't use string annotation easily, use real import style
        src = """\
from typing import Literal
def build(order_by: Literal["asc", "desc"]) -> str:
    return f"ORDER BY {order_by}"
"""
        s = _summary(tmp_path, src)
        assert ProvenanceCategory.LITERAL_TYPE in s.parameter_provenance.get(
            "order_by", UNKNOWN
        )

    def test_bool_param(self, tmp_path: Path) -> None:
        src = """\
def build(has_cursor: bool) -> str:
    return "x"
"""
        s = _summary(tmp_path, src)
        assert s.parameter_provenance.get("has_cursor") == BOOL

    def test_str_param(self, tmp_path: Path) -> None:
        src = """\
def build(raw: str) -> str:
    return raw
"""
        s = _summary(tmp_path, src)
        assert s.parameter_provenance.get("raw") == UNTYPED_STR

    def test_unannotated_param_is_unknown(self, tmp_path: Path) -> None:
        src = """\
def build(x) -> str:
    return x
"""
        s = _summary(tmp_path, src)
        assert s.parameter_provenance.get("x") == UNKNOWN

    def test_vararg_is_unknown(self, tmp_path: Path) -> None:
        src = """\
def build(*args: str) -> str:
    return ""
"""
        s = _summary(tmp_path, src)
        assert s.parameter_provenance.get("args") == UNKNOWN


class TestReturnProvenance:
    def test_literal_return(self, tmp_path: Path) -> None:
        src = """\
def build() -> str:
    return "SELECT *"
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == LITERAL

    def test_fstring_literal_only(self, tmp_path: Path) -> None:
        src = """\
def build() -> str:
    table = "projects"
    return f"SELECT * FROM {table}"
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == LITERAL

    def test_fstring_with_untyped_param(self, tmp_path: Path) -> None:
        src = """\
def build(table: str) -> str:
    return f"SELECT * FROM {table}"
"""
        s = _summary(tmp_path, src)
        assert ProvenanceCategory.UNTYPED_STR in s.return_provenance

    def test_fstring_with_literal_param(self, tmp_path: Path) -> None:
        src = """\
from typing import Literal
def build(order: Literal["ASC", "DESC"]) -> str:
    return f"ORDER BY {order}"
"""
        s = _summary(tmp_path, src)
        assert ProvenanceCategory.LITERAL_TYPE in s.return_provenance

    def test_conditional_assignment(self, tmp_path: Path) -> None:
        src = """\
from typing import Literal
def build(order: Literal["asc", "desc"]) -> str:
    direction = "ASC" if order == "asc" else "DESC"
    return f"ORDER BY {direction}"
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == LITERAL

    def test_if_branch_both_literal(self, tmp_path: Path) -> None:
        src = """\
def build(x: bool) -> str:
    if x:
        col = "a"
    else:
        col = "b"
    return f"SELECT {col}"
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == LITERAL

    def test_if_branch_one_unsafe(self, tmp_path: Path) -> None:
        src = """\
def build(x: str) -> str:
    if len(x) > 3:
        col = "a"
    else:
        col = x
    return f"SELECT {col}"
"""
        s = _summary(tmp_path, src)
        assert ProvenanceCategory.UNTYPED_STR in s.return_provenance

    def test_concat_literals(self, tmp_path: Path) -> None:
        src = """\
def build() -> str:
    a = "SELECT"
    b = " * FROM t"
    return a + b
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == LITERAL

    def test_augassign(self, tmp_path: Path) -> None:
        src = """\
def build() -> str:
    sql = "SELECT *"
    sql += " FROM t"
    return sql
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == LITERAL

    def test_module_constant_used(self, tmp_path: Path) -> None:
        src = """\
_FROM = "FROM projects"
def build() -> str:
    return "SELECT * " + _FROM
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == LITERAL

    def test_no_return_is_unknown(self, tmp_path: Path) -> None:
        src = """\
def build() -> None:
    pass
"""
        s = _summary(tmp_path, src)
        assert s.return_provenance == UNKNOWN


class TestTokenSinks:
    def test_safe_fstring_no_unsafe_sinks(self, tmp_path: Path) -> None:
        src = """\
from typing import Literal
def build(order: Literal["ASC", "DESC"]) -> str:
    return f"ORDER BY {order}"
"""
        s = _summary(tmp_path, src)
        for sink in s.token_sinks:
            assert sink.provenance.is_safe()

    def test_unsafe_fstring_has_sink(self, tmp_path: Path) -> None:
        src = """\
def build(table: str) -> str:
    return f"SELECT * FROM {table}"
"""
        s = _summary(tmp_path, src)
        assert any(not sink.provenance.is_safe() for sink in s.token_sinks)

    def test_sink_origin_expr_captured(self, tmp_path: Path) -> None:
        src = """\
def build(table: str) -> str:
    return f"SELECT * FROM {table}"
"""
        s = _summary(tmp_path, src)
        exprs = [sink.origin_expr for sink in s.token_sinks]
        assert "table" in exprs

    def test_sink_location_has_line(self, tmp_path: Path) -> None:
        src = """\
def build(table: str) -> str:
    return f"SELECT * FROM {table}"
"""
        s = _summary(tmp_path, src)
        assert all(sink.location.line > 0 for sink in s.token_sinks)


class TestResolution:
    def test_complete_when_all_safe(self, tmp_path: Path) -> None:
        src = """\
def build() -> str:
    return "SELECT 1"
"""
        s = _summary(tmp_path, src)
        assert s.resolution == "complete"

    def test_partial_when_unknown_sink(self, tmp_path: Path) -> None:
        src = """\
def build(table: str) -> str:
    return f"SELECT * FROM {table}"
"""
        s = _summary(tmp_path, src)
        assert s.resolution == "partial"


class TestClassMethods:
    def test_class_constant_attr(self, tmp_path: Path) -> None:
        src = """\
class Repo:
    TABLE = "projects"
    def build(self) -> str:
        return f"SELECT * FROM {self.TABLE}"
"""
        f = _write(tmp_path, "mod.py", src)
        idx = build_project_index([f], source_roots=[])
        fqn = next(k for k in idx._functions if "build" in k)
        fn_entry = idx.get_function(fqn)
        assert fn_entry is not None
        cls_fqn = next(k for k in idx._classes if "Repo" in k)
        cls_entry = idx.get_class(cls_fqn)
        s = compute_summary(fn_entry, idx, class_entry=cls_entry)
        assert s.return_provenance == LITERAL

    def test_cross_function_call_without_memo_is_unknown(self, tmp_path: Path) -> None:
        src = """\
def helper() -> str:
    return "FROM t"

def build() -> str:
    return "SELECT * " + helper()
"""
        s = _summary(tmp_path, src)
        # Without memo, helper() returns UNKNOWN, joined with LITERAL
        assert ProvenanceCategory.UNKNOWN in s.return_provenance


class TestRealLikeBuilder:
    """Mirror of pyxida's build_list_projects_sql pattern."""

    def test_safe_literal_builder(self, tmp_path: Path) -> None:
        src = """\
from typing import Literal

_FROM_USER = "FROM projects JOIN projects_users"
_FROM_WORKSPACE = "FROM projects"

def build_list_projects_sql(
    scope: Literal["user", "workspace"],
    order_by: Literal["created_at_desc", "created_at_asc"],
    has_statuses: bool,
    has_cursor: bool,
) -> str:
    from_clause = _FROM_WORKSPACE if scope == "workspace" else _FROM_USER
    order_direction = "DESC" if order_by == "created_at_desc" else "ASC"
    return (
        f"SELECT * {from_clause} "
        f"ORDER BY created_at {order_direction}"
    )
"""
        s = _summary(tmp_path, src, fn_name="build_list_projects_sql")
        assert s.return_provenance.is_safe()
        unsafe = [sink for sink in s.token_sinks if not sink.provenance.is_safe()]
        assert not unsafe

    def test_unsafe_when_order_by_is_str(self, tmp_path: Path) -> None:
        src = """\
def build_sql(order_by: str) -> str:
    return f"ORDER BY {order_by}"
"""
        s = _summary(tmp_path, src, fn_name="build_sql")
        assert not s.return_provenance.is_safe()
        assert any(not sink.provenance.is_safe() for sink in s.token_sinks)
