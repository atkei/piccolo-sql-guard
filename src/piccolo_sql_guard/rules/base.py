from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from piccolo_sql_guard.analysis.visitors import CallSite
from piccolo_sql_guard.models import Diagnostic, Location, Severity, SqlClassification

if TYPE_CHECKING:
    from piccolo_sql_guard.analysis.function_summary import FunctionSummary
    from piccolo_sql_guard.analysis.project_index import ProjectIndex


@dataclass(frozen=True)
class RuleMetadata:
    code: str
    name: str
    description: str


class Rule(ABC):
    @property
    @abstractmethod
    def metadata(self) -> RuleMetadata: ...

    @abstractmethod
    def check(self, call_site: CallSite) -> Diagnostic | None: ...


class ProjectRule(Rule):
    """A rule that analyzes the full project call graph instead of call sites.

    Inherits from Rule so the registry returns a uniform list[Rule].
    The inherited check() is a no-op; check_project() carries the logic.
    """

    def check(self, call_site: CallSite) -> Diagnostic | None:
        return None

    @abstractmethod
    def check_project(
        self,
        summaries: dict[str, FunctionSummary],
        index: ProjectIndex,
    ) -> list[Diagnostic]: ...


class ClassificationRule(Rule):
    _kind: Literal["raw", "querystring"]
    _triggers: frozenset[SqlClassification]
    _metadata: RuleMetadata
    _message: str

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def check(self, call_site: CallSite) -> Diagnostic | None:
        if call_site.kind != self._kind:
            return None
        if call_site.classification not in self._triggers:
            return None

        node = call_site.resolved_expr
        return Diagnostic(
            location=Location(
                path=call_site.path,
                line=node.lineno,
                column=node.col_offset,
                end_line=node.end_lineno or node.lineno,
                end_column=node.end_col_offset or node.col_offset,
            ),
            rule_code=self._metadata.code,
            message=self._message,
            severity=Severity.ERROR,
        )
