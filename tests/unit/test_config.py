from pathlib import Path

import pytest

from piccolo_sql_guard.config import load_config


def test_default_config() -> None:
    config = load_config(None)
    assert config.piccolo_modules == ["piccolo"]
    assert config.output_format == "text"
    assert config.select == []
    assert config.ignore == []


def test_load_pyproject_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "pyproject.toml"
    config_file.write_text(
        "[tool.piccolo-sql-guard]\n"
        'select = ["PQS001"]\n'
        'exclude = [".venv"]\n'
        'piccolo_modules = ["piccolo", "mypkg.piccolo"]\n'
    )
    config = load_config(config_file)
    assert config.select == ["PQS001"]
    assert ".venv" in config.exclude
    assert "mypkg.piccolo" in config.piccolo_modules


def test_load_standalone_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "piccolo-sql-guard.toml"
    config_file.write_text('select = ["PQS002", "PQS003"]\n')
    config = load_config(config_file)
    assert config.select == ["PQS002", "PQS003"]


def test_invalid_toml_raises(tmp_path: Path) -> None:
    config_file = tmp_path / "piccolo-sql-guard.toml"
    config_file.write_text("this is not toml ][[\n")
    with pytest.raises(ValueError, match="invalid TOML"):
        load_config(config_file)


def test_missing_explicit_file_raises(tmp_path: Path) -> None:
    # Explicitly pointing --config at a missing file must not silently fall
    # back to defaults — the user expected that file to be loaded.
    with pytest.raises(ValueError, match="cannot read config"):
        load_config(tmp_path / "nonexistent.toml")


def test_builder_allowlist_loaded(tmp_path: Path) -> None:
    config_file = tmp_path / "piccolo-sql-guard.toml"
    config_file.write_text('builder_allowlist = ["build_*_sql"]\n')
    config = load_config(config_file)
    assert "build_*_sql" in config.builder_allowlist


def test_max_iterations_rejects_bool(tmp_path: Path) -> None:
    # ``bool`` is a subclass of ``int`` — must not be silently coerced to 1.
    config_file = tmp_path / "piccolo-sql-guard.toml"
    config_file.write_text("pqs004_max_iterations = true\n")
    with pytest.raises(ValueError, match="pqs004_max_iterations"):
        load_config(config_file)


def test_max_iterations_rejects_zero(tmp_path: Path) -> None:
    config_file = tmp_path / "piccolo-sql-guard.toml"
    config_file.write_text("pqs004_max_iterations = 0\n")
    with pytest.raises(ValueError, match="pqs004_max_iterations"):
        load_config(config_file)


def test_max_iterations_accepts_positive_int(tmp_path: Path) -> None:
    config_file = tmp_path / "piccolo-sql-guard.toml"
    config_file.write_text("pqs004_max_iterations = 10\n")
    config = load_config(config_file)
    assert config.pqs004_max_iterations == 10
