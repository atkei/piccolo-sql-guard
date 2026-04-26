from __future__ import annotations

from piccolo_sql_guard.rules.base import Rule
from piccolo_sql_guard.rules.pqs001 import PQS001
from piccolo_sql_guard.rules.pqs002 import PQS002
from piccolo_sql_guard.rules.pqs003 import PQS003
from piccolo_sql_guard.rules.pqs004 import PQS004

_ALL_RULES: list[type[Rule]] = [PQS001, PQS002, PQS003, PQS004]


def get_rule_codes() -> frozenset[str]:
    return frozenset(cls().metadata.code for cls in _ALL_RULES)


def get_rules(
    select: list[str] | None = None,
    ignore: list[str] | None = None,
) -> list[Rule]:
    rules: list[Rule] = [cls() for cls in _ALL_RULES]
    known_codes = {r.metadata.code for r in rules}

    _validate_codes("select", select, known_codes)
    _validate_codes("ignore", ignore, known_codes)

    if select:
        rules = [r for r in rules if r.metadata.code in select]

    if ignore:
        rules = [r for r in rules if r.metadata.code not in ignore]

    return rules


def _validate_codes(
    option_name: str,
    codes: list[str] | None,
    known_codes: set[str],
) -> None:
    if not codes:
        return

    unknown = sorted({code for code in codes if code not in known_codes})
    if unknown:
        known = ", ".join(sorted(known_codes))
        requested = ", ".join(unknown)
        raise ValueError(
            f"unknown rule code(s) in {option_name}: {requested} "
            f"(known: {known})"
        )
