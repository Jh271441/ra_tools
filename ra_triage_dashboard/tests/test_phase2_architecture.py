from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fastapi import FastAPI

from ra_triage_dashboard.app.core.container import AppContainer
from ra_triage_dashboard.app.core.dataset_label_config import collapse_dataset_labels
from ra_triage_dashboard.app.core.deps import get_db, get_settings
from ra_triage_dashboard.app.core.version_review_config import get_version_review_weights
from ra_triage_dashboard.app.main import app as main_app
from ra_triage_dashboard.app.routers import cases as cases_router
from ra_triage_dashboard.app.routers import version_datasets as version_datasets_router
from ra_triage_dashboard.app.schemas import (
    AssignmentNameSuggestionResponse,
    CampaignAllocationResponse,
    DailyCronResponse,
    SessionResponse,
    SystemStatusResponse,
    VersionWorkbenchResponse,
    WorkSplitListResponse,
)
from ra_triage_dashboard.scripts.export_openapi import build_openapi_schema


class Phase2ArchitectureTests(unittest.TestCase):
    def test_zero_circular_imports_in_backend_app(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app"
        graph: dict[str, set[str]] = {}
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).with_suffix("")
            mod = ".".join(rel.parts)
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            tree = ast.parse(path.read_text(encoding="utf-8"))
            deps: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level > 0:
                    parts = mod.split(".")
                    base = (
                        parts[: len(parts) - (node.level - 1)]
                        if path.name == "__init__.py"
                        else parts[: max(0, len(parts) - node.level)]
                    )
                    target = ".".join(
                        [*base, *(node.module.split(".") if node.module else [])]
                    )
                    if target and target != mod:
                        deps.add(target)
            graph[mod] = deps

        # Detect strongly connected components (cycles of any length).
        index = 0
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        sccs: list[list[str]] = []

        def strongconnect(node: str) -> None:
            nonlocal index
            indices[node] = lowlink[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)
            for neighbor in sorted(graph.get(node, ())):
                if neighbor not in graph:
                    continue
                if neighbor not in indices:
                    strongconnect(neighbor)
                    lowlink[node] = min(lowlink[node], lowlink[neighbor])
                elif neighbor in on_stack:
                    lowlink[node] = min(lowlink[node], indices[neighbor])
            if lowlink[node] == indices[node]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(comp))

        for mod_name in sorted(graph):
            if mod_name not in indices:
                strongconnect(mod_name)
        self.assertEqual(
            sccs,
            [],
            f"Unexpected circular import SCCs detected in app/: {sccs}",
        )

    def test_app_container_mounted_and_dependency_overrides_work(self) -> None:
        self.assertIsInstance(main_app.state.container, AppContainer)

        mini = FastAPI()
        mini.include_router(version_datasets_router.router)
        fake_db = SimpleNamespace(
            list_version_datasets=lambda: [
                {
                    "id": "release-20261113-odd2",
                    "name": "1113 复核集",
                    "release_family": "20261113",
                    "total": 10,
                    "targets": 4,
                    "states": {"published": 10},
                    "assigned": {"alice": 4},
                }
            ]
        )
        mini.dependency_overrides[get_db] = lambda: fake_db
        mini.dependency_overrides[get_settings] = lambda: SimpleNamespace(
            ra_auto_triage_root=Path("/tmp")
        )

        async def _call_asgi(path: str) -> tuple[int, dict]:
            messages: list[dict] = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(msg):
                messages.append(msg)

            await mini(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "method": "GET",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "headers": [],
                    "scheme": "http",
                    "server": ("127.0.0.1", 80),
                    "client": ("127.0.0.1", 12345),
                },
                receive,
                send,
            )
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
            return status, json.loads(raw.decode("utf-8"))

        status, body = asyncio.run(_call_asgi("/api/version-datasets"))
        self.assertEqual(status, 200)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["id"], "release-20261113-odd2")

    def test_cases_router_preserves_reexported_handlers_and_route_order(self) -> None:
        for attr in (
            "suggest_assignment_name",
            "list_case_work_splits",
            "review_work_split_options",
            "get_case_work_split",
            "reassign_case_work_item",
            "reviewers",
        ):
            self.assertTrue(hasattr(cases_router, attr), f"Missing compat export {attr}")
        paths = [getattr(r, "path", "") for r in cases_router.router.routes]
        self.assertLess(
            paths.index("/api/cases/work-splits"),
            paths.index("/api/cases/{issue_id}"),
        )
        self.assertLess(
            paths.index("/api/cases/work-splits/{split_id}"),
            paths.index("/api/cases/{issue_id}"),
        )

    def test_externalized_version_review_weights_and_dataset_label_unions(self) -> None:
        self.assertEqual(
            get_version_review_weights("20261030"),
            (("liangxianghui", 4), ("jasperchen", 3), ("hejianmo", 3)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "weights.json"
            cfg.write_text(
                json.dumps(
                    {
                        "default": [["alice", 2], ["bob", 1]],
                        "by_family": {"20261120": [["charlie", 5]]},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                get_version_review_weights("20261120", config_file=cfg),
                (("charlie", 5),),
            )
            self.assertEqual(
                get_version_review_weights("20261127", config_file=cfg),
                (("alice", 2), ("bob", 1)),
            )

        collapsed = collapse_dataset_labels(
            ["1009-2026-10-15", "review-2026-10-15-extra", "0508"],
            {
                "1009-2026-10-15": "1009 2026-10-15",
                "review-2026-10-15-extra": "每日复核 2026-10-15 补齐",
                "0508": "0508",
            },
        )
        self.assertEqual(collapsed, ["1009 2026-10-15", "0508"])

    def test_openapi_schema_exports_typed_core_contracts_and_preserves_extra_fields(
        self,
    ) -> None:
        schema = build_openapi_schema()
        self.assertIn("paths", schema)
        schemas = schema.get("components", {}).get("schemas", {})
        for expected in (
            "HealthResponse",
            "SessionResponse",
            "ChangeRevisionResponse",
            "BaselinesResponse",
            "DashboardConfigResponse",
            "SystemStatusResponse",
            "DailyCronResponse",
            "WorkSplitListResponse",
            "CampaignAllocationResponse",
            "AllocationPreviewResponse",
            "AssignmentNameSuggestionResponse",
            "VersionDatasetListResponse",
            "VersionWorkbenchResponse",
            "CaseListResponse",
            "CaseDetailResponse",
        ):
            self.assertIn(expected, schemas, f"Missing OpenAPI schema {expected}")

        # Verify extra='allow' preserves dynamic fields cleanly on both Pydantic v1 and v2
        sample = SystemStatusResponse(
            overall={"status": "healthy", "problems": []},
            custom_runtime_flag="kept",
        )
        dumped = sample.model_dump() if hasattr(sample, "model_dump") else sample.dict()
        self.assertEqual(dumped["custom_runtime_flag"], "kept")
        self.assertEqual(dumped["overall"]["status"], "healthy")

        # Sanity-validate minimal payloads for key models
        self.assertEqual(
            AssignmentNameSuggestionResponse(suggestion="test", source="rule").source,
            "rule",
        )
        self.assertEqual(DailyCronResponse(observed_at=1.0).refresh_seconds, 30)
        self.assertEqual(SessionResponse(authenticated=True, username="u").username, "u")
        self.assertEqual(WorkSplitListResponse(items=[]).lifecycle, "current")
        self.assertEqual(CampaignAllocationResponse(campaign_id="c1").campaign_id, "c1")
        self.assertEqual(VersionWorkbenchResponse(dataset_id="d1").dataset_id, "d1")

    def test_phase2b_repositories_openapi_coverage_and_decomposed_db_modules(self) -> None:
        from ra_triage_dashboard.app.core.repositories import (
            CampaignRepository,
            CaseRepository,
            DbSessionFactory,
            WorkSplitRepository,
        )

        container = main_app.state.container
        self.assertIsInstance(container.session_factory, DbSessionFactory)
        self.assertIsInstance(container.cases_repo, CaseRepository)
        self.assertIsInstance(container.campaigns_repo, CampaignRepository)
        self.assertIsInstance(container.work_splits_repo, WorkSplitRepository)

        # Verify decomposed db_parts modules stay below 1,500 lines each
        db_parts = Path(__file__).resolve().parents[1] / "app" / "db_parts"
        for name in (
            "campaign_common.py",
            "campaign_lifecycle.py",
            "campaign_legacy.py",
            "campaign_progress.py",
            "campaigns.py",
            "cases.py",
            "work_splits.py",
        ):
            line_count = len((db_parts / name).read_text(encoding="utf-8").splitlines())
            self.assertLess(line_count, 1500, f"{name} exceeded 1500 lines ({line_count})")

        # Verify expanded OpenAPI typed coverage (>= 150 typed API ops, >= 90 schemas)
        spec = build_openapi_schema()
        schemas = spec.get("components", {}).get("schemas", {})
        self.assertGreaterEqual(len(schemas), 90)
        typed_ops = 0
        for path, methods in spec.get("paths", {}).items():
            if not path.startswith("/api/"):
                continue
            for method, op in methods.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete"):
                    continue
                r200 = (op.get("responses") or {}).get("200", {})
                content = (r200.get("content") or {}).get("application/json", {})
                if "$ref" in (content.get("schema") or {}):
                    typed_ops += 1
        self.assertGreaterEqual(typed_ops, 150)

    def test_phase4b_cross_repo_adapter_portability_and_archive(self) -> None:
        from ra_triage_dashboard.app.integrations.ra_auto_triage_adapter import (
            ensure_ra_auto_triage_on_path,
        )

        app_root = Path(__file__).resolve().parents[1] / "app"
        adapter_rel = Path("integrations") / "ra_auto_triage_adapter.py"
        sys_path_violations: list[str] = []
        hardcoded_volume_violations: list[str] = []
        allowed_volume_files = {
            Path("settings.py"),
            Path("cron_version_source.py"),
            adapter_rel,
        }
        for py_path in sorted(app_root.rglob("*.py")):
            rel = py_path.relative_to(app_root)
            text = py_path.read_text(encoding="utf-8")
            if rel != adapter_rel and ("sys.path.insert" in text or "sys.path.append" in text):
                sys_path_violations.append(str(rel))
            if rel not in allowed_volume_files and "/volume/home/workspace" in text:
                hardcoded_volume_violations.append(str(rel))

        self.assertEqual(
            sys_path_violations,
            [],
            f"Direct sys.path mutation forbidden outside ra_auto_triage_adapter.py: {sys_path_violations}",
        )
        self.assertEqual(
            hardcoded_volume_violations,
            [],
            f"Hardcoded /volume/home/workspace forbidden outside settings/adapter: {hardcoded_volume_violations}",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                ensure_ra_auto_triage_on_path(root, require_vlm=True)
            (root / "vlm").mkdir()
            resolved = ensure_ra_auto_triage_on_path(root, require_vlm=True)
            self.assertEqual(resolved, root.resolve())

        archive_dir = Path(__file__).resolve().parents[1] / "scripts" / "archive"
        self.assertTrue(archive_dir.is_dir(), "scripts/archive/ directory must exist")
        self.assertTrue(
            any(archive_dir.iterdir()),
            "scripts/archive/ must contain archived s3-s6 milestone scripts",
        )


if __name__ == "__main__":
    unittest.main()
