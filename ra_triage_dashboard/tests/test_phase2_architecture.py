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

        cycles: set[tuple[str, ...]] = set()
        for a, adeps in graph.items():
            for b in adeps:
                if b in graph and a in graph[b] and a < b:
                    cycles.add((a, b))
                for c in graph.get(b, ()):
                    if c in graph and a in graph[c] and a < b and a < c:
                        cycles.add((a, b, c))
        self.assertEqual(
            cycles,
            set(),
            f"Unexpected circular imports detected in app/: {sorted(cycles)}",
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


if __name__ == "__main__":
    unittest.main()
