from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from pathlib import Path

from piccolo_sql_guard.analysis.ast_parser import ParseError, parse_file
from piccolo_sql_guard.analysis.call_graph import (
    build_reachable_call_graph,
    compute_all_summaries,
    compute_summaries_for_graph,
)
from piccolo_sql_guard.analysis.call_resolver import collect_call_sites
from piccolo_sql_guard.analysis.function_summary import FunctionSummary
from piccolo_sql_guard.analysis.piccolo_imports import (
    PiccoloScope,
    build_piccolo_scope,
)
from piccolo_sql_guard.analysis.project_index import ProjectIndex
from piccolo_sql_guard.analysis.visitors import CallSite
from piccolo_sql_guard.config import Config
from piccolo_sql_guard.models import Diagnostic
from piccolo_sql_guard.rules.base import ProjectRule, Rule


@dataclass
class EngineResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    internal_errors: list[str] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    timing: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)


@dataclass
class ModuleAnalysis:
    module_fqn: str
    path: Path
    tree: ast.Module
    piccolo_scope: PiccoloScope
    imported_table_receivers: set[str]
    call_sites_by_allowlist: dict[frozenset[str], list[CallSite]] = field(
        default_factory=dict
    )


@dataclass
class _EngineContext:
    index: ProjectIndex
    expanded_modules: set[str] = field(default_factory=set)
    module_analysis_by_path: dict[Path, ModuleAnalysis] = field(default_factory=dict)


def run_engine(
    files: list[Path],
    rules: list[Rule],
    config: Config,
    source_paths: list[str] | None = None,
) -> EngineResult:
    result = EngineResult()
    builder_allowlist = set(config.builder_allowlist)

    site_rules = [r for r in rules if not isinstance(r, ProjectRule)]
    proj_rules = [r for r in rules if isinstance(r, ProjectRule)]

    source_roots = _infer_source_roots(files, source_paths or [])
    context = _EngineContext(index=ProjectIndex(source_roots=source_roots))
    parse_error_paths: set[Path] = set()

    t_engine = time.perf_counter()

    t0 = time.perf_counter()
    if site_rules:
        for file_path in files:
            try:
                _analyze_file(
                    file_path,
                    site_rules,
                    config,
                    builder_allowlist,
                    result,
                    context,
                )
            except ParseError as e:
                result.parse_errors.append(str(e))
                parse_error_paths.add(file_path.resolve())
                result.files_scanned += 1
            except Exception as e:
                result.internal_errors.append(
                    f"internal error processing {file_path}: {e}"
                )
                result.files_scanned += 1
    else:
        for file_path in files:
            try:
                tree = parse_file(file_path)
                result.files_scanned += 1
                context.index.register_parsed_file(file_path, tree)
            except ParseError as e:
                result.parse_errors.append(str(e))
                parse_error_paths.add(file_path.resolve())
                result.files_scanned += 1
            except Exception as e:
                result.internal_errors.append(
                    f"internal error processing {file_path}: {e}"
                )
                result.files_scanned += 1
    result.timing["per_file"] = time.perf_counter() - t0

    if proj_rules:
        t1 = time.perf_counter()
        _analyze_project(
            files,
            proj_rules,
            config,
            builder_allowlist,
            result,
            context,
            parse_error_paths,
        )
        result.timing["project"] = time.perf_counter() - t1

    result.timing["total"] = time.perf_counter() - t_engine
    return result


def _infer_source_roots(
    files: list[Path],
    source_paths: list[str] | None = None,
) -> list[Path]:
    """Derive source roots from explicit scan paths and package boundaries."""
    explicit_roots = _roots_from_source_paths(source_paths or [])
    roots: set[Path] = set(explicit_roots)

    for path in files:
        leaf_parent = path.parent.resolve()

        package_root = _package_source_root(path)
        if package_root is not None:
            roots.add(package_root)
        elif not _is_under_any_root(path, explicit_roots):
            roots.add(leaf_parent)

    return sorted(_safe_source_roots(roots))


def _roots_from_source_paths(source_paths: list[str]) -> set[Path]:
    roots: set[Path] = set()
    for raw_path in source_paths:
        path = Path(raw_path)
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_file():
            roots.add(resolved.parent)
        elif resolved.is_dir():
            roots.add(resolved)
    return roots


def _package_source_root(path: Path) -> Path | None:
    candidate = path.parent.resolve()
    package_parent: Path | None = None
    while True:
        try:
            is_package = (candidate / "__init__.py").exists()
        except OSError:
            break
        if not is_package:
            break
        package_parent = candidate.parent
        candidate = candidate.parent
    return package_parent


