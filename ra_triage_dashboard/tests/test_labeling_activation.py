from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import case_annotations, case_comments, labeling
from ra_triage_dashboard.app.support import annotations as annotation_support
from ra_triage_dashboard.app.support import catalogs as catalog_support


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
            self.database.apply_gt_sync_snapshot(
                scope=scope,
                rows=[{"issue_id": issue_id, "gt_label": "正确触发"}],
                source_name="Trail",
                source_view_id=1000,
                source_field="ra_merge_result",
                trigger="test",
                requested_by="tester",
                requested_by_source="test",
                requested_by_verified=False,
                expected_issue_ids=[issue_id],
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
        patches.enter_context(patch.object(
            labeling, "_require_labeling_admin", new=AsyncMock(return_value=None),
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
                        await labeling.get_label_attachment(
                            f"attachment-{scope}", self.request()
                        )
                    self.assertEqual(raised.exception.status_code, 409)
            response = await labeling.get_label_attachment(
                "attachment-active", self.request()
            )
            self.assertEqual(response.media_type, "image/png")
            self.assertEqual(response.headers["cache-control"], "private, no-cache")
            self.set_scope("active", "paused")
            with self.assertRaises(HTTPException) as raised:
                await labeling.get_label_attachment("attachment-active", self.request())
            self.assertEqual(raised.exception.status_code, 409)

    async def test_export_preview_rejects_inactive_and_missing_batches(self) -> None:
        for scope in ("shadow", "paused"):
            batch = self.preview(scope)
            with self.subTest(scope=scope):
                with self.assertRaises(HTTPException) as raised:
                    await labeling.get_gt_export_preview(batch["id"], self.request())
                self.assertEqual(raised.exception.status_code, 409)
        batch = self.preview("active")
        result = await labeling.get_gt_export_preview(batch["id"], self.request())
        self.assertEqual(result["preview"]["item_count"], 1)
        with self.assertRaises(HTTPException) as raised:
            await labeling.get_gt_export_preview("missing", self.request())
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


class LegacyWriteHandoverTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = Database(self.root / "handover.sqlite")
        self.database.init()
        self.database.upsert_issues(
            [{"issue_id": "cn-migrated", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="migrated",
        )
        self.database.upsert_issues(
            [{"issue_id": "cn-legacy", "gt_label": "正确触发"},
             {"issue_id": "cn-elsewhere", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="elsewhere",
        )
        self.database.set_labeling_scope_state(
            baseline_scope="migrated", status="active", policy_version="test-v1",
            source_inventory_sha256="a" * 64, updated_by="test",
        )
        rows = [
            {"issue_id": issue_id, "model_label": "正确触发"}
            for issue_id in ("cn-migrated", "cn-legacy", "cn-elsewhere")
        ]
        self.run_a, _ = self.database.import_model_run(
            name="run-a", source_name="run-a.json", source_sha256="a" * 64,
            metadata={}, rows=rows,
        )
        self.run_b, _ = self.database.import_model_run(
            name="run-b", source_name="run-b.json", source_sha256="b" * 64,
            metadata={}, rows=rows,
        )
        patches = ExitStack()
        self.addCleanup(patches.close)
        for module in (case_annotations, case_comments):
            patches.enter_context(patch.object(module, "database", self.database))
        patches.enter_context(patch.object(annotation_support, "database", self.database))
        patches.enter_context(patch.object(catalog_support, "database", self.database))
        patches.enter_context(patch.object(
            annotation_support,
            "settings",
            SimpleNamespace(dchat_notifications_enabled=False),
        ))
        patches.enter_context(patch.object(
            annotation_support,
            "_action_actor",
            return_value=("alice", "kylin_ticket", True),
        ))
        patches.enter_context(patch.object(
            annotation_support, "_review_tag_catalog", return_value=[]
        ))
        patches.enter_context(patch.object(case_comments, "settings", SimpleNamespace(
            dchat_notifications_enabled=False, comment_attachments_dir=self.root,
        )))

    def request(self, body: dict | None = None) -> Request:
        async def receive():
            return {"type": "http.request", "body": json.dumps(body or {}).encode()}

        return Request({"type": "http", "headers": [], "query_string": b""}, receive)

    async def test_old_annotation_entries_reject_migrated_scope(self) -> None:
        with patch.object(case_annotations, "_create_annotation_record") as create:
            for issue_id in ("cn-migrated", "missing"):
                with self.subTest(issue_id=issue_id):
                    with self.assertRaises(HTTPException) as raised:
                        await case_annotations.create_annotation(issue_id, self.request())
                    expected = 409 if issue_id == "cn-migrated" else 404
                    self.assertEqual(raised.exception.status_code, expected)
            create.assert_not_called()
            with self.assertRaises(HTTPException) as raised:
                await case_annotations.create_annotation("cn-legacy", self.request())
            self.assertEqual(raised.exception.status_code, 400)
            create.assert_not_called()

    async def test_active_scope_run_annotations_allow_json_and_multipart(self) -> None:
        json_result = await case_annotations.create_annotation(
            "cn-migrated",
            self.request({
                "model_run_id": self.run_a["id"],
                "expected_output": "误触发",
                "note": "run A review",
                "author": "alice",
            }),
        )
        attachment = {
            "id": "review-attachment",
            "original_name": "review.png",
            "stored_name": "review.png",
            "media_type": "image/png",
            "size_bytes": 4,
            "width": 1,
            "height": 1,
            "sha256": "c" * 64,
        }
        with patch.object(
            case_annotations,
            "_store_review_attachments",
            return_value=([attachment], [self.root / "review.png"]),
        ):
            multipart_result = await case_annotations.create_annotation_with_attachments(
                "cn-migrated",
                self.request(),
                payload=json.dumps({
                    "model_run_id": self.run_b["id"],
                    "expected_output": "正确触发",
                    "note": "run B review",
                    "author": "alice",
                }),
                attachments=[],
            )

        self.assertEqual(json_result["annotation"]["model_run_id"], self.run_a["id"])
        self.assertEqual(multipart_result["annotation"]["model_run_id"], self.run_b["id"])
        run_a_case = self.database.list_cases(
            baseline_scopes=["migrated"], model_run_id=self.run_a["id"], page_size=10
        )["items"][0]
        run_b_case = self.database.list_cases(
            baseline_scopes=["migrated"], model_run_id=self.run_b["id"], page_size=10
        )["items"][0]
        self.assertEqual(run_a_case["annotation"]["note"], "run A review")
        self.assertEqual(run_b_case["annotation"]["note"], "run B review")

    async def test_active_scope_no_run_rejects_before_annotation_attachment_storage(self) -> None:
        with patch.object(case_annotations, "_store_review_attachments") as store:
            with self.assertRaises(HTTPException) as raised:
                await case_annotations.create_annotation_with_attachments(
                    "cn-migrated",
                    self.request(),
                    payload=json.dumps({"note": "legacy label write"}),
                    attachments=[],
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("Case 标注工作台", str(raised.exception.detail))
        store.assert_not_called()

    async def test_old_delete_rejects_migrated_scope(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await case_annotations.delete_annotation("cn-migrated", 1, self.request())
        self.assertEqual(raised.exception.status_code, 409)
        with self.assertRaises(HTTPException) as raised:
            await case_annotations.delete_annotation("cn-legacy", 1, self.request())
        self.assertEqual(raised.exception.status_code, 404)

    async def test_old_comment_entries_reject_migrated_scope(self) -> None:
        with patch.object(case_comments, "_action_actor", return_value=("alice", "kylin_ticket", True)), patch.object(
            case_comments, "extract_review_mentions", return_value=[]
        ):
            with self.assertRaises(HTTPException) as raised:
                await case_comments.create_review_comment("cn-migrated", self.request({"body": "讨论"}))
            self.assertEqual(raised.exception.status_code, 409)
            with self.assertRaises(HTTPException) as inactive_raised:
                await case_comments.create_review_comment(
                    "cn-legacy", self.request({"body": "讨论"})
                )
            self.assertEqual(inactive_raised.exception.status_code, 400)

    async def test_active_scope_run_comments_allow_json_and_multipart(self) -> None:
        with patch.object(case_comments, "_action_actor", return_value=("alice", "kylin_ticket", True)), patch.object(
            case_comments, "extract_review_mentions", return_value=[]
        ):
            json_result = await case_comments.create_review_comment(
                "cn-migrated",
                self.request({"body": "Run A discussion", "model_run_id": self.run_a["id"]}),
            )
            attachment = {
                "id": "comment-attachment",
                "original_name": "comment.png",
                "stored_name": "comment.png",
                "media_type": "image/png",
                "size_bytes": 4,
                "width": 1,
                "height": 1,
                "sha256": "d" * 64,
            }
            with patch.object(
                case_comments,
                "_store_comment_attachments",
                return_value=([attachment], [self.root / "comment.png"]),
            ):
                multipart_result = await case_comments.create_review_comment_with_attachments(
                    "cn-migrated",
                    self.request(),
                    payload=json.dumps({
                        "body": "![evidence](attachment:token)",
                        "model_run_id": self.run_b["id"],
                        "attachment_tokens": ["token"],
                    }),
                    attachments=[SimpleNamespace()],
                )

        self.assertEqual(json_result["comment"]["model_run_id"], self.run_a["id"])
        self.assertEqual(multipart_result["comment"]["model_run_id"], self.run_b["id"])
        self.assertEqual(
            self.database.review_comment_count(
                issue_id="cn-migrated", model_run_id=self.run_a["id"]
            ),
            1,
        )
        self.assertEqual(
            self.database.review_comment_count(
                issue_id="cn-migrated", model_run_id=self.run_b["id"]
            ),
            1,
        )

    async def test_active_scope_no_run_rejects_before_comment_attachment_storage(self) -> None:
        with patch.object(case_comments, "_store_comment_attachments") as store:
            with self.assertRaises(HTTPException) as raised:
                await case_comments.create_review_comment_with_attachments(
                    "cn-migrated",
                    self.request(),
                    payload=json.dumps({
                        "body": "![evidence](attachment:token)",
                        "attachment_tokens": ["token"],
                    }),
                    attachments=[SimpleNamespace()],
                )
        self.assertEqual(raised.exception.status_code, 409)
        store.assert_not_called()

    async def test_inactive_scope_rejects_new_unbound_annotation_and_comment_writes(self) -> None:
        review_attachment = {
            "id": "legacy-review-attachment",
            "original_name": "legacy-review.png",
            "stored_name": "legacy-review.png",
            "media_type": "image/png",
            "size_bytes": 4,
            "width": 1,
            "height": 1,
            "sha256": "e" * 64,
        }
        with patch.object(
            case_annotations,
            "_store_review_attachments",
            return_value=([review_attachment], [self.root / "legacy-review.png"]),
        ) as store:
            with self.assertRaises(HTTPException) as raised:
                await case_annotations.create_annotation_with_attachments(
                    "cn-legacy",
                    self.request(),
                    payload=json.dumps({
                        "expected_output": "误触发",
                        "note": "legacy no-Run review",
                        "author": "alice",
                    }),
                    attachments=[],
                )
            self.assertEqual(raised.exception.status_code, 400)
            store.assert_not_called()

        comment_attachment = {
            "id": "legacy-comment-attachment",
            "original_name": "legacy-comment.png",
            "stored_name": "legacy-comment.png",
            "media_type": "image/png",
            "size_bytes": 4,
            "width": 1,
            "height": 1,
            "sha256": "f" * 64,
        }
        with patch.object(case_comments, "_action_actor", return_value=("alice", "kylin_ticket", True)), patch.object(
            case_comments, "extract_review_mentions", return_value=[]
        ), patch.object(
            case_comments,
            "_store_comment_attachments",
            return_value=([comment_attachment], [self.root / "legacy-comment.png"]),
        ) as store:
            with self.assertRaises(HTTPException) as raised:
                await case_comments.create_review_comment_with_attachments(
                    "cn-legacy",
                    self.request(),
                    payload=json.dumps({
                        "body": "![evidence](attachment:token)",
                        "attachment_tokens": ["token"],
                    }),
                    attachments=[SimpleNamespace()],
                )
            self.assertEqual(raised.exception.status_code, 400)
            store.assert_not_called()

    async def test_handover_follows_activation_state(self) -> None:
        self.database.set_labeling_scope_state(
            baseline_scope="migrated", status="paused", policy_version="test-v1",
            source_inventory_sha256="a" * 64, updated_by="test", expected_epoch=1,
        )
        with patch.object(case_annotations, "_create_annotation_record") as create:
            with self.assertRaises(HTTPException) as raised:
                await case_annotations.create_annotation("cn-migrated", self.request())
            self.assertEqual(raised.exception.status_code, 400)
            create.assert_not_called()
        self.database.set_labeling_scope_state(
            baseline_scope="migrated", status="active", policy_version="test-v1",
            source_inventory_sha256="a" * 64, updated_by="test", expected_epoch=2,
        )
        with patch.object(case_annotations, "_create_annotation_record") as create:
            with self.assertRaises(HTTPException) as raised:
                await case_annotations.create_annotation("cn-migrated", self.request())
            self.assertEqual(raised.exception.status_code, 409)
            create.assert_not_called()


class LabelingPreviewAdminTest(unittest.TestCase):
    def test_case_labeling_page_requires_admin(self) -> None:
        core = (
            Path(__file__).resolve().parents[1] / "app" / "routers" / "core.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@router.get("/case-labeling/new-task", include_in_schema=False)', core)
        self.assertIn("async def case_labeling_page(request: Request)", core)
        self.assertIn("await asyncio.to_thread(_admin_identity, request)", core)

    def test_labeling_task_creation_applies_selected_cluster(self) -> None:
        router = (
            Path(__file__).resolve().parents[1] / "app" / "routers" / "labeling.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cluster=normalized_cluster", router)

    def test_labeling_actor_rejects_writer(self) -> None:
        identity = SimpleNamespace(
            verified=True, username="writer", source="kylin_ticket"
        )
        with patch.object(labeling, "request_identity", return_value=identity), patch.object(
            labeling.database, "access_role", return_value="writer"
        ):
            with self.assertRaises(HTTPException) as raised:
                labeling._labeling_actor(SimpleNamespace())
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("管理员", str(raised.exception.detail))


class LabelingCommentWriteTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Database(Path(self.tmp.name) / "comments.sqlite")
        self.database.init()
        self.database.upsert_issues(
            [{"issue_id": "cn-active", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="active",
        )
        self.database.set_labeling_scope_state(
            baseline_scope="active", status="active", policy_version="test-v1",
            source_inventory_sha256="a" * 64, updated_by="test",
        )
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.object(labeling, "database", self.database))
        patches.enter_context(patch.object(
            labeling, "_labeling_actor", return_value=("alice", "kylin_ticket", True),
        ))
        patches.enter_context(patch.object(
            labeling, "_require_labeling_admin", new=AsyncMock(return_value=None),
        ))
        patches.enter_context(patch.object(labeling, "extract_review_mentions", return_value=[]))
        patches.enter_context(patch.object(
            labeling, "settings",
            SimpleNamespace(dchat_notifications_enabled=False),
        ))

    def request(self, body: dict | None = None) -> Request:
        async def receive():
            return {"type": "http.request", "body": json.dumps(body or {}).encode()}

        return Request({"type": "http", "headers": [], "query_string": b""}, receive)

    async def test_create_and_list_case_level_discussion(self) -> None:
        created = await labeling.create_labeling_comment(
            "cn-active", self.request({"body": "内测讨论"})
        )
        self.assertEqual(created["comment"]["body"], "内测讨论")
        self.assertEqual(created["comment"]["author"], "alice")
        listed = await labeling.list_labeling_comments("cn-active", self.request())
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["comments"][0]["body"], "内测讨论")

    async def test_reply_inherits_parent_thread(self) -> None:
        first = await labeling.create_labeling_comment(
            "cn-active", self.request({"body": "原始讨论"})
        )
        reply = await labeling.create_labeling_comment(
            "cn-active",
            self.request({"body": "跟进", "reply_to_id": first["comment"]["id"]}),
        )
        self.assertEqual(reply["comment"]["reply_to_id"], first["comment"]["id"])
        listed = await labeling.list_labeling_comments("cn-active", self.request())
        self.assertEqual(listed["count"], 2)

    async def test_inactive_issue_cannot_write_labeling_comments(self) -> None:
        self.database.upsert_issues(
            [{"issue_id": "cn-shadow", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="shadow",
        )
        self.database.set_labeling_scope_state(
            baseline_scope="shadow", status="shadow", policy_version="test-v1",
            source_inventory_sha256="a" * 64, updated_by="test",
        )
        with self.assertRaises(HTTPException) as raised:
            await labeling.create_labeling_comment(
                "cn-shadow", self.request({"body": "不能写"})
            )
        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
