from __future__ import annotations

from piccolo_sql_guard.models import SqlClassification
from piccolo_sql_guard.rules.base import ClassificationRule, RuleMetadata


class PQS003(ClassificationRule):
    _kind = "querystring"
    _triggers = frozenset(
        {
            SqlClassification.UNSAFE_FSTRING,
            SqlClassification.UNSAFE_CONCAT,
            SqlClassification.UNSAFE_PERCENT_FORMAT,
            SqlClassification.UNSAFE_DOT_FORMAT,
        }
    )
    _metadata = RuleMetadata(
        code="PQS003",
        name="querystring-unsafe-template",
        description="Reject unsafe template construction for QueryString()",
    )
    _message = (
        "QueryString template was built unsafely; "
        "avoid interpolated SQL and pass values separately"
    )
