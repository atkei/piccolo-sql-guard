from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SqlClassification(StrEnum):
    SAFE_LITERAL = "SAFE_LITERAL"
    SAFE_BUILDER_CALL = "SAFE_BUILDER_CALL"
    UNSAFE_FSTRING = "UNSAFE_FSTRING"
    UNSAFE_CONCAT = "UNSAFE_CONCAT"
    UNSAFE_PERCENT_FORMAT = "UNSAFE_PERCENT_FORMAT"
    UNSAFE_DOT_FORMAT = "UNSAFE_DOT_FORMAT"
    UNKNOWN_DYNAMIC = "UNKNOWN_DYNAMIC"


class Severity(StrEnum):
    ERROR = "error"


@dataclass(frozen=True)
class Location:
    path: str
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class Diagnostic:
    location: Location
    rule_code: str
    message: str
    severity: Severity = Severity.ERROR
    symbol: str | None = None

    @property
    def path(self) -> str:
        return self.location.path

    @property
    def line(self) -> int:
        return self.location.line

    @property
    def column(self) -> int:
        return self.location.column

    @property
    def end_line(self) -> int:
        return self.location.end_line

    @property
    def end_column(self) -> int:
        return self.location.end_column
