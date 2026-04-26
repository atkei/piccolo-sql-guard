from __future__ import annotations

from pathlib import Path

from piccolo_sql_guard.config import Config
from piccolo_sql_guard.engine import run_engine
from piccolo_sql_guard.rules.registry import get_rules

FIXTURES = Path(__file__).parent.parent / "fixtures"


def scan(path: Path, select: list[str] | None = None) -> list[str]:
    config = Config()
    rules = get_rules(select=select or ["PQS004"])
    result = run_engine([path], rules, config)
    return [d.rule_code for d in result.diagnostics]


def _assert_seed_first_matches_baseline(files: list[Path]) -> None:
    import piccolo_sql_guard.engine as engine
    from piccolo_sql_guard.analysis.call_graph import (
        build_reachable_call_graph,
        compute_all_summaries,
        compute_summaries_for_graph,
    )
    from piccolo_sql_guard.analysis.project_index import ProjectIndex
    from piccolo_sql_guard.rules.pqs004 import PQS004

    config = Config()
    context = engine._EngineContext(
        index=ProjectIndex(source_roots=engine._infer_source_roots(files))
    )

    for file_path in files:
        context.index.register_file(file_path)
    engine._expand_project_index(context.index, context.expanded_modules)

    seed_fqns = engine._collect_pqs004_seed_fqns(
        context,
        config,
        set(config.builder_allowlist),
    )
    all_summaries = compute_all_summaries(context.index, config.pqs004_max_iterations)
    baseline = engine._filter_reachable_summaries(seed_fqns, all_summaries)

    reachable_graph = build_reachable_call_graph(context.index, seed_fqns)
    optimized = compute_summaries_for_graph(
        context.index,
        reachable_graph,
        config.pqs004_max_iterations,
    )

    assert set(baseline) == set(optimized)

    rule = PQS004()
    baseline_diags = [
        (d.path, d.line, d.column, d.message)
        for d in sorted(
            rule.check_project(baseline, context.index),
            key=lambda d: (d.path, d.line, d.column, d.message),
        )
    ]
    optimized_diags = [
        (d.path, d.line, d.column, d.message)
        for d in sorted(
            rule.check_project(optimized, context.index),
            key=lambda d: (d.path, d.line, d.column, d.message),
        )
    ]
    assert baseline_diags == optimized_diags


# ---------------------------------------------------------------------------
# Safe fixtures — must not trigger PQS004
# ---------------------------------------------------------------------------


def test_safe_token_builder_no_pqs004() -> None:
    codes = scan(FIXTURES / "safe" / "safe_token_builder.py")
    assert "PQS004" not in codes


def test_safe_literal_builder_no_pqs004() -> None:
    codes = scan(FIXTURES / "safe" / "allowlisted_builder.py")
    assert "PQS004" not in codes


def test_safe_literal_raw_no_pqs004() -> None:
    codes = scan(FIXTURES / "safe" / "literal_raw.py")
    assert "PQS004" not in codes


def test_safe_bool_param_no_pqs004() -> None:
    codes = scan(FIXTURES / "safe" / "bool_param_builder.py")
    assert "PQS004" not in codes


def test_safe_enum_param_no_pqs004() -> None:
    codes = scan(FIXTURES / "safe" / "enum_param_builder.py")
    assert "PQS004" not in codes


def test_safe_chained_builders_no_pqs004() -> None:
    codes = scan(FIXTURES / "safe" / "chained_safe_builders.py")
    assert "PQS004" not in codes


def test_safe_ilike_placeholder_no_pqs004() -> None:
    """Literal operator + {} placeholder binding must not trigger PQS004."""
    codes = scan(FIXTURES / "safe" / "ilike_placeholder.py")
    assert "PQS004" not in codes


# ---------------------------------------------------------------------------
# Unsafe fixture — must trigger PQS004
# ---------------------------------------------------------------------------


def test_unsafe_builder_fn_pqs004() -> None:
    codes = scan(FIXTURES / "unsafe" / "unsafe_builder_fn.py")
    assert codes.count("PQS004") >= 2  # two unsafe tokens: table_name + order_by


def test_unsafe_mixed_params_only_str_flagged() -> None:
    """Literal-typed param must not be flagged; only the str param triggers PQS004."""
    rules = get_rules(select=["PQS004"])
    config = Config()
    result = run_engine(
        [FIXTURES / "unsafe" / "mixed_params_builder.py"], rules, config
    )
    pqs004 = [d for d in result.diagnostics if d.rule_code == "PQS004"]
    # table (Literal) is safe; sort_col (str) is unsafe — exactly 1 sink per builder fn
    assert any("sort_col" in d.message for d in pqs004)
    assert not any("table" in d.message for d in pqs004)


def test_unsafe_chained_builder_pqs004() -> None:
    """Unsafe token propagates through a chain: both inner and outer builder flagged."""
    codes = scan(FIXTURES / "unsafe" / "chained_unsafe_builder.py")
    assert codes.count("PQS004") >= 2


def test_unsafe_ilike_fstring_builder_pqs004() -> None:
    """Builder that interpolates ILIKE search value directly must trigger PQS004."""
    codes = scan(FIXTURES / "unsafe" / "ilike_fstring_builder.py")
    assert "PQS004" in codes


