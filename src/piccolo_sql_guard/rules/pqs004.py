from __future__ import annotations

from typing import TYPE_CHECKING

from piccolo_sql_guard.models import Diagnostic, Location, Severity
from piccolo_sql_guard.rules.base import ProjectRule, RuleMetadata

if TYPE_CHECKING:
    from piccolo_sql_guard.analysis.function_summary import FunctionSummary
    from piccolo_sql_guard.analysis.project_index import ProjectIndex


class PQS004(ProjectRule):
    @property
    def metadata(self) -> RuleMetadata:
        return RuleMetadata(
            code="PQS004",
            name="unsafe-sql-token-builder",
            description=(
                "Reject uncontrolled SQL tokens in helper builders "
                "(identifiers, operators, ORDER BY fragments)"
            ),
        )

    def check_project(
        self,
        summaries: dict[str, FunctionSummary],
        index: ProjectIndex,
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for fqn in sorted(summaries):
            summary = summaries[fqn]
            unsafe_sinks = [
                s for s in summary.token_sinks if not s.provenance.is_safe()
            ]
            if not unsafe_sinks:
                continue
            fn_entry = index.get_function(fqn)
            if fn_entry is None:
                continue
            mod = index.get_module(fn_entry.module_fqn)
            if mod is None:
                continue
            file_path = str(mod.path)
            fn_name = fqn.rsplit(".", 1)[-1]
            for sink in unsafe_sinks:
                end_line = sink.location.end_line or sink.location.line
                end_column = sink.location.end_column or sink.location.column
                diagnostics.append(
                    Diagnostic(
                        location=Location(
                            path=file_path,
                            line=sink.location.line,
                            column=sink.location.column,
                            end_line=end_line,
                            end_column=end_column,
                        ),
                        rule_code="PQS004",
                        message=(
                            f"unsafe SQL token `{sink.origin_expr}` in builder"
                            f" `{fn_name}` — "
                            "use Literal type or bool to constrain this parameter"
                        ),
                        severity=Severity.ERROR,
                    )
                )
        return diagnostics
