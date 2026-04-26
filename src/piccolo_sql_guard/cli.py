from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from piccolo_sql_guard import __version__
from piccolo_sql_guard.config import load_config
from piccolo_sql_guard.engine import EngineResult, run_engine
from piccolo_sql_guard.exit_codes import (
    EXIT_CONFIG_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
    EXIT_VIOLATIONS,
)
from piccolo_sql_guard.filesystem import enumerate_python_files
from piccolo_sql_guard.reporting.json import render_json
from piccolo_sql_guard.reporting.text import render_text
from piccolo_sql_guard.rules.registry import get_rules


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.version:
        print(f"piccolo-sql-guard {__version__}")
        sys.exit(EXIT_OK)

    try:
        config_path = Path(args.config) if args.config else None
        config = load_config(config_path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_CONFIG_ERROR)

    if args.format:
        config.output_format = args.format
    if args.select:
        config.select = [c.strip() for c in args.select.split(",")]
    if args.ignore:
        config.ignore = [c.strip() for c in args.ignore.split(",")]

    try:
        rules = get_rules(
            select=config.select or None,
            ignore=config.ignore or None,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_CONFIG_ERROR)

    paths = args.paths or config.include or ["."]

    t_enum = time.perf_counter()
    files = enumerate_python_files(paths, config.exclude)
    enum_elapsed = time.perf_counter() - t_enum

    result = run_engine(files, rules, config)

    diagnostics = sorted(
        result.diagnostics,
        key=lambda d: (d.path, d.line, d.column),
    )

    if config.output_format == "json":
        output = render_json(diagnostics)
    else:
        output = render_text(diagnostics)

    if args.output:
        # Always create the file the user asked for, even with zero
        # diagnostics — callers grep the result path and should not have
        # to care whether text/json behave differently on empty output.
        payload = output + "\n" if output else ""
        Path(args.output).write_text(payload, encoding="utf-8")
    elif output:
        print(output)

    for err in result.parse_errors:
        print(f"error: {err}", file=sys.stderr)
    for err in result.internal_errors:
        print(f"internal error: {err}", file=sys.stderr)

    if args.statistics:
        print(
            f"\n{result.files_scanned} files scanned, "
            f"{len(diagnostics)} violation(s) found",
            file=sys.stderr,
        )

    if args.profile:
        _print_profile(enum_elapsed, result, file_count=len(files))

    if result.internal_errors:
        sys.exit(EXIT_INTERNAL_ERROR)
    if diagnostics or result.parse_errors:
        sys.exit(EXIT_VIOLATIONS)
    sys.exit(EXIT_OK)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="piccolo-sql-guard",
        description="Static checker for unsafe Piccolo raw SQL construction",
    )
    parser.add_argument(
        "paths", nargs="*", metavar="PATH", help="Files or directories to scan"
    )
    parser.add_argument("--config", metavar="PATH", help="Config file path")
    parser.add_argument(
        "--format", choices=["text", "json"], help="Output format (default: text)"
    )
    parser.add_argument("--output", metavar="PATH", help="Write output to file")
    parser.add_argument(
        "--select", metavar="CODES", help="Comma-separated rule codes to enable"
    )
    parser.add_argument(
        "--ignore", metavar="CODES", help="Comma-separated rule codes to disable"
    )
    parser.add_argument(
        "--statistics", action="store_true", help="Print scan statistics"
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Print per-phase timing summary to stderr",
    )
    return parser


def _print_profile(
    enum_elapsed: float,
    result: EngineResult,
    file_count: int,
) -> None:
    timing = result.timing
    counters = result.counters
    per_file = timing.get("per_file", 0.0)
    project = timing.get("project", 0.0)
    total = timing.get("total", 0.0)
    width = 22
    err = sys.stderr
    sep = f"  {'':-<{width + 12}}"
    print("", file=err)
    print("Profile", file=err)
    print(
        f"  {'file enumeration':<{width}}: {enum_elapsed:7.3f}s  ({file_count} files)",
        file=err,
    )
    print(f"  {'per-file analysis':<{width}}: {per_file:7.3f}s  (PQS001-003)", file=err)
    if project > 0.0:
        print(f"  {'project analysis':<{width}}: {project:7.3f}s  (PQS004)", file=err)
        seeds = counters.get("seed_builders")
        if seeds is not None:
            print(f"  {'reachable seeds':<{width}}: {seeds}", file=err)
        reachable = counters.get("reachable_functions")
        functions_registered = counters.get("functions_registered")
        if reachable is not None and functions_registered is not None:
            print(
                f"  {'reachable functions':<{width}}: "
                f"{reachable} / {functions_registered}",
                file=err,
            )
        summaries = counters.get("summaries_computed")
        if summaries is not None:
            print(f"  {'summaries computed':<{width}}: {summaries}", file=err)
    print(sep, file=err)
    print(f"  {'total (engine)':<{width}}: {total:7.3f}s", file=err)
