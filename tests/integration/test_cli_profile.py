from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"
SRC_ROOT = Path(__file__).parent.parent.parent / "src"


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


# ---------------------------------------------------------------------------
# --profile flag: output shape
# ---------------------------------------------------------------------------


def test_profile_prints_to_stderr() -> None:
    result = _run(["--profile", str(FIXTURES / "unsafe" / "fstring_raw.py")])
    assert "Profile" in result.stderr
    assert "file enumeration" in result.stderr
    assert "per-file analysis" in result.stderr
    assert "total (engine)" in result.stderr


def test_profile_project_phase_shown_when_pqs004_active() -> None:
    result = _run(["--profile", str(FIXTURES / "unsafe" / "unsafe_builder_fn.py")])
    assert "project analysis" in result.stderr
    assert "reachable seeds" in result.stderr
    assert "reachable functions" in result.stderr
    assert "summaries computed" in result.stderr


def test_profile_project_phase_absent_when_only_site_rules() -> None:
    result = _run(
        [
            "--profile",
            "--select",
            "PQS001",
            str(FIXTURES / "unsafe" / "fstring_raw.py"),
        ]
    )
    assert "project analysis" not in result.stderr


def test_profile_does_not_affect_stdout_diagnostics() -> None:
    without = _run(["--format", "text", str(FIXTURES / "unsafe" / "fstring_raw.py")])
    with_profile = _run(
        [
            "--profile",
            "--format",
            "text",
            str(FIXTURES / "unsafe" / "fstring_raw.py"),
        ]
    )
    assert without.stdout == with_profile.stdout


def test_profile_exit_code_unchanged() -> None:
    without = _run([str(FIXTURES / "unsafe" / "fstring_raw.py")])
    with_profile = _run(["--profile", str(FIXTURES / "unsafe" / "fstring_raw.py")])
    assert without.returncode == with_profile.returncode


def test_profile_file_count_shown() -> None:
    result = _run(["--profile", str(FIXTURES / "unsafe" / "fstring_raw.py")])
    assert "1 file" in result.stderr


# ---------------------------------------------------------------------------
# Timing values are non-negative floats
# ---------------------------------------------------------------------------


def test_profile_timing_values_are_numeric() -> None:
    result = _run(["--profile", str(FIXTURES / "unsafe" / "fstring_raw.py")])
    phases = ("enumeration", "analysis", "total")
    for line in result.stderr.splitlines():
        if ":" in line and "s" in line and any(ph in line for ph in phases):
            part = line.split(":")[1].strip().split("s")[0].strip()
            val = float(part)
            assert val >= 0.0