def _is_under_any_root(path: Path, roots: set[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _safe_source_roots(roots: set[Path]) -> list[Path]:
    safe: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
            exists = resolved.exists()
        except OSError:
            continue
        if not exists or resolved.parent == resolved or resolved in seen:
            continue
        safe.append(resolved)
        seen.add(resolved)
    return safe


def _ensure_registered_files(
    files: list[Path],
    context: _EngineContext,
    skip_paths: set[Path],
) -> None:
    for file_path in files:
        if file_path.resolve() in skip_paths:
            continue
        context.index.register_file(file_path)


def _analyze_project(
    files: list[Path],
    proj_rules: list[ProjectRule],
    config: Config,
    builder_allowlist: set[str],
    result: EngineResult,
    context: _EngineContext,
    parse_error_paths: set[Path],
) -> None:
    try:
        _ensure_registered_files(files, context, parse_error_paths)
        _expand_project_index(context.index, context.expanded_modules)
        result.counters["functions_registered"] = len(
            context.index.iter_function_items()
        )
    except Exception as e:
        result.internal_errors.append(f"PQS004 project analysis failed: {e}")
        return

    pqs004_rules = [r for r in proj_rules if r.metadata.code == "PQS004"]
    other_proj_rules = [r for r in proj_rules if r.metadata.code != "PQS004"]
    pqs004_summaries: dict[str, FunctionSummary] = {}
    all_summaries: dict[str, FunctionSummary] | None = None

    try:
        if pqs004_rules:
            seed_fqns = _collect_pqs004_seed_fqns(
                context,
                config,
                builder_allowlist,
            )
            result.counters["seed_builders"] = len(seed_fqns)
            reachable_graph = build_reachable_call_graph(context.index, seed_fqns)
            result.counters["reachable_functions"] = len(reachable_graph)
            pqs004_summaries = compute_summaries_for_graph(
                context.index,
                reachable_graph,
                config.pqs004_max_iterations,
            )
            result.counters["summaries_computed"] = len(pqs004_summaries)

        if other_proj_rules:
            all_summaries = compute_all_summaries(
                context.index,
                config.pqs004_max_iterations,
            )
    except Exception as e:
        result.internal_errors.append(f"PQS004 project analysis failed: {e}")
        return

    for rule in proj_rules:
        try:
            if rule.metadata.code == "PQS004":
                result.diagnostics.extend(
                    rule.check_project(pqs004_summaries, context.index)
                )
            elif all_summaries is not None:
                result.diagnostics.extend(
                    rule.check_project(all_summaries, context.index)
                )
        except Exception as e:
            result.internal_errors.append(f"{rule.metadata.code} check failed: {e}")


def _collect_pqs004_seed_fqns(
    context: _EngineContext,
    config: Config,
    builder_allowlist: set[str],
) -> set[str]:
    seed_fqns: set[str] = set()

    for module_fqn in sorted(context.index.all_module_fqns()):
        analysis = _get_module_analysis(module_fqn, context, config)
        if analysis is None:
            continue
        if (
            not analysis.piccolo_scope.has_piccolo_imports()
            and not analysis.imported_table_receivers
        ):
            continue

        call_sites = _get_call_sites(analysis, builder_allowlist)
        for call_site in call_sites:
            for expr in _seed_exprs(call_site.template_expr, call_site.resolved_expr):
                for node in ast.walk(expr):
                    if not isinstance(node, ast.Call):
                        continue
                    callee_fqn = _resolve_call_fqn_for_seed(
                        node,
                        module_fqn,
                        call_site.enclosing_class,
                        context.index,
                    )
                    if (
                        callee_fqn is not None
                        and context.index.get_function(callee_fqn)
                    ):
                        seed_fqns.add(callee_fqn)

    return seed_fqns


def _filter_reachable_summaries(
    seed_fqns: set[str],
    summaries: dict[str, FunctionSummary],
) -> dict[str, FunctionSummary]:
    if not seed_fqns:
        return {}

    reachable = set(seed_fqns)
    worklist = list(sorted(seed_fqns, reverse=True))
    while worklist:
        fqn = worklist.pop()
        summary = summaries.get(fqn)
        if summary is None:
            continue
        for dep in sorted(summary.depends_on, reverse=True):
            if dep in summaries and dep not in reachable:
                reachable.add(dep)
                worklist.append(dep)

    return {fqn: summaries[fqn] for fqn in sorted(reachable)}


def _seed_exprs(
    template_expr: ast.expr,
    resolved_expr: ast.expr,
) -> tuple[ast.expr, ...]:
    if template_expr is resolved_expr:
        return (template_expr,)
    return (template_expr, resolved_expr)


def _resolve_call_fqn_for_seed(
    node: ast.Call,
    module_fqn: str,
    enclosing_class: str | None,
    index: ProjectIndex,
) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        binding = index.resolve_name(func.id, module_fqn)
        if binding is not None:
            imported = f"{binding.source_fqn}.{binding.original_name}"
            if index.get_function(imported) is not None:
                return imported
        local = f"{module_fqn}.{func.id}"
        if index.get_function(local) is not None:
            return local

    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        owner = func.value.id
        if owner in ("self", "cls") and enclosing_class is not None:
            method = f"{module_fqn}.{enclosing_class}.{func.attr}"
            if index.get_function(method) is not None:
                return method

        imported_owner = index.resolve_name(owner, module_fqn)
        if imported_owner is not None:
            imported_method = f"{imported_owner.source_fqn}.{func.attr}"
            if index.get_function(imported_method) is not None:
                return imported_method

        class_method = f"{module_fqn}.{owner}.{func.attr}"
        if index.get_function(class_method) is not None:
            return class_method

    return None


def _expand_project_index(
    index: ProjectIndex,
    processed: set[str] | None = None,
) -> None:
    """Best-effort expansion: register local modules referenced by imports."""
    if processed is None:
        processed = set()
    queue = index.all_module_fqns()
    while queue:
        module_fqn = queue.pop()
        if module_fqn in processed:
            continue
        processed.add(module_fqn)
        module = index.get_module(module_fqn)
        if module is None:
            continue

        import_module_fqns = {b.source_fqn for b in module.imports.bindings}
        import_module_fqns.update(module.imports.star_imports)

        for imported_fqn in sorted(import_module_fqns):
            registered = _register_module_if_local(index, imported_fqn)
            if registered is not None and registered not in processed:
                queue.append(registered)


def _register_module_if_local(index: ProjectIndex, module_fqn: str) -> str | None:
    if index.get_module(module_fqn) is not None:
        return module_fqn

    cached_path = index._local_module_path_cache.get(module_fqn)
    if cached_path is not None:
        return index.register_file(cached_path).fqn
    if module_fqn in index._local_module_path_cache:
        return None

    parts = module_fqn.split(".")
    for root in _iter_search_roots(index):
        py_path = root.joinpath(*parts).with_suffix(".py")
        if py_path.exists():
            index._local_module_path_cache[module_fqn] = py_path
            return index.register_file(py_path).fqn
        pkg_init = root.joinpath(*parts, "__init__.py")
        if pkg_init.exists():
            index._local_module_path_cache[module_fqn] = pkg_init
            return index.register_file(pkg_init).fqn

    index._local_module_path_cache[module_fqn] = None
    return None


def _iter_search_roots(index: ProjectIndex) -> list[Path]:
    """Search declared roots and nested package roots for import resolution."""
    if index._search_roots_cache is not None:
        return index._search_roots_cache

    roots: list[Path] = []
    seen: set[Path] = set()
    max_depth = 3

    def add_root(path: Path) -> bool:
        try:
            resolved = path.resolve()
            exists = resolved.exists()
        except OSError:
            return False
        if resolved not in seen and exists:
            roots.append(resolved)
            seen.add(resolved)
            return True
        return False

    def walk_children(root: Path, depth: int) -> None:
        if depth >= max_depth:
            return
        try:
            children = sorted(root.iterdir())
        except OSError:
            return
        for child in children:
            try:
                is_package_dir = child.is_dir() and (child / "__init__.py").exists()
            except OSError:
                continue
            if not is_package_dir:
                continue
            added = add_root(child)
            if added:
                walk_children(child, depth + 1)

    for root in index.source_roots:
        if add_root(root):
            walk_children(root, depth=0)

    index._search_roots_cache = roots
    return roots


def _collect_imported_table_receivers(
    index: ProjectIndex,
    module_fqn: str,
    config: Config,
) -> set[str]:
    module = index.get_module(module_fqn)
    if module is None:
        return set()

    receivers: set[str] = set()
    for binding in module.imports.bindings:
        source_module_fqns = _iter_local_module_fqns(index, binding.source_fqn)
        for source_module_fqn in source_module_fqns:
            imported_class_fqn = f"{source_module_fqn}.{binding.original_name}"
            if _is_piccolo_table_class(
                imported_class_fqn,
                index,
                config.piccolo_modules,
                frozenset(),
            ):
                receivers.add(binding.local_name)
                break
    return receivers


def _is_piccolo_module_name(module: str, piccolo_modules: list[str]) -> bool:
    return any(module == m or module.startswith(m + ".") for m in piccolo_modules)


def _is_piccolo_table_class(
    class_fqn: str,
    index: ProjectIndex,
    piccolo_modules: list[str],
    visited: frozenset[str],
) -> bool:
    if class_fqn in visited:
        return False
    visited = visited | {class_fqn}

    cls = index.get_class(class_fqn)
    if cls is None:
        return False

    module = index.get_module(cls.module_fqn)
    for base_name in cls.base_names:
        if base_name == "Table":
            return True

        if module is not None:
            imported = module.imports.lookup(base_name)
            if imported is not None:
                if (
                    imported.original_name == "Table"
                    and _is_piccolo_module_name(imported.source_fqn, piccolo_modules)
                ):
                    return True
                for source_module_fqn in _iter_local_module_fqns(
                    index, imported.source_fqn
                ):
                    imported_class_fqn = (
                        f"{source_module_fqn}.{imported.original_name}"
                    )
                    if _is_piccolo_table_class(
                        imported_class_fqn,
                        index,
                        piccolo_modules,
                        visited,
                    ):
                        return True

        same_module_base = f"{cls.module_fqn}.{base_name}"
        if _is_piccolo_table_class(
            same_module_base,
            index,
            piccolo_modules,
            visited,
        ):
            return True

    return False


def _iter_local_module_fqns(index: ProjectIndex, module_fqn: str) -> list[str]:
    """Resolve a logical import module to known local module FQNs."""
    resolved: list[str] = []
    seen: set[str] = set()

    def add(fqn: str) -> None:
        if fqn not in seen and index.get_module(fqn) is not None:
            resolved.append(fqn)
            seen.add(fqn)

    add(module_fqn)
    registered = _register_module_if_local(index, module_fqn)
    if registered is not None:
        add(registered)
    return resolved


def _get_module_analysis(
    module_fqn: str,
    context: _EngineContext,
    config: Config,
) -> ModuleAnalysis | None:
    module = context.index.get_module(module_fqn)
    if module is None:
        return None

    target = module.path.resolve()
    cached = context.module_analysis_by_path.get(target)
    if cached is not None:
        return cached

    _expand_project_index(context.index, context.expanded_modules)

    piccolo_scope = build_piccolo_scope(module.tree, config.piccolo_modules)
    imported_table_receivers = _collect_imported_table_receivers(
        context.index,
        module_fqn,
        config,
    )
    if imported_table_receivers:
        piccolo_scope.table_subclasses.update(imported_table_receivers)

    analysis = ModuleAnalysis(
        module_fqn=module_fqn,
        path=target,
        tree=module.tree,
        piccolo_scope=piccolo_scope,
        imported_table_receivers=imported_table_receivers,
    )
    context.module_analysis_by_path[target] = analysis
    return analysis


def _get_call_sites(
    analysis: ModuleAnalysis,
    builder_allowlist: set[str],
) -> list[CallSite]:
    key = frozenset(builder_allowlist)
    cached = analysis.call_sites_by_allowlist.get(key)
    if cached is not None:
        return cached

    call_sites = collect_call_sites(
        analysis.tree,
        analysis.piccolo_scope,
        str(analysis.path),
        set(key),
    )
    analysis.call_sites_by_allowlist[key] = call_sites
    return call_sites


def _analyze_file(
    file_path: Path,
    rules: list[Rule],
    config: Config,
    builder_allowlist: set[str],
    result: EngineResult,
    context: _EngineContext,
) -> None:
    tree = parse_file(file_path)
    result.files_scanned += 1
    module = context.index.register_parsed_file(file_path, tree)
    analysis = _get_module_analysis(module.fqn, context, config)
    if analysis is None:
        result.files_skipped += 1
        return

    if (
        not analysis.piccolo_scope.has_piccolo_imports()
        and not analysis.imported_table_receivers
    ):
        result.files_skipped += 1
        return

    call_sites = _get_call_sites(analysis, builder_allowlist)
    for call_site in call_sites:
        for rule in rules:
            diagnostic = rule.check(call_site)
            if diagnostic is not None:
                result.diagnostics.append(diagnostic)
