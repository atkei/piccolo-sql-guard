from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import piccolo_sql_guard

FIXTURES = Path(__file__).parent.parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent.parent
SRC_ROOT = REPO_ROOT / "src"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{SRC_ROOT}{os.pathsep}{existing}" if existing else str(SRC_ROOT)
    )
    return subprocess.run(
        [sys.executable, "-m", "piccolo_sql_guard", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_unknown_select_code_is_config_error() -> None:
    result = _run(["--select", "PQS999", str(FIXTURES / "safe" / "literal_raw.py")])

    assert result.returncode == 2
    assert "unknown rule code" in result.stderr


def test_unknown_ignore_code_is_config_error() -> None:
    result = _run(["--ignore", "PQS999", str(FIXTURES / "safe" / "literal_raw.py")])

    assert result.returncode == 2
    assert "unknown rule code" in result.stderr


def test_package_version_matches_cli_and_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    result = _run(["--version"])

    assert pyproject["project"]["version"] == "0.1.0"
    assert piccolo_sql_guard.__version__ == "0.1.0"
    assert result.stdout.strip() == "piccolo-sql-guard 0.1.0"
