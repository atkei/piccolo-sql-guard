from __future__ import annotations

from piccolo_sql_guard.models import SqlClassification
from piccolo_sql_guard.rules.base import ClassificationRule, RuleMetadata


class PQS001(ClassificationRule):
    _kind = "raw"
    _triggers = frozenset({SqlClassification.UNSAFE_FSTRING})
    _metadata = RuleMetadata(
        code="PQS001",
        name="raw-sql-fstring",
        description="Reject f-strings passed into raw()",
    )
    _message = (
        "unsafe SQL f-string passed to raw(); "
        "use '{}' placeholders and separate bind values"
    )
