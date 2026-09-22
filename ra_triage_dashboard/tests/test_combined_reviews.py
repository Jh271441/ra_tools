from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import AnnotationConflictError, Database, LabelAnnotationConflictError


class CombinedReviewWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "combined.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues(
            [{"issue_id": "cn1", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="scope",
        )
        self.db.apply_gt_sync_snapshot(
            scope="scope", rows=[{"issue_id": "cn1", "gt_label": "正确触发"}],
            source_name="Trail", source_view_id=1000, source_field="gt",
            trigger="test", requested_by="tester", requested_by_source="test",
            requested_by_verified=True, expected_issue_ids=["cn1"],
        )
        self.db.set_labeling_scope_state(
            baseline_scope="scope", status="active", policy_version="test",
            source_inventory_sha256="a" * 64, updated_by="tester",
        )
        self.db.set_access_user(username="alice", role="admin", actor="tester")
        self.db.set_access_user(username="bob", role="admin", actor="tester")
        self.db.set_access_user(username="viewer", role="writer", actor="tester")
        self.runs = []
        for index in range(2):
            run, _ = self.db.import_model_run(
                name=f"run-{index}", source_name=f"run-{index}.json",
                source_sha256=str(index + 1) * 64, metadata={},
                rows=[{"issue_id": "cn1", "model_label": "误触发"}],
            )
            self.runs.append(run)
        self.workset = self.db.create_review_workset(
            baseline_scope="scope", issue_ids=["cn1"], name="combined",
            selection_source_run_id=self.runs[0]["id"], created_by="tester",
        )

    def campaign(self, run_index: int, *, workflow: str = "model_review_and_case_label", assignees=None):
        return self.db.create_campaign(
            spec={
                "purpose": "model_review", "workflow_mode": workflow,
                "evaluation_run_id": self.runs[run_index]["id"],
                "workset_id": self.workset["id"], "name": f"campaign-{run_index}-{workflow}",
                "members": [{"issue_id": "cn1", "assignees": assignees or ["alice"]}],
            },
            actor="tester", actor_source="test", actor_verified=True,
            idempotency_key=f"campaign-{run_index}-{workflow}-{','.join(assignees or ['alice'])}",
        )["campaign"]

    def submit(self, campaign, context, *, label="误触发", reviewer="alice", key="submit-1", status="completed"):
        return self.db.submit_combined_review(
            issue_id="cn1", campaign_id=campaign["id"],
            model_run_id=campaign["evaluation_run_id"], reviewer=reviewer,
            reviewer_source="test", reviewer_verified=True,
            model_review_status=status, reason="model reason",
            missing_evidence=["camera"], expected_output=label,
            tags=[], rationale="case rationale",
            expected_model_review_storage_id=context["model_review_storage_id"],
            expected_case_revision_id=context["case_revision_id"],
            expected_label_state_fingerprint=context["label_state_fingerprint"],
            idempotency_key=key,
        )

    def test_existing_campaign_defaults_to_model_review_only_and_combined_requires_case_permission(self) -> None:
        ordinary = self.campaign(0, workflow="model_review_only")
        self.assertEqual(ordinary["workflow_mode"], "model_review_only")
        with self.assertRaisesRegex(ValueError, "缺少 Case 标注权限"):
            self.campaign(0, assignees=["viewer"])

    def test_atomic_combined_submission_reuses_vote_across_runs_and_tracks_progress(self) -> None:
        campaign_a = self.campaign(0)
        with self.db.connect() as conn:
            before_annotations = conn.execute("SELECT COUNT(*) n FROM annotations").fetchone()["n"]
        context_a = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign_a["id"], reviewer="alice"
        )
        first = self.submit(campaign_a, context_a)
        self.assertEqual(first["case_action"], "submitted")
        self.assertEqual(first["model_review"]["model_review_status"], "completed")
        self.assertTrue(first["progress"]["model_review_submitted"])
        self.assertTrue(first["progress"]["case_label_acknowledged"])
        with self.db.connect() as conn:
            first_label_count = int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"])
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM annotations").fetchone()["n"]), before_annotations)

        campaign_b = self.campaign(1)
        context_b = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign_b["id"], reviewer="alice"
        )
        second = self.submit(campaign_b, context_b, key="submit-run-b")
        self.assertEqual(second["case_action"], "acknowledged")
        with self.db.connect() as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"]), first_label_count)
            heads = conn.execute("SELECT model_run_id FROM model_review_heads ORDER BY model_run_id").fetchall()
        self.assertEqual({row["model_run_id"] for row in heads}, {self.runs[0]["id"], self.runs[1]["id"]})

        replay = self.submit(campaign_b, context_b, key="submit-run-b")
        self.assertTrue(replay["duplicate"])

    def test_vote_change_conflict_does_not_block_completed_model_review(self) -> None:
        campaign = self.campaign(0, assignees=["alice", "bob"])
        alice_context = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="alice"
        )
        self.submit(campaign, alice_context, label="误触发", reviewer="alice", key="alice")
        bob_context = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="bob"
        )
        bob = self.submit(campaign, bob_context, label="正确触发", reviewer="bob", key="bob")
        self.assertEqual(bob["label_state"]["state"], "conflict")
        self.assertEqual(bob["model_review"]["model_review_status"], "completed")
        alice_after = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="alice"
        )
        changed = self.submit(
            campaign, alice_after, label="正确触发", reviewer="alice", key="alice-change"
        )
        self.assertEqual(changed["case_action"], "submitted")
        with self.db.connect() as conn:
            bob_heads = conn.execute(
                "SELECT COUNT(*) n FROM label_revisions WHERE lower(author)='bob'"
            ).fetchone()["n"]
        self.assertEqual(int(bob_heads), 1)

    def test_stale_case_version_rolls_back_model_half(self) -> None:
        campaign = self.campaign(0)
        stale = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="alice"
        )
        self.db.submit_review_case_label(
            issue_id="cn1", reviewer="alice", reviewer_source="test",
            reviewer_verified=True, expected_output="误触发", tags=[], rationale="external",
            expected_case_revision_id=None,
            expected_label_state_fingerprint=stale["label_state_fingerprint"],
        )
        with self.db.connect() as conn:
            before_models = int(conn.execute("SELECT COUNT(*) n FROM model_review_revisions").fetchone()["n"])
            before_labels = int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"])
        with self.assertRaises((LabelAnnotationConflictError, AnnotationConflictError)):
            self.submit(campaign, stale, key="stale")
        with self.db.connect() as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM model_review_revisions").fetchone()["n"]), before_models)
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"]), before_labels)
