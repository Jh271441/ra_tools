"""Default/current task scope must exclude terminal Campaigns without deleting audit."""
import asyncio
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_combined_reviews as workflow
from ra_triage_dashboard.app.db_parts.task_lifecycle import task_list_metrics

class TaskLifecycleTest(unittest.TestCase):
    setUp = workflow.CombinedReviewWorkflowTest.setUp
    submit = workflow.CombinedReviewWorkflowTest.submit

    def create(self, name, assignees=("alice", "bob")):
        return self.db.create_campaign(spec={
            "purpose": "model_review", "workflow_mode": "model_review_and_case_label",
            "evaluation_run_id": self.runs[0]["id"], "workset_id": self.workset["id"],
            "name": name, "members": [{"issue_id": "cn1", "assignees": list(assignees)}],
        }, actor="tester", actor_source="test", actor_verified=True, idempotency_key=name)["campaign"]

    def terminal(self, campaign, action="supersede"):
        return self.db.transition_campaign(
            campaign_id=campaign["id"], action=action, actor="tester", actor_source="test",
            actor_verified=True, expected_revision=1, idempotency_key=campaign["id"]+action,
            reason="Replaced by full Run" if action == "supersede" else "Cancelled test task",
        )

    def fixture(self):
        active = self.create("full-run")
        historical = self.create("old-run")
        ctx = self.db.combined_review_context(issue_id="cn1", campaign_id=historical["id"], reviewer="alice")
        saved = self.submit(historical, ctx)
        self.terminal(historical)
        cancelled = self.create("cancelled", ("bob",))
        self.terminal(cancelled, "cancel")
        return active, historical, cancelled, saved

    def test_default_my_tasks_metrics_and_filter_before_limit(self):
        active, old, cancelled, _ = self.fixture()
        current = self.db.list_review_work_splits(limit=1)
        self.assertEqual([x["split_id"] for x in current], [active["id"]])
        self.assertEqual([x["split_id"] for x in self.db.list_review_work_splits(assignee="ALICE")], [active["id"]])
        metrics = task_list_metrics(current)
        self.assertEqual((metrics["batch_count"], metrics["assignment_count"], metrics["pending_count"]), (1, 2, 2))
        mine = task_list_metrics(current, "alice")
        self.assertEqual((mine["assignment_count"], mine["pending_count"]), (1, 1))
        history = self.db.list_review_work_splits(lifecycle="history")
        self.assertEqual({x["split_id"] for x in history}, {old["id"], cancelled["id"]})
        self.assertTrue(all(not x["is_current"] for x in history))
        self.assertEqual({x["split_id"] for x in self.db.list_review_work_splits(lifecycle="all")}, {active["id"],old["id"],cancelled["id"]})
        self.assertEqual([x["id"] for x in self.db.list_campaigns()["items"]], [active["id"]])
        self.assertEqual({x["id"] for x in self.db.list_campaigns(lifecycle="history")["items"]}, {old["id"],cancelled["id"]})
        self.assertEqual(self.db.list_campaigns(lifecycle="all")["total"], 3)
        self.assertEqual([x["id"] for x in self.db.list_labeling_tasks(["scope"])], [active["id"]])
        self.assertEqual({x["id"] for x in self.db.list_labeling_tasks(["scope"], lifecycle="history")}, {old["id"], cancelled["id"]})
        with self.assertRaises(ValueError): self.db.list_review_work_splits(lifecycle="garbage")

    def test_historical_detail_progress_reviews_and_audit_are_preserved(self):
        active, old, cancelled, saved = self.fixture()
        detail = self.db.get_review_work_split(old["id"])
        self.assertEqual(detail["lifecycle"], "superseded")
        self.assertFalse(detail["is_current"])
        self.assertEqual(detail["completed_count"], 1)
        self.assertEqual(detail["assignment_count"], 2)
        self.assertEqual(len(detail["items"]), 2)
        audit = self.db.get_campaign(old["id"])
        self.assertEqual(audit["lifecycle_audit"][0]["action"], "superseded")
        with self.db.connect() as conn:
            revision = conn.execute("SELECT id FROM model_review_revisions WHERE id=?", (saved["model_review_storage_id"],)).fetchone()
            label = conn.execute("SELECT id FROM label_revisions WHERE id=?", (saved["case_revision_id"],)).fetchone()
            self.assertIsNotNone(revision); self.assertIsNotNone(label)
            self.assertEqual(conn.execute("SELECT count(*) n FROM review_work_assignments WHERE split_id=?", (old["id"],)).fetchone()["n"], 2)
        with self.assertRaises(PermissionError):
            self.db.review_task_context(split_id=old["id"],username="alice",is_admin=True)
        with self.assertRaises(PermissionError):
            self.db.review_task_context(split_id=cancelled["id"],username="bob",allow_supplemental=True)
        self.assertEqual(self.db.review_task_context(split_id=active["id"],username="alice")["id"], active["id"])

    def test_api_default_and_my_history_use_same_scope_and_metrics(self):
        from ra_triage_dashboard.app.routers import cases
        active, old, cancelled, _ = self.fixture()
        with patch.object(cases, "database", self.db), patch.object(cases, "_admin_identity", return_value=SimpleNamespace(username="alice")):
            current = asyncio.run(cases.list_case_work_splits(None))
            history = asyncio.run(cases.list_case_work_splits(None,lifecycle="history",assigned_to_me=True))
        self.assertEqual([x["split_id"] for x in current["items"]], [active["id"]])
        self.assertEqual(current["metrics"]["assignment_count"], 2)
        self.assertEqual([x["split_id"] for x in history["items"]], [old["id"]])
        self.assertEqual(history["metrics"]["assignment_count"], 1)
        self.assertEqual(history["metrics"]["completed_count"], 1)

    def test_history_cards_metrics_and_filter_cache_in_browser_logic(self):
        result = subprocess.run(["node", str(Path(__file__).with_name("task_lifecycle_ui.cjs"))], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
