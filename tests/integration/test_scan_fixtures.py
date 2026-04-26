from pathlib import Path

from piccolo_sql_guard.config import Config
from piccolo_sql_guard.engine import run_engine
from piccolo_sql_guard.rules.registry import get_rules

FIXTURES = Path(__file__).parent.parent / "fixtures"


def scan(path: Path, select: list[str] | None = None) -> list[str]:
    config = Config()
    rules = get_rules(select=select)
    result = run_engine([path], rules, config)
    return [d.rule_code for d in result.diagnostics]


# ---------------------------------------------------------------------------
# Safe fixtures – must produce zero violations
# ---------------------------------------------------------------------------


def test_safe_literal_raw_no_violations() -> None:
    codes = scan(FIXTURES / "safe" / "literal_raw.py")
    assert codes == []


def test_safe_placeholder_binding_no_violations() -> None:
    codes = scan(FIXTURES / "safe" / "placeholder_binding.py")
    assert codes == []


def test_safe_allowlisted_builder_no_violations() -> None:
    codes = scan(FIXTURES / "safe" / "allowlisted_builder.py")
    assert codes == []


# ---------------------------------------------------------------------------
# Unsafe fixtures – PQS001
# ---------------------------------------------------------------------------


def test_fstring_raw_pqs001() -> None:
    codes = scan(FIXTURES / "unsafe" / "fstring_raw.py", select=["PQS001"])
    assert codes.count("PQS001") >= 2  # direct + indirect


def test_imported_table_fstring_raw_pqs001() -> None:
    """Imported Table subclass receiver should be detected for site rules."""
    codes = scan(
        FIXTURES / "unsafe" / "imported_table_fstring_raw.py",
        select=["PQS001"],
    )
    assert "PQS001" in codes


def test_fstring_not_pqs002() -> None:
    codes = scan(FIXTURES / "unsafe" / "fstring_raw.py", select=["PQS002"])
    assert codes == []


def test_ilike_direct_fstring_pqs001() -> None:
    """f-string with ILIKE search value passed directly to raw() triggers PQS001."""
    codes = scan(FIXTURES / "unsafe" / "ilike_fstring_builder.py", select=["PQS001"])
    assert "PQS001" in codes


def test_ilike_placeholder_no_pqs001() -> None:
    """ILIKE with {} placeholder binding must not trigger PQS001."""
    codes = scan(FIXTURES / "safe" / "ilike_placeholder.py", select=["PQS001"])
    assert codes == []


# ---------------------------------------------------------------------------
# Unsafe fixtures – PQS002
# ---------------------------------------------------------------------------


def test_concat_raw_pqs002() -> None:
    codes = scan(FIXTURES / "unsafe" / "concat_raw.py", select=["PQS002"])
    assert "PQS002" in codes


def test_percent_format_pqs002() -> None:
    codes = scan(FIXTURES / "unsafe" / "percent_format_raw.py", select=["PQS002"])
    assert "PQS002" in codes


def test_dot_format_pqs002() -> None:
    codes = scan(FIXTURES / "unsafe" / "dot_format_raw.py", select=["PQS002"])
    assert "PQS002" in codes


# ---------------------------------------------------------------------------
# Unsafe fixtures – PQS003
# ---------------------------------------------------------------------------


def test_querystring_fstring_pqs003() -> None:
    codes = scan(FIXTURES / "unsafe" / "querystring_fstring.py", select=["PQS003"])
    assert "PQS003" in codes


def test_querystring_concat_pqs003() -> None:
    codes = scan(FIXTURES / "unsafe" / "querystring_fstring.py", select=["PQS003"])
    assert codes.count("PQS003") >= 2


# ---------------------------------------------------------------------------
# Non-Piccolo fixtures – must produce zero violations
# ---------------------------------------------------------------------------


def test_django_like_raw_not_flagged() -> None:
    codes = scan(FIXTURES / "non_piccolo" / "django_like_raw.py")
    assert codes == []


def test_unrelated_querystring_not_flagged() -> None:
    codes = scan(FIXTURES / "non_piccolo" / "unrelated_querystring.py")
    assert codes == []


# ---------------------------------------------------------------------------
# Diagnostic details
# ---------------------------------------------------------------------------


def test_diagnostic_has_location() -> None:
    from piccolo_sql_guard.config import Config
    from piccolo_sql_guard.engine import run_engine
    from piccolo_sql_guard.rules.registry import get_rules

    config = Config()
    rules = get_rules(select=["PQS001"])
    result = run_engine([FIXTURES / "unsafe" / "fstring_raw.py"], rules, config)

    assert result.diagnostics
    d = result.diagnostics[0]
    assert d.line > 0
    assert d.column >= 0
    assert d.path.endswith("fstring_raw.py")
    assert "PQS001" in d.rule_code


def test_json_output_structure() -> None:
    import json

    from piccolo_sql_guard.reporting.json import render_json

    config = Config()
    rules = get_rules(select=["PQS001"])
    result = run_engine([FIXTURES / "unsafe" / "fstring_raw.py"], rules, config)
    output = json.loads(render_json(result.diagnostics))

    assert isinstance(output, list)
    assert len(output) > 0
    required = {
        "path",
        "line",
        "column",
        "end_line",
        "end_column",
        "rule_code",
        "message",
        "severity",
    }
    assert required.issubset(output[0].keys())
