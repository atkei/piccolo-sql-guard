from pathlib import Path

from piccolo_sql_guard.config import Config
from piccolo_sql_guard.engine import run_engine
from piccolo_sql_guard.rules.registry import get_rules

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_site_rule_scan_does_not_run_project_summary_analysis(monkeypatch) -> None:
    import piccolo_sql_guard.engine as engine

    calls = 0
    original = engine.compute_all_summaries

    def counting_compute_all_summaries(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        engine, "compute_all_summaries", counting_compute_all_summaries
    )

    files = [
        FIXTURES / "unsafe" / "fstring_raw.py",
        FIXTURES / "unsafe" / "imported_table_fstring_raw.py",
    ]
    result = run_engine(files, get_rules(select=["PQS001"]), Config())

    assert not result.internal_errors
    assert any(d.rule_code == "PQS001" for d in result.diagnostics)
    assert calls == 0


def test_project_only_scan_reports_parse_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("def broken(:\n    pass\n")

    result = run_engine([broken], get_rules(select=["PQS004"]), Config())

    assert result.parse_errors
    assert "syntax error" in result.parse_errors[0]
    assert result.files_scanned == 1


def test_source_roots_use_package_boundary(tmp_path: Path) -> None:
    import piccolo_sql_guard.engine as engine

    src = tmp_path / "src"
    pkg = src / "app" / "services"
    pkg.mkdir(parents=True)
    (src / "app" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    file_path = pkg / "query.py"
    file_path.write_text("")

    roots = engine._infer_source_roots([file_path])

    assert roots == [src.resolve()]


def test_source_roots_use_scan_path_for_namespace_package(tmp_path: Path) -> None:
    import piccolo_sql_guard.engine as engine

    src = tmp_path / "src"
    namespace = src / "app" / "services"
    namespace.mkdir(parents=True)
    file_path = namespace / "query.py"
    file_path.write_text("")

    roots = engine._infer_source_roots([file_path], [str(src)])

    assert roots == [src.resolve()]


def test_source_roots_do_not_include_filesystem_root(tmp_path: Path) -> None:
    import piccolo_sql_guard.engine as engine

    file_path = tmp_path / "query.py"
    file_path.write_text("")

    roots = engine._infer_source_roots([file_path])

    assert file_path.parent.resolve() in roots
    assert all(root.parent != root for root in roots)


def test_module_analysis_is_shared_between_site_and_project_phases(monkeypatch) -> None:
    import piccolo_sql_guard.engine as engine

    observed_module_analysis_ids: list[int] = []
    call_site_calls = 0
    target_path = str((FIXTURES / "unsafe" / "ilike_fstring_builder.py").resolve())
    original_get_module_analysis = engine._get_module_analysis
    original_call_sites = engine.collect_call_sites

    def tracking_get_module_analysis(*args, **kwargs):
        analysis = original_get_module_analysis(*args, **kwargs)
        if analysis is not None and str(analysis.path.resolve()) == target_path:
            observed_module_analysis_ids.append(id(analysis))
        return analysis

    def counting_collect_call_sites(*args, **kwargs):
        nonlocal call_site_calls
        if len(args) >= 3 and args[2] == target_path:
            call_site_calls += 1
        return original_call_sites(*args, **kwargs)

    monkeypatch.setattr(engine, "_get_module_analysis", tracking_get_module_analysis)
    monkeypatch.setattr(engine, "collect_call_sites", counting_collect_call_sites)

    rules = get_rules(select=["PQS001", "PQS004"])
    result = run_engine(
        [FIXTURES / "unsafe" / "ilike_fstring_builder.py"], rules, Config()
    )

    assert not result.internal_errors
    assert any(d.rule_code == "PQS001" for d in result.diagnostics)
    assert any(d.rule_code == "PQS004" for d in result.diagnostics)
    assert observed_module_analysis_ids
    assert len(set(observed_module_analysis_ids)) == 1
    assert call_site_calls == 1
