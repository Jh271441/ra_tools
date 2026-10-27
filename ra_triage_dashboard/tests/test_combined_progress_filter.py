"""Task delivery filters are read-only and separate from S1/S3 states."""
import asyncio
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import HTTPException
from starlette.requests import Request

import test_version_campaign_physical as fixture
from ra_triage_dashboard.app.support import baselines, filter_parsing
from ra_triage_dashboard.app.routers import cases


class CombinedProgressFilterTest(unittest.TestCase):
    setUp = fixture.VersionCampaignPhysicalTest.setUp
    submit = fixture.VersionCampaignPhysicalTest.submit

    def request(self, progress="", owner="", view=""):
        return Request(dict(type="http", headers=[], query_string=urlencode({
            "task_progress": progress, "work_assignee": owner, "task_view": view,
        }).encode()))

    def ids(self, task, progress="", owner="", view="", selected=()):
        with patch.object(baselines, "database", self.db):
            return baselines.restrict_version_issue_ids(
                request=self.request(progress, owner, view), task_id=task,
                issue_ids=selected,
            )

    def test_fixed_task_partial_submission_and_ownership_survive_completion(self):
        task = self.campaigns[0]
        self.assertEqual(self.ids(task["id"], "pending", "jasperchen"), ("cn1",))
        self.assertEqual(self.ids(task["id"], "pending", "liangxianghui"), ("__empty_version_membership__",))
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=task["id"], reviewer="jasperchen")
        written = self.submit(task, context)
        self.assertTrue(self.submit(task, context)["duplicate"])
        revision = self.db.change_revision()
        self.assertEqual(self.ids(task["id"], "pending", "jasperchen"), ("__empty_version_membership__",))
        self.assertEqual(self.ids(task["id"], "completed", "JasperChen"), ("cn1",))
        self.assertEqual(self.ids(task["id"], "pending,completed", "jasperchen"), ("cn1",))
        self.assertEqual(self.db.change_revision(), revision)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT assignee FROM review_work_assignments WHERE split_id=?", (task["id"],)).fetchone()["assignee"], "jasperchen")
            # Isolate both incomplete halves without changing any source labels.
            for model, label in [(True, False), (False, True)]:
                conn.execute("UPDATE combined_review_progress SET model_review_submitted=?,case_label_acknowledged=? WHERE campaign_id=?", (model, label, task["id"]))
                conn.commit()
                self.assertEqual(self.ids(task["id"], "pending", "jasperchen"), ("cn1",))
                self.assertEqual(self.ids(task["id"], "completed", "jasperchen"), ("__empty_version_membership__",))
            self.assertEqual(conn.execute("SELECT id FROM model_review_revisions WHERE id=?", (written["model_review_storage_id"],)).fetchone()["id"], written["model_review_storage_id"])

    def test_cross_assigned_issue_requires_only_selected_owners(self):
        ws = self.db.create_review_workset(baseline_scope="manual_sidecar_test", issue_ids=["cn3"], selection_source_run_id=self.rid, created_by="test")
        snap = self.db.create_label_result_snapshot(workset_id=ws["id"], created_by="test", allow_partial=True)
        task = self.db.create_campaign(spec=dict(
            purpose="model_review", workflow_mode="model_review_and_case_label",
            evaluation_run_id=self.rid, workset_id=ws["id"], name="Overlap",
            reference_type="label_result_snapshot", reference_id=snap["id"],
            members=[dict(issue_id="cn3", assignees=["jasperchen", "liangxianghui"])],
        ), actor="test", actor_source="test", actor_verified=True, idempotency_key="overlap")["campaign"]
        context = self.db.combined_review_context(issue_id="cn3", campaign_id=task["id"], reviewer="jasperchen")
        self.submit(task, context, iid="cn3", key="overlap-submit")
        self.assertEqual(self.ids(task["id"], "completed", "jasperchen"), ("cn3",))
        self.assertEqual(self.ids(task["id"], "pending", "liangxianghui"), ("cn3",))
        self.assertEqual(self.ids(task["id"], "pending", "jasperchen,liangxianghui"), ("cn3",))
        self.assertEqual(self.ids(task["id"], "completed"), ("__empty_version_membership__",))

    def test_version_scope_intersection_and_validation(self):
        receipt = self.db.consolidate_version_campaigns(dataset_id="release-20261009-odd2", backup_sha256="a"*64, actor="test")
        task = receipt["campaign_id"]
        self.assertEqual(self.ids(task, "pending", "jasperchen", "targets"), ("cn1",))
        self.assertEqual(self.ids(task, "pending", "jasperchen", "targets", ("cn2",)), ("__empty_version_membership__",))
        self.items[0]["is_target"] = False
        self.db.ingest_version_dataset(family="20261009", policy=self.policy, items=self.items, batch_key="retired", actor="test")
        self.assertEqual(self.ids(task, "pending", "jasperchen", "targets"), ("__empty_version_membership__",))
        self.assertEqual(self.ids(task, "pending", "jasperchen"), ("cn1",))
        for task_id, value in [("", "pending"), ("missing", "completed"), (task, "invalid")]:
            with self.assertRaises(HTTPException):
                self.ids(task_id, value)

    def test_filter_payload_and_export_queue_keep_domains_separate(self):
        task = self.campaigns[0]["id"]
        request = self.request("pending", "jasperchen")
        with patch.object(baselines, "database", self.db), \
             patch.object(filter_parsing, "resolve_request_baseline_scopes", return_value=["manual_sidecar_test"]):
            filters = filter_parsing._case_filter_kwargs(request=request, work_split_id=task, work_assignee="jasperchen", label_state="conflict")
            self.assertEqual(filters["issue_ids"], ("cn1",))
            self.assertEqual(filters["model_review_status"], "")
            self.assertEqual(filters["label_states"], ("conflict",))
            with patch.object(cases, "_case_issue_ids_with_status_filter", return_value=["cn1"]) as queue:
                result = asyncio.run(cases.list_case_issue_ids(request, work_split_id=task, work_assignee="jasperchen"))
                self.assertEqual(result["issue_ids"], ["cn1"])
                self.assertEqual(queue.call_args.kwargs["filters"]["issue_ids"], ("cn1",))

    def test_frontend_behavior(self):
        subprocess.run(["node", str(Path(__file__).with_name("combined_progress_filter.cjs"))], check=True)
