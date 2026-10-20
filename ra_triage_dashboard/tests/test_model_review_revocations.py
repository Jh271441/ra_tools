"""Run revocation keeps Case votes and append-only audit, across task namespaces."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request
import test_combined_reviews as workflow
from ra_triage_dashboard.app.db import AnnotationConflictError
from ra_triage_dashboard.app.routers import case_annotations, cases
from ra_triage_dashboard.app.support import review_payloads


class ModelReviewRevocationTest(unittest.TestCase):
    setUp = workflow.CombinedReviewWorkflowTest.setUp
    campaign = workflow.CombinedReviewWorkflowTest.campaign
    submit = workflow.CombinedReviewWorkflowTest.submit

    def context(self, campaign):
        return self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"],
                                              reviewer="alice", model_run_id=campaign["evaluation_run_id"])

    def revoke(self, result, head=None, **kwargs):
        return self.db.revoke_model_review(
            issue_id="cn1", annotation_id=result["model_review"]["id"],
            expected_head_id=(head or result)["model_review"]["id"],
            **{**dict(actor="alice", actor_source="test", actor_verified=True), **kwargs},
        )

    def analysis(self, **kwargs):
        with patch.object(review_payloads, "database", self.db), \
             patch.object(review_payloads, "_missing_evidence_catalog", return_value=[]), \
             patch.object(review_payloads, "_review_tag_catalog", return_value=[]):
            return review_payloads._review_reason_analysis_payload(
                baseline_scopes=["scope"], comparison="all", include_multi_reviews=True, **kwargs,
            )

    def test_head_rollback_last_revocation_keeps_label_and_original_audit(self):
        campaign = self.campaign(0)
        first = self.submit(campaign, self.context(campaign))
        second = self.submit(campaign, self.context(campaign), key="second", label="正确触发")
        with self.db.connect() as conn:
            original = [dict(row) for row in conn.execute("SELECT * FROM model_review_revisions ORDER BY id").fetchall()]
            labels = [dict(row) for row in conn.execute("SELECT * FROM label_revisions ORDER BY id").fetchall()]
            submissions = [dict(row) for row in conn.execute("SELECT * FROM combined_review_submissions ORDER BY id").fetchall()]
        self.revoke(second)
        self.assertEqual(self.context(campaign)["model_review_storage_id"], first["model_review_storage_id"])
        self.assertEqual(self.context(campaign)["case_revision_id"], second["case_revision_id"])
        self.assertTrue(self.context(campaign)["progress"]["model_review_submitted"])
        self.assertTrue(self.revoke(second)["duplicate"])
        self.revoke(first)
        self.assertIsNone(self.context(campaign)["model_review_storage_id"])
        self.assertFalse(self.context(campaign)["progress"]["model_review_submitted"])
        self.assertEqual(self.db.list_review_work_splits()[0]["completed_count"], 0)
        summary = self.db.list_labeling_cases(baseline_scopes=["scope"], task_id=campaign["id"])
        self.assertEqual(summary["items"][0]["expected_output"], "正确触发")
        self.assertEqual(self.db.model_review_revisions(issue_id="cn1"), [])
        self.assertEqual(self.analysis(work_split_id=campaign["id"])["total"], 0)
        with self.db.connect() as conn:
            self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM model_review_revisions ORDER BY id").fetchall()], original)
            self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM label_revisions ORDER BY id").fetchall()], labels)
            self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM combined_review_submissions ORDER BY id").fetchall()], submissions)
            self.assertEqual(conn.execute("SELECT count(*) n FROM model_review_revocations").fetchone()["n"], 2)

    def test_non_head_permissions_stale_and_other_namespace(self):
        campaign = self.campaign(0)
        first = self.submit(campaign, self.context(campaign))
        second = self.submit(campaign, self.context(campaign), key="second")
        other = self.campaign(1)
        other_result = self.submit(other, self.context(other), key="other")
        self.db.set_access_user(username="bob", role="writer", actor="test")
        for actor, verified in [("bob", True), ("unknown", True), ("alice", False)]:
            with self.assertRaises(PermissionError):
                self.revoke(first, head=second, actor=actor, actor_verified=verified)
        with self.assertRaises(AnnotationConflictError): self.revoke(first)
        self.revoke(first, head=second)
        self.assertEqual(self.context(campaign)["model_review_storage_id"], second["model_review_storage_id"])
        self.assertEqual(self.context(other)["model_review_storage_id"], other_result["model_review_storage_id"])
        self.db.set_access_user(username="bob", role="admin", actor="test")
        self.revoke(second, actor="bob")
        self.assertIsNone(self.context(campaign)["model_review_storage_id"])
        self.assertEqual(self.context(other)["model_review_storage_id"], other_result["model_review_storage_id"])

    def test_single_task_analysis_global_run_exact_and_name(self):
        campaign = self.campaign(0)
        free = {"id": "", "evaluation_run_id": campaign["evaluation_run_id"]}
        self.submit(free, self.context(free), key="free")
        self.assertEqual(self.analysis(work_split_id=campaign["id"])["total"], 0)
        result = self.submit(campaign, self.context(campaign))
        for params in ({}, {"model_run_id": campaign["evaluation_run_id"]}, {"work_split_id": campaign["id"]}):
            payload = self.analysis(**params)
            self.assertEqual(payload["total"], 1)
            item = payload["items"][0]
            self.assertEqual(item["annotation"]["id"], result["model_review"]["id"])
            self.assertNotIn("multi_review", item)
        self.assertEqual(self.analysis(model_run_id=self.runs[1]["id"], work_split_id=campaign["id"])["total"], 0)
        other = self.campaign(0, workflow="model_review_only")
        self.assertEqual(self.analysis()["items"][0]["annotation"]["id"], result["model_review"]["id"])
        self.assertEqual(self.analysis(work_split_id=other["id"])["total"], 0)
        self.assertEqual(self.db.list_review_work_splits()[0]["campaign_name"], other["name"] if "name" in other else other["campaign_name"])

    def test_sqlite_existing_view_is_upgraded(self):
        campaign = self.campaign(0)
        first = self.submit(campaign, self.context(campaign))
        self.revoke(first)
        with self.db.connect() as conn:
            conn.execute("DROP VIEW review_records")
            conn.execute("CREATE VIEW review_records AS SELECT id FROM model_review_revisions")
        self.db.init()
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM review_records").fetchone()["n"], 0)

    def test_route_checks_verified_actor_and_optimistic_head(self):
        campaign = self.campaign(0)
        first = self.submit(campaign, self.context(campaign))
        async def receive():
            return {"type": "http.request", "body": json.dumps({"expected_head_id": first["model_review"]["id"]}).encode(), "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)
        with patch.object(case_annotations, "database", self.db), patch.object(case_annotations, "_writer_identity", return_value=SimpleNamespace(username="alice", source="test", verified=True)):
            result = asyncio.run(case_annotations.revoke_model_review("cn1", first["model_review"]["id"], request))
        self.assertFalse(result["revoked"]["duplicate"])

    def test_non_head_combined_revocation_recomputes_progress_from_standalone_head(self):
        campaign = self.campaign(0)
        first = self.submit(campaign, self.context(campaign))
        standalone = self.db.create_model_review(
            issue_id="cn1", model_run_id=campaign["evaluation_run_id"],
            campaign_id=campaign["id"], status="pending", reason="draft", missing_evidence=[],
            reviewer="alice", reviewer_verified=True,
        )
        self.revoke(first, head={"model_review": standalone})
        self.assertFalse(self.context(campaign)["progress"]["model_review_submitted"])
        self.assertEqual(self.context(campaign)["case_revision_id"], first["case_revision_id"])

    def test_history_ui_permissions_and_navigation_race(self):
        import subprocess
        from pathlib import Path
        script = Path(__file__).with_name("model_review_revocation_ui.cjs")
        subprocess.run(["node", str(script)], cwd=Path(__file__).resolve().parents[2], check=True)
