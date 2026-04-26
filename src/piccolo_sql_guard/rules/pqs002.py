from __future__ import annotations

from piccolo_sql_guard.models import SqlClassification
from piccolo_sql_guard.rules.base import ClassificationRule, RuleMetadata


class PQS002(ClassificationRule):
    _kind = "raw"
    _triggers = frozenset(
        {
            SqlClassification.UNSAFE_CONCAT,
            SqlClassification.UNSAFE_PERCENT_FORMAT,
            SqlClassification.UNSAFE_DOT_FORMAT,
        }
    )
    _metadata = RuleMetadata(
        code="PQS002",
        name="raw-sql-string-formatting",
        description=(
            "Reject concatenation, % formatting, and .format() passed into raw()"
        ),
    )
    _message = (
        "dynamically formatted SQL passed to raw(); "
        "keep SQL tokens fixed and bind values separately"
    )
