"""Static architecture guardrails to track and lock refactoring progress.

Ratchet bounds downward as P1/P2 land until SCC == 0, local imports == 0,
and cross-repo ra_api imports == 0.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# Current phase ratchets (tightened to 0 at P2 completion).
MAX_NONTRIVIAL_SCCS = 1
MAX_SCC_SIZE = 25
MAX_LOCAL_APP_IMPORTS = 140
MAX_RA_API_IMPORTS = 25


def _collect_app_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        name = ".".join(parts) if parts else "__root__"
        modules[name] = path
    return modules


def _build_dependency_graph(
    modules: dict[str, Path],
) -> tuple[dict[str, set[str]], list[str], list[str]]:
    graph: dict[str, set[str]] = collections.defaultdict(set)
    local_imports: list[str] = []
    ra_api_imports: list[str] = []

    for mod, path in sorted(modules.items()):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "ra_api" or node.module.startswith("ra_api."):
                    ra_api_imports.append(f"{mod}:{node.lineno} -> {node.module}")
                elif node.module.startswith("app."):
                    target = node.module[4:]
                    if target in modules:
                        graph[mod].add(target)
                    for alias in node.names:
                        candidate = f"{target}.{alias.name}"
                        if candidate in modules:
                            graph[mod].add(candidate)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ra_api" or alias.name.startswith("ra_api."):
                        ra_api_imports.append(f"{mod}:{node.lineno} -> {alias.name}")
                    elif alias.name.startswith("app."):
                        target = alias.name[4:]
                        if target in modules:
                            graph[mod].add(target)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.ImportFrom)
                        and sub.module
                        and sub.module.startswith("app.")
                    ):
                        local_imports.append(f"{mod}:{sub.lineno} in {node.name}() -> {sub.module}")

    return graph, local_imports, ra_api_imports


def _tarjan_sccs(nodes: list[str], graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = lowlink[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(sorted(scc))

    for node in sorted(nodes):
        if node not in indices:
            strongconnect(node)
    return sccs


def test_architecture_coupling_ratchets() -> None:
    modules = _collect_app_modules()
    graph, local_imports, ra_api_imports = _build_dependency_graph(modules)
    sccs = _tarjan_sccs(list(modules), graph)
    max_scc = max((len(c) for c in sccs), default=0)
    assert len(sccs) <= MAX_NONTRIVIAL_SCCS, f"Unexpected cyclic SCCs: {sccs}"
    assert max_scc <= MAX_SCC_SIZE, f"SCC grew to {max_scc}: {sccs}"
    assert len(local_imports) <= MAX_LOCAL_APP_IMPORTS, f"Local imports grew ({len(local_imports)})"
    assert len(ra_api_imports) <= MAX_RA_API_IMPORTS, f"ra_api imports grew ({len(ra_api_imports)})"
