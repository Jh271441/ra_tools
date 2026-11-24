"""Static and runtime architecture guardrails locking P0-P2 invariants permanently.

Enforces:
- Zero cyclic SCCs across `app/`
- Zero function-local `app.*` imports
- Zero cross-repo `ra_api` imports
- 100% pure `app/domain/` (no DB/HTTP/subprocess/OS/upper-layer imports)
- Strictly downward layer dependencies (infra -> domain -> clients -> repositories -> services -> api)
- Explicit Pydantic `response_model` on every `/api/*` FastAPI route
- Read-only `GET /api/dashboard/versions` (zero write-on-GET)
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# Locked at 0 after P2 completion — never regress.
MAX_NONTRIVIAL_SCCS = 0
MAX_SCC_SIZE = 0
MAX_LOCAL_APP_IMPORTS = 0
MAX_RA_API_IMPORTS = 0

_FORBIDDEN_DOMAIN_TOP_MODULES = {
    "sqlalchemy",
    "httpx",
    "requests",
    "subprocess",
    "os",
    "redis",
    "rq",
    "fastapi",
    "starlette",
    "alembic",
    "fcntl",
}

_FORBIDDEN_DOMAIN_APP_PREFIXES = (
    "app.infra",
    "app.clients",
    "app.repositories",
    "app.services",
    "app.api",
    "app.database",
    "app.models",
    "app.config",
    "app.security",
)


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
    assert (
        len(local_imports) <= MAX_LOCAL_APP_IMPORTS
    ), f"Unexpected function-local app imports ({len(local_imports)}): {local_imports}"
    assert (
        len(ra_api_imports) <= MAX_RA_API_IMPORTS
    ), f"Unexpected cross-repo ra_api imports ({len(ra_api_imports)}): {ra_api_imports}"


def test_domain_layer_is_pure() -> None:
    domain_dir = APP_ROOT / "domain"
    domain_files = sorted(domain_dir.glob("*.py"))
    assert domain_files, "Expected pure modules under app/domain/"
    violations: list[str] = []
    for path in domain_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in _FORBIDDEN_DOMAIN_TOP_MODULES or node.module.startswith(
                    _FORBIDDEN_DOMAIN_APP_PREFIXES
                ):
                    violations.append(f"{path.name}:{node.lineno} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in _FORBIDDEN_DOMAIN_TOP_MODULES or alias.name.startswith(
                        _FORBIDDEN_DOMAIN_APP_PREFIXES
                    ):
                        violations.append(f"{path.name}:{node.lineno} imports {alias.name}")
    assert not violations, f"Pure domain layer violations: {violations}"


def test_layer_dependencies_are_strictly_downward() -> None:
    modules = _collect_app_modules()
    graph, _, _ = _build_dependency_graph(modules)
    forbidden: dict[str, tuple[str, ...]] = {
        "infra": ("clients", "repositories", "services", "api"),
        "domain": ("infra", "clients", "repositories", "services", "api", "database", "models"),
        "clients": ("repositories", "services", "api"),
        "repositories": ("services", "api"),
    }
    violations: list[str] = []
    for src, targets in sorted(graph.items()):
        layer = src.split(".")[0]
        banned = forbidden.get(layer)
        if not banned:
            continue
        for dst in sorted(targets):
            dst_layer = dst.split(".")[0]
            if dst_layer in banned:
                violations.append(f"{src} -> {dst}")
    assert not violations, f"Upward layer dependency violations: {violations}"


def test_every_api_route_declares_response_model() -> None:
    from app.main import app

    missing: list[str] = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            if route.response_model is None:
                methods = ",".join(sorted(route.methods or ()))
                missing.append(f"{methods} {route.path}")
    assert not missing, f"API routes missing explicit response_model: {missing}"


def test_versions_get_is_strictly_read_only(monkeypatch) -> None:
    from app.api import routes
    from app.database import Base, get_db
    from app.main import app
    from app.models import Version

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    monkeypatch.setattr(
        routes,
        "load_versions_config",
        lambda: {
            "current_version": "gen4-release-20261120",
            "compare_versions": ["gen4-release-20261113"],
            "versions": {
                "gen4-release-20261113": {"label": "release20261113", "sim_job_id": 1001},
                "gen4-release-20261120": {"label": "release20261120", "sim_job_id": 1002},
            },
        },
    )
    monkeypatch.setattr(
        routes,
        "business_context",
        lambda _db: {
            "business_current_version": "gen4-release-20261120",
            "business_metrics": None,
            "business_status": "pending_simulation",
            "business_reason": "",
            "metrics": {},
        },
    )
    monkeypatch.setattr(routes, "history_kpis", lambda _db: [])
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        resp = client.get("/api/dashboard/versions")
        assert resp.status_code == 200
        body = resp.json()
        assert [v["version_key"] for v in body["versions"]] == [
            "gen4-release-20261113",
            "gen4-release-20261120",
        ]
        # Zero writes on GET: versions table must remain empty.
        assert db.scalar(select(func.count()).select_from(Version)) == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()