def test_unsafe_join_builder_pqs004(tmp_path: Path) -> None:
    """Unsafe tokens joined into SQL fragments must trigger PQS004."""
    path = tmp_path / "join_builder.py"
    path.write_text(
        """from piccolo.table import Table


class MyModel(Table):
    pass


def build_query(order_by: str) -> str:
    return "SELECT * FROM my_model ORDER BY " + ", ".join([order_by])


async def query(order_by: str) -> None:
    await MyModel.raw(build_query(order_by))
"""
    )

    rules = get_rules(select=["PQS004"])
    result = run_engine([path], rules, Config())
    pqs004 = [d for d in result.diagnostics if d.rule_code == "PQS004"]

    assert any("order_by" in d.message for d in pqs004)


def test_unrelated_string_builder_not_flagged() -> None:
    """Only builders reachable from Piccolo raw sink should be checked."""
    rules = get_rules(select=["PQS004"])
    config = Config()
    result = run_engine(
        [FIXTURES / "unsafe" / "unrelated_string_builder.py"],
        rules,
        config,
    )
    pqs004 = [d for d in result.diagnostics if d.rule_code == "PQS004"]
    assert any("order_by" in d.message for d in pqs004)
    assert not any("name" in d.message for d in pqs004)


def test_imported_table_builder_pqs004() -> None:
    """Imported Table subclass receiver should still seed PQS004 analysis."""
    codes = scan(FIXTURES / "unsafe" / "imported_table_builder.py")
    assert "PQS004" in codes


# ---------------------------------------------------------------------------
# Diagnostic details
# ---------------------------------------------------------------------------


def test_pqs004_diagnostic_fields() -> None:
    rules = get_rules(select=["PQS004"])
    config = Config()
    result = run_engine([FIXTURES / "unsafe" / "unsafe_builder_fn.py"], rules, config)
    assert result.diagnostics
    d = result.diagnostics[0]
    assert d.rule_code == "PQS004"
    assert d.line > 0
    assert d.column >= 0
    assert "unsafe_builder_fn.py" in d.path
    assert "unsafe SQL token" in d.message


def test_pqs004_message_names_origin_expr() -> None:
    rules = get_rules(select=["PQS004"])
    config = Config()
    result = run_engine([FIXTURES / "unsafe" / "unsafe_builder_fn.py"], rules, config)
    exprs = {d.message.split("`")[1] for d in result.diagnostics}
    assert "table_name" in exprs or "order_by" in exprs


# ---------------------------------------------------------------------------
# Interaction with other rules
# ---------------------------------------------------------------------------


def test_safe_builder_no_pqs004_with_all_rules() -> None:
    """Safe builder must not trigger PQS004 even when all rules are active."""
    rules = get_rules()
    config = Config()
    result = run_engine([FIXTURES / "safe" / "safe_token_builder.py"], rules, config)
    pqs004_codes = [d for d in result.diagnostics if d.rule_code == "PQS004"]
    assert pqs004_codes == []


def test_nested_function_does_not_leak_into_outer() -> None:
    """A nested function's unsafe f-string must not cause PQS004 on the outer
    function — nested scopes are analyzed separately."""
    from piccolo_sql_guard.engine import run_engine

    result = run_engine(
        [FIXTURES / "safe" / "nested_function_builder.py"],
        get_rules(select=["PQS004"]),
        Config(),
    )
    for d in result.diagnostics:
        assert "build_safe" not in d.message, d.message


def test_max_iterations_config_respected() -> None:
    rules = get_rules(select=["PQS004"])
    config = Config(pqs004_max_iterations=1)
    result = run_engine([FIXTURES / "unsafe" / "unsafe_builder_fn.py"], rules, config)
    # Still finds violations even with min iterations
    assert any(d.rule_code == "PQS004" for d in result.diagnostics)


def test_seed_first_pqs004_matches_full_summary_graph() -> None:
    files = sorted(FIXTURES.rglob("*.py"))
    _assert_seed_first_matches_baseline(files)


def test_seed_first_matches_baseline_on_recursive_synthetic_corpus(
    tmp_path: Path,
) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "queries.py").write_text(
        """from piccolo.querystring import QueryString


def even_clause(n: int) -> str:
    if n <= 0:
        return "status = 'even'"
    return odd_clause(n - 1)


def odd_clause(n: int) -> str:
    if n <= 0:
        return "status = 'odd'"
    return even_clause(n - 1)


def build_query(n: int) -> str:
    return "SELECT * FROM projects WHERE " + even_clause(n)


def run(n: int):
    return QueryString(build_query(n))
"""
    )

    files = sorted(tmp_path.rglob("*.py"))
    _assert_seed_first_matches_baseline(files)


def test_seed_first_matches_baseline_on_reexport_heavy_synthetic_corpus(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg" / "builders").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("from .exports import build_sql\n")
    (tmp_path / "pkg" / "exports.py").write_text(
        "from .builders.query import build_sql\n"
    )
    (tmp_path / "pkg" / "builders" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "builders" / "query.py").write_text(
        """def table_name_fragment(table_name: str) -> str:
    return f'"{table_name}"'


def build_sql(table_name: str) -> str:
    return "SELECT * FROM " + table_name_fragment(table_name)
"""
    )
    (tmp_path / "consumer.py").write_text(
        """from piccolo.querystring import QueryString
from pkg import build_sql


def run(table_name: str):
    return QueryString(build_sql(table_name))
"""
    )

    files = sorted(tmp_path.rglob("*.py"))
    _assert_seed_first_matches_baseline(files)
