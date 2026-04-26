# piccolo-sql-guard

A community-maintained static checker for unsafe Piccolo raw SQL construction.

## What it checks

| Rule | Name | Description |
|------|------|-------------|
| `PQS001` | `raw-sql-fstring` | Flags f-strings passed into `Table.raw()` |
| `PQS002` | `raw-sql-string-formatting` | Flags concatenation, `%` formatting, and `.format()` passed into `Table.raw()` |
| `PQS003` | `querystring-unsafe-template` | Flags the same unsafe patterns for `QueryString()` |
| `PQS004` | `unsafe-sql-token-builder` | Flags uncontrolled SQL tokens in helper builders |

### PQS004 — unsafe SQL token builders

PQS004 performs cross-function analysis to find SQL builder functions that
interpolate parameters of unsafe type and are reachable from a Piccolo raw SQL
sink.  A parameter is **safe** when its type
annotation constrains it to a finite set of values:

- `Literal["ASC", "DESC"]` — explicitly enumerated strings
- `bool` — Boolean (maps to e.g. `" WHERE active"` / `""`)
- `int` / `float` — numeric constants
- A local `Enum` / `StrEnum` subclass

A plain `str` parameter is **unsafe** and triggers PQS004.

```python
# PQS004 fires — sort_col is unconstrained str
def build(sort_col: str) -> str:
    return f"SELECT * FROM my_model ORDER BY {sort_col}"

# Safe — Literal constrains the set of allowed values
def build(direction: Literal["ASC", "DESC"]) -> str:
    return f"SELECT * FROM my_model ORDER BY id {direction}"
```

PQS004 also follows simple helper-call chains and common string-building
patterns such as f-strings, string concatenation, and `str.join()` over literal
containers.

## Quick start

```bash
pip install piccolo-sql-guard
piccolo-sql-guard src/
```

## Usage

```bash
piccolo-sql-guard [PATH ...]                  # scan paths
piccolo-sql-guard --format json src/          # JSON output
piccolo-sql-guard --select PQS001,PQS002 src/ # enable specific rules
piccolo-sql-guard --ignore PQS004 src/        # disable specific rules
piccolo-sql-guard --statistics src/           # print file/violation counts
piccolo-sql-guard --profile src/              # print per-phase timing
piccolo-sql-guard --version
```

Unknown rule codes passed to `--select` or `--ignore` are treated as
configuration errors so CI does not accidentally run with an empty ruleset.

## Development

This project uses `uv` for the local development environment and lockfile.
The package supports Python 3.11 through 3.14.

```bash
uv sync --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev mypy src
```

## Configuration

`piccolo-sql-guard.toml` or `pyproject.toml`:

```toml
[tool.piccolo-sql-guard]
include = ["src"]
exclude = ["migrations", ".venv"]
select = ["PQS001", "PQS002", "PQS003", "PQS004"]
ignore = []
builder_allowlist = ["build_*_sql"]
piccolo_modules = ["piccolo"]
output_format = "text"
pqs004_max_iterations = 5   # fixed-point iteration cap for recursive builders
```

### `builder_allowlist`

A list of glob patterns matching builder function names that are assumed safe and
excluded from PQS004 analysis.  Use this for third-party or generated builders you
cannot annotate.

### `pqs004_max_iterations`

Maximum number of fixed-point iterations for recursive or mutually-recursive
builder groups (default: `5`).  Increase if you have deeply recursive builders;
decrease if scan time is a concern.

## Limitations

`piccolo-sql-guard` is a best-effort static checker.  Dynamic dispatch, complex
container mutation, runtime imports, and values assembled outside the scanned
source tree may be treated as unknown or missed.  Treat a clean run as a lint
signal, not as proof that every raw SQL path is injection-safe.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | No violations |
| `1` | Violations found |
| `2` | Config or usage error |
| `3` | Internal checker error |
