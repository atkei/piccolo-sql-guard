from __future__ import annotations

import fnmatch
from pathlib import Path

from piccolo_sql_guard.config import DEFAULT_EXCLUDES


def enumerate_python_files(
    paths: list[str],
    exclude_patterns: list[str] | None = None,
) -> list[Path]:
    if exclude_patterns is None:
        exclude_patterns = list(DEFAULT_EXCLUDES)

    results: set[Path] = set()
    for path_str in paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix == ".py":
                results.add(path)
        elif path.is_dir():
            _scan_dir(path, exclude_patterns, results, set())

    return sorted(results)


def _scan_dir(
    directory: Path,
    exclude_patterns: list[str],
    results: set[Path],
    seen: set[Path],
) -> None:
    try:
        real = directory.resolve()
    except OSError:
        return
    if real in seen:
        return
    seen.add(real)

    try:
        entries = list(directory.iterdir())
    except OSError:
        return

    for entry in entries:
        if _is_excluded(entry, exclude_patterns):
            continue
        if entry.is_symlink() and entry.is_dir():
            _scan_dir(entry, exclude_patterns, results, seen)
        elif entry.is_file() and entry.suffix == ".py":
            results.add(entry)
        elif entry.is_dir():
            _scan_dir(entry, exclude_patterns, results, seen)


def _is_excluded(path: Path, patterns: list[str]) -> bool:
    name = path.name
    posix = path.as_posix()
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if "/" in pattern and fnmatch.fnmatch(posix, pattern):
            return True
    return False
