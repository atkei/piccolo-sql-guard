import pytest

from piccolo_sql_guard.rules.registry import get_rules


def test_all_rules_returned_by_default() -> None:
    rules = get_rules()
    codes = {r.metadata.code for r in rules}
    assert {"PQS001", "PQS002", "PQS003", "PQS004"} == codes


def test_select_filter() -> None:
    rules = get_rules(select=["PQS001"])
    codes = {r.metadata.code for r in rules}
    assert codes == {"PQS001"}


def test_ignore_filter() -> None:
    rules = get_rules(ignore=["PQS001"])
    codes = {r.metadata.code for r in rules}
    assert "PQS001" not in codes
    assert "PQS002" in codes


def test_unknown_select_code_raises() -> None:
    with pytest.raises(ValueError, match="unknown rule code"):
        get_rules(select=["PQS999"])


def test_unknown_ignore_code_raises() -> None:
    with pytest.raises(ValueError, match="unknown rule code"):
        get_rules(ignore=["PQS999"])


def test_select_takes_precedence_over_none() -> None:
    rules_all = get_rules(select=None)
    rules_default = get_rules()
    assert len(rules_all) == len(rules_default)


def test_empty_select_means_all() -> None:
    rules = get_rules(select=None, ignore=None)
    assert len(rules) == 4


def test_each_rule_has_metadata() -> None:
    for rule in get_rules():
        assert rule.metadata.code.startswith("PQS")
        assert rule.metadata.name
        assert rule.metadata.description
