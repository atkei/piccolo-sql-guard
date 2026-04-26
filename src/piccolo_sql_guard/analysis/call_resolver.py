from __future__ import annotations

import ast

from piccolo_sql_guard.analysis.piccolo_imports import PiccoloScope
from piccolo_sql_guard.analysis.visitors import CallSite, CallSiteCollector


def collect_call_sites(
    tree: ast.Module,
    scope: PiccoloScope,
    path: str,
    builder_allowlist: set[str],
) -> list[CallSite]:
    collector = CallSiteCollector(scope, path, builder_allowlist)
    collector.visit(tree)
    return collector.call_sites
