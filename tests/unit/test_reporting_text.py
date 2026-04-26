from piccolo_sql_guard.models import Diagnostic, Location, Severity
from piccolo_sql_guard.reporting.text import render_text


def make_diagnostic(
    path: str = "file.py",
    line: int = 1,
    col: int = 0,
    rule: str = "PQS001",
    msg: str = "test message",
) -> Diagnostic:
    return Diagnostic(
        location=Location(
            path=path, line=line, column=col, end_line=line, end_column=col + 10
        ),
        rule_code=rule,
        message=msg,
        severity=Severity.ERROR,
    )


def test_empty() -> None:
    assert render_text([]) == ""


def test_single_diagnostic() -> None:
    d = make_diagnostic()
    result = render_text([d])
    assert result == "file.py:1:0: PQS001 test message"


def test_multiple_diagnostics() -> None:
    d1 = make_diagnostic(line=1)
    d2 = make_diagnostic(line=2, rule="PQS002", msg="other message")
    result = render_text([d1, d2])
    assert "file.py:1:0: PQS001 test message" in result
    assert "file.py:2:0: PQS002 other message" in result


def test_output_format() -> None:
    d = make_diagnostic(
        path="src/app.py", line=42, col=17, rule="PQS003", msg="bad sql"
    )
    result = render_text([d])
    assert result == "src/app.py:42:17: PQS003 bad sql"
