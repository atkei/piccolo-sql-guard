import json

from piccolo_sql_guard.models import Diagnostic, Location, Severity
from piccolo_sql_guard.reporting.json import render_json


def make_diagnostic(
    path: str = "file.py",
    line: int = 1,
    col: int = 0,
    rule: str = "PQS001",
    msg: str = "test",
) -> Diagnostic:
    return Diagnostic(
        location=Location(
            path=path, line=line, column=col, end_line=line, end_column=col + 5
        ),
        rule_code=rule,
        message=msg,
        severity=Severity.ERROR,
    )


def test_empty_list() -> None:
    result = json.loads(render_json([]))
    assert result == []


def test_required_fields_present() -> None:
    d = make_diagnostic()
    result = json.loads(render_json([d]))
    assert len(result) == 1
    item = result[0]
    assert item["path"] == "file.py"
    assert item["line"] == 1
    assert item["column"] == 0
    assert item["end_line"] == 1
    assert item["end_column"] == 5
    assert item["rule_code"] == "PQS001"
    assert item["message"] == "test"
    assert item["severity"] == "error"


def test_symbol_included_when_set() -> None:
    d = Diagnostic(
        location=Location("f.py", 1, 0, 1, 5),
        rule_code="PQS001",
        message="msg",
        symbol="my_func",
    )
    result = json.loads(render_json([d]))
    assert result[0]["symbol"] == "my_func"


def test_symbol_omitted_when_none() -> None:
    d = make_diagnostic()
    result = json.loads(render_json([d]))
    assert "symbol" not in result[0]


def test_multiple_diagnostics() -> None:
    diagnostics = [make_diagnostic(line=i, rule=f"PQS00{i}") for i in range(1, 4)]
    result = json.loads(render_json(diagnostics))
    assert len(result) == 3
    assert result[0]["rule_code"] == "PQS001"
