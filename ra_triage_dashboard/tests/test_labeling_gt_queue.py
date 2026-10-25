"""GT queue membership, provenance and export must share the audited candidate rules."""
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.labeling_summary import summarize_labeling_cases
from ra_triage_dashboard.app.routers.labeling_api import queries, exports
from ra_triage_dashboard.app.support import review_payloads


class LabelingGtQueueTest(IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = Database(self.root / "queue.sqlite")
        self.db.init()
        ids = [f"cn10{n}" for n in range(1, 9)]
        rows = [{"issue_id": issue, "gt_label": "" if issue == "cn102" else "正确触发", "scenario": "junction"} for issue in ids]
        self.db.upsert_issues(rows, source="fixture", replace_gt=True, baseline_scope="scope")
        self.db.apply_gt_sync_snapshot(scope="scope", rows=[row for row in rows if row["gt_label"]], source_name="fixture", source_view_id=1,
            source_field="ra_merge_result", trigger="test", requested_by="tester", requested_by_source="test",
            requested_by_verified=True, expected_issue_ids=ids, allow_sparse=True)
        self.db.set_labeling_scope_state(baseline_scope="scope", status="active", policy_version="test",
            source_inventory_sha256="a" * 64, updated_by="test")
        self.heads = {}
        self.submit("cn101", "alice", "误触发")
        self.submit("cn102", "alice", "无需协助")
        self.submit("cn103", "alice", "正确触发")
        workset = self.db.create_review_workset(baseline_scope="scope", issue_ids=ids, created_by="admin")
        self.task_a = self.task(workset, "cn104", ["alice"])
        task_b = self.task(workset, "cn104", ["bob"])
        self.submit("cn104", "alice", "误触发", self.task_a)
        self.submit("cn104", "bob", "正确触发", task_b)
        pending = self.task(workset, "cn105", ["alice", "bob"])
        self.submit("cn105", "alice", "误触发", pending)
        self.task(workset, "cn106", ["alice"])
        for issue in ("cn107", "cn108"):
            self.submit(issue, "alice", "误触发")
            self.submit(issue, "bob", "正确触发")
            projection = self.db.project_issue_label_states("scope", [issue])[issue]
            self.db.adjudicate_issue_label(baseline_scope="scope", issue_id=issue, expected_output="无需协助",
                rationale="final issue evidence", actor="judge", actor_source="test", actor_verified=True,
                expected_source_fingerprint=projection["source_fingerprint"])
        self.submit("cn107", "alice", "误触发", rationale="new evidence invalidates prior decision")
        stack = ExitStack()
        self.addCleanup(stack.close)
        for module in (queries, exports):
            stack.enter_context(patch.object(module, "database", self.db))
            stack.enter_context(patch.object(module, "resolve_request_baseline_scopes", return_value=["scope"]))
            stack.enter_context(patch.object(module, "_active_labeling_scopes", AsyncMock(return_value=["scope"])))
            stack.enter_context(patch.object(module, "restrict_version_issue_ids", side_effect=lambda *a, **kw: kw.get("issue_ids", ())))
        self.writer = stack.enter_context(patch.object(queries, "_require_labeling_writer", AsyncMock()))
        stack.enter_context(patch.object(exports, "_labeling_actor", return_value=("admin", "test", True)))

    def task(self, workset, issue, names):
        return self.db.create_labeling_task(workset_id=workset["id"], created_by="admin", seed=1,
            reviewers_per_issue=len(names), overlap_ratio=1 if len(names) > 1 else 0,
            assignments=[{"name": name, "issue_ids": [issue]} for name in names])["id"]

    def submit(self, issue, author, output, task="", rationale="visible label evidence"):
        key = (issue, author, task)
        revision = self.db.create_label_revision(issue_id=issue, task_id=task, expected_output=output,
            rationale=rationale, tags=[], evidence_gaps=[], is_excluded=False, author=author,
            author_source="test", author_verified=True, expected_previous_revision_id=self.heads.get(key))
        self.heads[key] = revision["id"]
        return revision

    @staticmethod
    def request(body=None):
        async def receive():
            return {"type": "http.request", "body": json.dumps(body or {}).encode()}
        return Request({"type": "http", "headers": [], "query_string": b""}, receive)

    async def test_membership_pagination_counts_and_read_only_view(self):
        before = self.db.change_revision()
        ready = await queries.labeling_summary(self.request(), gt_update="ready", page_size=1, page=2)
        self.assertEqual(ready["gt_update_counts"], {"all": 7, "ready": 3, "blocked": 3})
        self.assertEqual((ready["annotated"], ready["page_count"], ready["page"]), (3, 3, 2))
        full = await queries.labeling_summary(self.request(), gt_update="ready")
        self.assertEqual({row["issue_id"] for row in full["items"]}, {"cn101", "cn102", "cn108"})
        self.assertEqual(next(row for row in full["items"] if row["issue_id"] == "cn108")["rationales"], ["final issue evidence"])
        blocked = await queries.labeling_summary(self.request(), gt_update="blocked")
        self.assertEqual({row["issue_id"]: row["gt_update"]["reason"] for row in blocked["items"]},
                         {"cn104": "conflict", "cn105": "pending", "cn107": "stale"})
        self.assertEqual(self.db.change_revision(), before)
        self.writer.assert_awaited()

    async def test_incomplete_filter_excludes_untouched_cases_across_gallery_summary_and_queue(self):
        # A Case without an assignment and an untouched assignment both belong
        # to Not annotated. A submitted blank conclusion is still real evidence.
        self.db.upsert_issues([{"issue_id": "cn109", "gt_label": "正确触发"},
                               {"issue_id": "cn110", "gt_label": "正确触发"}],
                              source="fixture", replace_gt=True, baseline_scope="scope")
        self.submit("cn110", "alice", "", rationale="historical blank conclusion")
        before = self.db.change_revision()
        expected = {
            "unannotated": {"cn106", "cn109"},
            "incomplete": {"cn105", "cn110"},
            "conflict": {"cn104", "cn107"},
            "pending": {"cn105", "cn106", "cn109", "cn110"},
            "incomplete,conflict": {"cn104", "cn105", "cn107", "cn110"},
        }
        for status, ids in expected.items():
            with self.subTest(status=status):
                result = await queries.list_labeling_cases(self.request(), status=status, page_size=1, page=2)
                self.assertEqual(set(result["queue_issue_ids"]), ids)
                self.assertEqual(result["total"], len(ids))
                self.assertEqual(len(result["items"]), 1)
                self.assertEqual(set(self.db.labeling_case_issue_ids(baseline_scopes=["scope"], status=status)), ids)
                summary = await queries.labeling_summary(self.request(), status=status)
                self.assertEqual({item["issue_id"] for item in summary["items"]}, ids - {"cn106", "cn109"})
                clusters = await queries.list_labeling_clusters(self.request(), status=status)
                self.assertEqual(clusters["filters"]["status"], status.split(","))
        incomplete = await queries.labeling_summary(self.request(), status="incomplete")
        self.assertEqual(incomplete["gt_update_counts"], {"all": 2, "ready": 0, "blocked": 2})
        self.assertTrue(all(item["label_state"] == "pending" for item in incomplete["items"]))
        for kwargs in ({"author": "nobody"}, {"q": "not-present"}, {"issue_ids": "cn106"}):
            result = await queries.list_labeling_cases(self.request(), status="incomplete", **kwargs)
            self.assertEqual(result["queue_issue_ids"], [])
        self.assertEqual(self.db.change_revision(), before)
        # Export scoping uses the same new filter, not the whole baseline.
        with patch.object(self.db, "labeling_case_issue_ids", wraps=self.db.labeling_case_issue_ids) as scope:
            preview = await exports.create_gt_export_preview(self.request({
                "baselines": "scope", "filters": {"status": "incomplete"}}))
        self.assertEqual(scope.call_args.kwargs["status"], ["incomplete"])
        self.assertEqual(preview["preview"]["item_count"], 0)
        self.assertEqual(preview["preview"]["scope_summary"]["total"], 2)

    async def test_incomplete_filter_preserves_task_scope_and_writer_guard(self):
        partial = self.db.label_cases_for_issue("cn105")[0]["task_id"]
        result = await queries.list_labeling_cases(self.request(), task_id=partial, status="incomplete")
        self.assertEqual(result["queue_issue_ids"], ["cn105"])
        empty = await queries.list_labeling_cases(self.request(), task_id=self.task_a, status="incomplete")
        self.assertEqual(empty["queue_issue_ids"], [])
        with self.assertRaises(HTTPException) as invalid:
            await queries.list_labeling_cases(self.request(), status="not-a-state")
        self.assertEqual(invalid.exception.status_code, 400)
        with patch.object(queries, "_require_labeling_writer", AsyncMock(side_effect=HTTPException(403, "writer required"))), \
             patch.object(self.db, "list_labeling_cases") as project:
            with self.assertRaises(HTTPException):
                await queries.list_labeling_cases(self.request(), status="incomplete")
            project.assert_not_called()

    async def test_task_local_resolution_cannot_hide_global_conflict(self):
        local, _ = self.db._project_labeling_cases(baseline_scopes=["scope"], task_id=self.task_a)
        self.assertEqual(next(item for item in local if item["issue_id"] == "cn104")["label_state"], "resolved")
        ready = await queries.labeling_summary(self.request(), task_id=self.task_a, gt_update="ready")
        self.assertEqual(ready["items"], [])
        blocked = await queries.labeling_summary(self.request(), task_id=self.task_a, gt_update="blocked")
        row = blocked["items"][0]
        self.assertEqual((row["issue_id"], row["label_state"], row["source_count"]), ("cn104", "conflict", 2))
        self.assertEqual(row["gt_update"]["reason"], "conflict")

    async def test_export_and_filters_preserve_exact_membership(self):
        ready = await queries.labeling_summary(self.request(), gt_update="ready", q="cn10", author="alice")
        preview = await exports.create_gt_export_preview(self.request({"baselines": "scope", "filters": {"gt_update": "ready", "q": "cn10", "author": "alice"}}))
        self.assertEqual({row["issue_id"] for row in preview["preview"]["items"]}, {row["issue_id"] for row in ready["items"]})
        blocked = await exports.create_gt_export_preview(self.request({"baselines": "scope", "filters": {"gt_update": "blocked"}}))
        self.assertEqual(blocked["preview"]["item_count"], 0)
        for kwargs in ({"q": "nonexistent"}, {"author": "nobody"}, {"gt": "误触发"}):
            result = await queries.labeling_summary(self.request(), gt_update="ready", **kwargs)
            self.assertEqual(result["items"], [])
            self.assertEqual(result["gt_update_counts"]["ready"], 0)
        with self.assertRaises(HTTPException) as error:
            await exports.create_gt_export_preview(self.request({"baselines": "scope", "filters": {"gt_update": "ready", "q": "nonexistent"}}))
        self.assertEqual(error.exception.status_code, 400)

    async def test_gt_refresh_clears_only_matching_ready_item_and_invalid_filter_is_rejected(self):
        rows = [{"issue_id": f"cn10{n}", "gt_label": "误触发" if n == 1 else "" if n == 2 else "正确触发"} for n in range(1, 9)]
        self.db.apply_gt_sync_snapshot(scope="scope", rows=[row for row in rows if row["gt_label"]], source_name="fixture", source_view_id=1,
            source_field="ra_merge_result", trigger="test", requested_by="tester", requested_by_source="test",
            requested_by_verified=True, expected_issue_ids=[row["issue_id"] for row in rows], allow_sparse=True)
        result = await queries.labeling_summary(self.request(), gt_update="ready")
        self.assertEqual({row["issue_id"] for row in result["items"]}, {"cn102", "cn108"})
        with self.assertRaises(HTTPException) as error:
            await queries.labeling_summary(self.request(), gt_update="anything")
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.label_gt_candidates(["scope"], issue_ids=[]), [])
        self.assertEqual(self.db.label_gt_candidates(["other"], issue_ids=["cn101"]), [])

    async def test_view_requires_writer(self):
        with patch.object(queries, "_require_labeling_writer", AsyncMock(side_effect=HTTPException(403, "writer required"))), patch.object(self.db, "_project_labeling_cases") as project:
            with self.assertRaises(HTTPException):
                await queries.labeling_summary(self.request(), gt_update="ready")
            project.assert_not_called()

    def test_candidate_batch_selection_does_not_escape_scopes(self):
        selected = ["cn101"] + [f"cn{n}" for n in range(1000, 1450)]
        self.assertEqual([item["issue_id"] for item in self.db.label_gt_candidates(["scope"], issue_ids=selected)], ["cn101"])

    def test_reason_analysis_gt_counts_follow_complete_filtered_scope_and_stay_read_only(self):
        run, _ = self.db.import_model_run(name="analysis", source_name="analysis.json", source_sha256="e" * 64,
            metadata={}, rows=[{"issue_id": f"cn10{n}", "model_label": "误触发"} for n in range(1, 9)])
        for n in range(1, 9):
            self.db.create_model_review(issue_id=f"cn10{n}", model_run_id=run["id"], status="completed",
                reason="model-only reason", missing_evidence=[], reviewer="alice" if n < 4 else "bob")
        before = self.db.change_revision()
        with patch.object(review_payloads, "database", self.db), \
             patch.object(review_payloads, "_missing_evidence_catalog", return_value=[]), \
             patch.object(review_payloads, "_review_tag_catalog", return_value=[]):
            def query(**kwargs):
                return review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"], baseline_scopes=["scope"], exclusion="all", **kwargs)
            first, last = query(page_size=1), query(page_size=1, page=8)
            self.assertEqual(first["gt_update_counts"], {"all": 7, "ready": 3, "blocked": 3})
            self.assertEqual(first["gt_update_counts"], last["gt_update_counts"])
            self.assertNotIn("_scope_issue_ids", first)
            self.assertEqual(first["total"], 8)  # Empty Case assignment stays outside the GT denominator.
            alice = query(annotation_author="alice")
            self.assertEqual(alice["gt_update_counts"], {"all": 3, "ready": 2, "blocked": 0})
            blocked = query(issue_ids=["cn104", "cn107"])
            self.assertEqual(blocked["gt_update_counts"], {"all": 2, "ready": 0, "blocked": 2})
            unchanged = query(search="cn103")
            self.assertEqual(unchanged["gt_update_counts"], {"all": 1, "ready": 0, "blocked": 0})
            for kwargs in ({"search": "no-such-issue"}, {"review_status": "pending"}, {"work_split_id": "missing-task"}):
                result = query(**kwargs)
                self.assertEqual(result["gt_update_counts"], {"all": 0, "ready": 0, "blocked": 0}, kwargs)
            with patch.object(self.db, "labeling_gt_update_cases", wraps=self.db.labeling_gt_update_cases) as counts:
                exported = query(unbounded=True)
                counts.assert_not_called()
                self.assertNotIn("gt_update_counts", exported)
                self.assertNotIn("_scope_issue_ids", exported)
                self.assertEqual(exported["total"], 8)
            self.assertEqual(first["items"][0]["annotation"]["note"], "model-only reason")
            label_cases, _ = self.db._project_labeling_cases(baseline_scopes=["scope"], issue_ids=["cn101"])
            self.assertEqual(summarize_labeling_cases(label_cases)["items"][0]["rationales"], ["visible label evidence"])
        self.assertEqual(self.db.change_revision(), before)
