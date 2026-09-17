from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import labeling


class LabelingActivationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = Database(self.root / "activation.sqlite")
        self.database.init()
        self.tasks = {}
        self.revisions = {}
        for scope, status in (("active", "active"), ("shadow", "shadow"), ("paused", "paused")):
            issue_id = f"cn-{scope}"
            self.database.upsert_issues(
                [{"issue_id": issue_id, "gt_label": "正确触发"}],
                source="test", replace_gt=True, baseline_scope=scope,
            )
            self.set_scope(scope, status)
            workset = self.database.create_review_workset(
                baseline_scope=scope, issue_ids=[issue_id], created_by="admin",
            )
            task = self.database.create_labeling_task(
                workset_id=workset["id"],
                assignments=[{"name": "alice", "issue_ids": [issue_id]}],
                created_by="admin", seed=1, reviewers_per_issue=1, overlap_ratio=0,
            )
            self.tasks[scope] = task["id"]
            self.revisions[scope] = self.database.create_label_revision(
                issue_id=issue_id, task_id=task["id"],
                expected_output="误触发", tags=[], evidence_gaps=[],
                rationale="label evidence", is_excluded=False,
                author="alice", author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=None,
                attachments=[{
                    "id": f"attachment-{scope}", "original_name": "evidence.png",
                    "stored_name": "evidence.png", "media_type": "image/png",
                    "size_bytes": 4, "width": 1, "height": 1, "sha256": "a" * 64,
                }],
            )
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.object(labeling, "database", self.database))
        patches.enter_context(patch.object(
            labeling, "resolve_request_baseline_scopes",
            side_effect=lambda raw, **kwargs: (raw or "active").split(","),
        ))
        patches.enter_context(patch.object(
            labeling, "_labeling_actor", return_value=("alice", "kylin_ticket", True),
        ))

    def set_scope(self, scope: str, status: str) -> None:
        self.database.set_labeling_scope_state(
            baseline_scope=scope, status=status, policy_version="test-v1",
            source_inventory_sha256="a" * 64, updated_by="test",
        )

    def request(self, body: dict | None = None) -> Request:
        async def receive():
            return {"type": "http.request", "body": json.dumps(body or {}).encode()}

        return Request({"type": "http", "headers": [], "query_string": b""}, receive)

    def preview(self, scope: str) -> dict:
        return self.database.create_label_gt_export_preview(
            baseline_scopes=[scope], created_by="alice",
            created_by_source="kylin_ticket", created_by_verified=True,
        )

    async def test_inactive_selection_returns_no_tasks_cases_or_candidates(self) -> None:
        # An empty scope list has historically meant "all" for task storage.
        self.assertEqual(len(self.database.list_labeling_tasks([])), 3)
        for scope in ("shadow", "paused"):
            with self.subTest(scope=scope):
                tasks = await labeling.list_labeling_tasks(self.request(), baselines=scope)
                cases = await labeling.list_labeling_cases(self.request(), baselines=scope)
                candidates = await labeling.get_gt_candidates(self.request(), baselines=scope)
                for result in (tasks, cases, candidates):
                    self.assertEqual(result["items"], [])
                self.assertEqual(cases["total"], 0)
                self.assertEqual(candidates["ready_count"], 0)

    async def test_mixed_selection_returns_only_active_data(self) -> None:
        request = self.request()
        selection = "active,shadow,paused"
        tasks = await labeling.list_labeling_tasks(request, baselines=selection)
        cases = await labeling.list_labeling_cases(request, baselines=selection)
        candidates = await labeling.get_gt_candidates(request, baselines=selection)
        self.assertEqual([task["id"] for task in tasks["items"]], [self.tasks["active"]])
        self.assertEqual([case["issue_id"] for case in cases["items"]], ["cn-active"])
        self.assertEqual([item["issue_id"] for item in candidates["items"]], ["cn-active"])

    async def test_task_id_cannot_bypass_active_dataset_selection(self) -> None:
        for selected_scope in ("active", "shadow"):
            with self.subTest(selected_scope=selected_scope):
                with self.assertRaises(HTTPException) as raised:
                    await labeling.list_labeling_cases(
                        self.request(), baselines=selected_scope, task_id=self.tasks["shadow"],
                    )
                self.assertEqual(raised.exception.status_code, 404)
        self.set_scope("shadow", "active")
        with self.assertRaises(HTTPException) as raised:
            await labeling.list_labeling_cases(
                self.request(), baselines="active", task_id=self.tasks["shadow"],
            )
        self.assertEqual(raised.exception.status_code, 404)
        result = await labeling.list_labeling_cases(
            self.request(), baselines="active", task_id=self.tasks["active"],
        )
        self.assertEqual([item["issue_id"] for item in result["items"]], ["cn-active"])

    async def test_inactive_detail_and_revision_write_are_rejected(self) -> None:
        for scope in ("shadow", "paused"):
            for operation in (labeling.get_labeling_case, labeling.create_label_revision):
                with self.subTest(scope=scope, operation=operation.__name__):
                    with self.assertRaises(HTTPException) as raised:
                        await operation(f"cn-{scope}", self.request())
                    self.assertEqual(raised.exception.status_code, 409)

    async def test_attachment_requires_its_own_dataset_to_be_active(self) -> None:
        with patch.object(labeling, "settings", SimpleNamespace(review_attachments_dir=self.root)), patch.object(Path, "is_file", return_value=True):
            for scope in ("shadow", "paused"):
                with self.subTest(scope=scope):
                    with self.assertRaises(HTTPException) as raised:
                        await labeling.get_label_attachment(f"attachment-{scope}")
                    self.assertEqual(raised.exception.status_code, 409)
            response = await labeling.get_label_attachment("attachment-active")
            self.assertEqual(response.media_type, "image/png")
            self.assertEqual(response.headers["cache-control"], "private, no-cache")
            self.set_scope("active", "paused")
            with self.assertRaises(HTTPException) as raised:
                await labeling.get_label_attachment("attachment-active")
            self.assertEqual(raised.exception.status_code, 409)

    async def test_export_preview_rejects_inactive_and_missing_batches(self) -> None:
        for scope in ("shadow", "paused"):
            batch = self.preview(scope)
            with self.subTest(scope=scope):
                with self.assertRaises(HTTPException) as raised:
                    await labeling.get_gt_export_preview(batch["id"])
                self.assertEqual(raised.exception.status_code, 409)
        batch = self.preview("active")
        result = await labeling.get_gt_export_preview(batch["id"])
        self.assertEqual(result["preview"]["item_count"], 1)
        with self.assertRaises(HTTPException) as raised:
            await labeling.get_gt_export_preview("missing")
        self.assertEqual(raised.exception.status_code, 404)

    async def test_paused_export_rejected_before_validation_can_mutate_batch(self) -> None:
        batch = self.preview("active")
        self.set_scope("active", "paused")
        with patch.object(self.database, "validate_label_gt_export_batch") as validate, patch.object(self.database, "mark_label_gt_exported") as mark:
            with self.assertRaises(HTTPException) as raised:
                await labeling.export_gt_candidates(batch["id"], self.request())
            self.assertEqual(raised.exception.status_code, 409)
            validate.assert_not_called()
            mark.assert_not_called()
        self.assertEqual(self.database.get_label_gt_export_batch(batch["id"])["status"], "preview")

    async def test_inactive_export_creation_rejected_without_writing_batch(self) -> None:
        with patch.object(self.database, "create_label_gt_export_preview") as create:
            with self.assertRaises(HTTPException) as raised:
                await labeling.create_gt_export_preview(self.request({"baselines": "shadow"}))
            self.assertEqual(raised.exception.status_code, 409)
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
