from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".venv",
    "venv",
    ".git",
    "node_modules",
    "__pycache__",
    "*.egg-info",
    ".eggs",
    "dist",
    "build",
)

_LIST_KEYS: tuple[str, ...] = (
    "include",
    "exclude",
    "select",
    "ignore",
    "builder_allowlist",
    "piccolo_modules",
)

_ALLOWED_FORMATS = {"text", "json"}


@dataclass
class Config:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    select: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    builder_allowlist: list[str] = field(default_factory=list)
    piccolo_modules: list[str] = field(default_factory=lambda: ["piccolo"])
    output_format: str = "text"
    pqs004_max_iterations: int = 5


def load_config(config_path: Path | None = None) -> Config:
    explicit = config_path is not None
    if config_path is None:
        config_path = _find_config()

    if config_path is None:
        return Config()

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        if explicit:
            raise ValueError(f"cannot read config {config_path}: {e}") from e
        return Config()
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"invalid TOML in {config_path}: {e}") from e

    section = _select_section(data, config_path)
    if section is None:
        return Config()

    return _build_config(section, config_path)


def _select_section(
    data: dict[str, object], config_path: Path
) -> dict[str, object] | None:
    if config_path.name == "pyproject.toml":
        tool = data.get("tool")
        if isinstance(tool, dict):
            section = tool.get("piccolo-sql-guard")
            if isinstance(section, dict):
                return section
        return None

    tool = data.get("tool")
    if isinstance(tool, dict):
        section = tool.get("piccolo-sql-guard")
        if isinstance(section, dict):
            return section
    return data


def _build_config(section: dict[str, object], config_path: Path) -> Config:
    config = Config()
    for key in _LIST_KEYS:
        if key not in section:
            continue
        value = section[key]
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(
                f"invalid config in {config_path}: '{key}' must be a list of strings"
            )
        setattr(config, key, list(value))

    if "output_format" in section:
        value = section["output_format"]
        if not isinstance(value, str) or value not in _ALLOWED_FORMATS:
            raise ValueError(
                f"invalid config in {config_path}: 'output_format' must be one of "
                f"{sorted(_ALLOWED_FORMATS)}"
            )
        config.output_format = value

    if "pqs004_max_iterations" in section:
        value = section["pqs004_max_iterations"]
        # ``bool`` is a subclass of ``int``; reject it explicitly so that
        # ``pqs004_max_iterations = true`` does not silently become ``1``.
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(
                f"invalid config in {config_path}: "
                "'pqs004_max_iterations' must be a positive integer"
            )
        config.pqs004_max_iterations = value

    return config


def _find_config() -> Path | None:
    current = Path.cwd()
    while True:
        for name in ("piccolo-sql-guard.toml", "pyproject.toml"):
            candidate = current / name
            if candidate.exists():
                return candidate
        parent = current.parent
        # Stop at git root or filesystem root.
        if (current / ".git").exists() or parent == current:
            break
        current = parent
    return None
