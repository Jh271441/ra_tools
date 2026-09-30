from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import analysis as analysis_router
from ra_triage_dashboard.app.support import review_payloads
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class LegacyAdjudicationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "adjudication.sqlite")
        self.db.init()
        self.db.upsert_issues(
            [{"issue_id": "cn1", "gt_label": "正确触发"}, {"issue_id": "cn2", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="scope",
        )
        self.run, _ = self.db.import_model_run(
            name="blind", source_name="a.json", source_sha256="a" * 64, metadata={},
            rows=[{"issue_id": "cn1", "model_label": "误触发"}, {"issue_id": "cn2", "model_label": "误触发"}],
        )
        self.other_run, _ = self.db.import_model_run(
            name="other", source_name="b.json", source_sha256="b" * 64, metadata={},
            rows=[{"issue_id": "cn1", "model_label": "无需协助"}],
        )
        self.split = self.db.apply_work_split(
            assignments=distribute_issue_ids(["cn1"], [{"name": "alice"}, {"name": "bob"}], seed=1, reviewers_per_issue=2),
            created_by="admin", reviewers_per_issue=2, model_run_id=self.run["id"],
        )["split_id"]
        self.patches = [
            patch.object(review_payloads, "database", self.db),
            patch("ra_triage_dashboard.app.support.catalogs.database", self.db),
        ]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def vote(self, author, label, *, run=None, split="", issue="cn1", previous=None, tags=None):
        return self.db.create_annotation(
            issue_id=issue, model_run_id=self.run["id"] if run is None else run,
            work_split_id=split, label=label, review_status="pending", tags=tags or [],
            missing_evidence=[], note=f"reason-{author}-{label}", author=author,
            author_source="test", author_verified=True, expected_previous_annotation_id=previous,
        )

    def conflict(self):
        a = self.vote("alice", "正确触发", split=self.split)
        b = self.vote("bob", "误触发", split=self.split)
        return a, b

    def result(self, **overrides):
        kwargs = dict(model_run_id=self.run["id"], comparison="all", baseline_scopes=["scope"], work_agreement="conflict", work_split_id=self.split, include_multi_reviews=True)
        kwargs.update(overrides)
        return review_payloads._review_reason_analysis_payload(**kwargs)

    def test_same_run_third_review_drives_summary_and_both_exports_keeps_conflict(self):
        self.conflict()
        decision = self.vote("carol", "无需协助", tags=["decision-tag"])
        result = self.result()
        item = result["items"][0]
        self.assertEqual(item["annotation"]["id"], decision["id"])
        self.assertEqual(item["annotation"]["author"], "carol")
        self.assertEqual(item["annotation"]["note"], "reason-carol-无需协助")
        self.assertEqual(item["annotation"]["tags"], ["decision-tag"])
        multi = item["multi_review"]
        self.assertEqual(multi["agreement"], "conflict")
        self.assertEqual((multi["assigned_count"], multi["completed_count"]), (2, 2))
        self.assertEqual({r["username"] for r in multi["reviews"]}, {"alice", "bob"})
        self.assertEqual(multi["adjudication"]["id"], decision["id"])
        self.assertEqual(analysis_router._trail_expected_output_rows(result), [{"issue_id": "cn1", "期望输出": "无需协助"}])
        exported = analysis_router._review_analysis_export_rows(result)[0]
        self.assertEqual((exported["reviewer"], exported["adjudicator"], exported["blind_agreement"]), ("carol", "carol", "conflict"))
        self.assertEqual(exported["adjudication_id"], decision["id"])
        workbook = openpyxl.load_workbook(io.BytesIO(analysis_router._review_analysis_export_response(result, "trail_xlsx").body), read_only=True)
        self.addCleanup(workbook.close)
        self.assertEqual(list(workbook.active.values), [("issue_id", "期望输出"), ("cn1", "无需协助")])
        self.assertEqual(self.result(work_agreement="all")["items"][0]["annotation"]["id"], decision["id"])
        self.assertEqual(self.result(model_run_id="")["items"][0]["annotation"]["id"], decision["id"])
        self.assertEqual(self.result(annotation_author="carol")["total"], 1)
        self.assertEqual(self.result(annotation_author="alice")["total"], 1)
        self.assertEqual(self.result(review_status="reviewed")["total"], 0)
        self.assertEqual(self.result(review_status="needs_gt_review")["total"], 1)

    def test_other_run_unbound_run_other_task_and_assignee_cannot_adjudicate(self):
        self.conflict()
        self.vote("carol", "无需协助", run=self.other_run["id"])
        self.vote("dave", "无需协助", run="")
        self.vote(" ALICE ", "无需协助")
        other = self.db.apply_work_split(
            assignments=distribute_issue_ids(["cn2"], [{"name":"carol"},{"name":"dave"}], seed=1, reviewers_per_issue=2),
            created_by="admin", reviewers_per_issue=2, model_run_id=self.run["id"],
        )["split_id"]
        self.vote("carol", "无需协助", split=other)
        result = self.result()
        self.assertIsNone(result["items"][0]["multi_review"]["adjudication"])
        self.assertEqual(analysis_router._trail_expected_output_rows(result), [])

    def test_older_review_and_later_member_revision_do_not_leave_stale_decision(self):
        self.vote("carol", "无需协助")
        _, bob = self.conflict()
        self.assertIsNone(self.result()["items"][0]["multi_review"]["adjudication"])
        self.vote("dave", "无需协助")
        self.assertEqual(self.result()["items"][0]["annotation"]["author"], "dave")
        self.vote("bob", "误触发", split=self.split, previous=bob["id"])
        result = self.result()
        self.assertIsNone(result["items"][0]["multi_review"]["adjudication"])
        self.assertEqual(analysis_router._trail_expected_output_rows(result), [])

    def test_newest_non_assignee_controls_gt_and_invalid_latest_does_not_resurrect_old(self):
        self.conflict()
        self.vote("carol", "无需协助")
        self.vote("dave", "正确触发")
        result = self.result()
        self.assertEqual(result["items"][0]["annotation"]["author"], "dave")
        self.assertEqual(analysis_router._trail_expected_output_rows(result), [])
        self.vote("erin", "")
        result = self.result()
        self.assertIsNone(result["items"][0]["multi_review"]["adjudication"])
        self.assertEqual(analysis_router._trail_expected_output_rows(result), [])

    def test_agreed_pair_is_not_replaced_by_non_assignee(self):
        self.vote("alice", "误触发", split=self.split)
        self.vote("bob", "误触发", split=self.split)
        self.vote("carol", "无需协助")
        item = self.result(work_agreement="all")["items"][0]
        self.assertEqual(item["multi_review"]["agreement"], "agreed")
        self.assertIsNone(item["multi_review"]["adjudication"])
        self.assertEqual(item["annotation"]["author"], "bob")
