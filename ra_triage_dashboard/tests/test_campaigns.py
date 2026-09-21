from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.campaigns import (
    CampaignConflictError,
    CampaignReadOnlyError,
    campaign_inventory_fingerprint,
)


class CampaignStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "campaign.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues(
            [
                {"issue_id": "cn001", "title": "One", "scenario": "scenario-a", "gt_label": "正确触发"},
                {"issue_id": "cn002", "title": "Two", "scenario": "scenario-b", "gt_label": "误触发"},
            ],
            source="test",
            replace_gt=True,
            baseline_scope="scope",
        )
        now = "2026-09-21T00:00:00Z"
        content_sha = hashlib.sha256(b"test-gt-snapshot").hexdigest()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO gt_snapshots (
                    id, baseline_scope, gt_mode, content_sha256,
                    membership_sha256, member_count, valid_label_count, created_at
                ) VALUES (?, ?, 'strict', ?, ?, 2, 2, ?)
                """,
                ("gt-test", "scope", content_sha, "b" * 64, now),
            )
            conn.executemany(
                "INSERT INTO gt_snapshot_items (snapshot_id, baseline_scope, issue_id, ordinal, gt_label) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("gt-test", "scope", "cn001", 1, "正确触发"),
                    ("gt-test", "scope", "cn002", 2, "误触发"),
                ],
            )
            conn.execute(
                "INSERT INTO gt_snapshot_active (baseline_scope, snapshot_id, activated_at) VALUES (?, ?, ?)",
                ("scope", "gt-test", now),
            )
        self.run_a, _ = self.db.import_model_run(
            name="run-a",
            source_name="run-a.json",
            source_sha256="a" * 64,
            metadata={},
            rows=[
                {"issue_id": "cn001", "model_label": "正确触发"},
                {"issue_id": "cn002", "model_label": "误触发"},
            ],
        )
        self.run_b, _ = self.db.import_model_run(
            name="run-b",
            source_name="run-b.json",
            source_sha256="b" * 64,
            metadata={},
            rows=[
                {"issue_id": "cn001", "model_label": "正确触发"},
                {"issue_id": "cn002", "model_label": "误触发"},
            ],
        )

    def _model_campaign(self):
        return self.db.create_campaign(
            spec={
                "purpose": "model_review",
                "evaluation_run_id": self.run_a["id"],
                "name": "Overlap review",
                "members": [
                    {"issue_id": "cn001", "assignees": ["alice", "bob"]},
                    {"issue_id": "cn002", "assignees": ["alice"]},
                ],
            },
            actor="admin",
            actor_source="test",
            actor_verified=True,
            idempotency_key="create-overlap",
        )

    def test_overlapping_requirements_assignment_audit_and_close_reopen(self) -> None:
        created = self._model_campaign()
        campaign = created["campaign"]
        campaign_id = campaign["id"]
        reference_id = campaign["reference_id"]
        self.assertEqual(created["progress"]["member_count"], 2)
        self.assertEqual(created["progress"]["required_submitter_count"], 3)
        self.assertEqual([item["required_submitter_count"] for item in created["issues"]], [2, 1])

        for issue_id, reviewer in (
            ("cn001", "alice"),
            ("cn001", "bob"),
            ("cn002", "alice"),
        ):
            self.db.create_model_review(
                issue_id=issue_id,
                model_run_id=self.run_a["id"],
                status="completed",
                reason="reviewed",
                missing_evidence=[],
                reviewer=reviewer,
                campaign_id=campaign_id,
                reference_id=reference_id,
                work_split_id=campaign_id,
            )
        progressed = self.db.get_campaign(campaign_id)
        self.assertEqual(progressed["progress"]["submitted_submitter_count"], 3)
        self.assertEqual(progressed["progress"]["completed_issue_count"], 2)

        change_args = {
            "campaign_id": campaign_id,
            "issue_id": "cn002",
            "action": "assign",
            "assignee": "carol",
            "actor": "admin",
            "actor_source": "test",
            "actor_verified": True,
            "expected_revision": 1,
            "idempotency_key": "assign-carol",
        }
        changed = self.db.update_campaign_assignment(**change_args)
        self.assertEqual(changed["config_revision"], 2)
        replay = self.db.update_campaign_assignment(**change_args)
        self.assertTrue(replay["replayed"])
        with self.assertRaises(CampaignConflictError):
            self.db.update_campaign_assignment(
                **{**change_args, "assignee": "dave"}
            )

        closed = self.db.close_campaign(
            campaign_id=campaign_id,
            actor="admin",
            actor_source="test",
            actor_verified=True,
            expected_revision=2,
            idempotency_key="close-2",
            reason="review complete",
        )
        snapshot_id = closed["snapshot_id"]
        self.assertEqual(closed["campaign"]["campaign"]["lifecycle"], "closed")
        self.assertEqual(closed["campaign"]["close_snapshot"]["config_revision"], 2)
        with self.db.connect() as conn:
            snapshot = conn.execute(
                "SELECT source_fingerprint, result_snapshot_json FROM campaign_close_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            item_count = conn.execute(
                "SELECT COUNT(*) AS n FROM campaign_close_snapshot_items WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()["n"]
            self.assertEqual(len(str(snapshot["source_fingerprint"])), 64)
            self.assertEqual(int(item_count), 2)
        with self.assertRaises(CampaignReadOnlyError):
            self.db.update_campaign_assignment(
                **{**change_args, "expected_revision": 2, "idempotency_key": "after-close"}
            )

        reopened = self.db.reopen_campaign(
            campaign_id=campaign_id,
            actor="admin",
            actor_source="test",
            actor_verified=True,
            expected_revision=2,
            idempotency_key="reopen-2",
            reason="one more check",
        )
        self.assertEqual(reopened["campaign"]["campaign"]["config_revision"], 3)
        self.assertEqual(reopened["campaign"]["campaign"]["lifecycle"], "active")
        with self.db.connect() as conn:
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM campaign_close_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone())

    def test_grouped_runs_and_discussion_channels_are_isolated(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO review_worksets (id, baseline_scope, name, selection_source_run_id, source_filter_json, member_count, members_sha256, created_by, created_at) "
                "VALUES (?, ?, ?, ?, '{}', 1, ?, ?, ?)",
                ("ws-group", "scope", "Shared Run group", self.run_a["id"], "f" * 64, "admin", "2026-09-21T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO review_workset_items (workset_id, issue_id, ordinal) VALUES (?, ?, 1)",
                ("ws-group", "cn001"),
            )
        group = self.db.create_campaign_group(
            name="Compare two runs",
            purpose="model_review",
            campaigns=[
                {
                    "purpose": "model_review",
                    "evaluation_run_id": self.run_a["id"],
                    "workset_id": "ws-group",
                    "name": "Run A",
                    "members": [{"issue_id": "cn001", "assignees": ["alice"]}],
                },
                {
                    "purpose": "model_review",
                    "evaluation_run_id": self.run_b["id"],
                    "workset_id": "ws-group",
                    "name": "Run B",
                    "members": [{"issue_id": "cn001", "assignees": ["alice"]}],
                },
            ],
            actor="admin",
            actor_source="test",
            actor_verified=True,
            idempotency_key="group-two-runs",
        )
        self.assertEqual(len(group["campaigns"]), 2)
        self.assertEqual({item["campaign"]["evaluation_run_id"] for item in group["campaigns"]}, {self.run_a["id"], self.run_b["id"]})
        self.assertTrue(self.db.create_campaign_group(
            name="Compare two runs",
            purpose="model_review",
            campaigns=[
                {"purpose": "model_review", "evaluation_run_id": self.run_a["id"], "workset_id": "ws-group", "name": "Run A", "members": [{"issue_id": "cn001", "assignees": ["alice"]}]},
                {"purpose": "model_review", "evaluation_run_id": self.run_b["id"], "workset_id": "ws-group", "name": "Run B", "members": [{"issue_id": "cn001", "assignees": ["alice"]}]},
            ],
            actor="admin",
            actor_source="test",
            actor_verified=True,
            idempotency_key="group-two-runs",
        )["id"] == group["id"])

        campaign_id = group["campaigns"][0]["campaign"]["id"]
        model_comment = self.db.create_review_comment(
            issue_id="cn001", model_run_id=self.run_a["id"], body="Run thread",
            author="alice", author_source="test",
        )
        case_comment = self.db.create_review_comment(
            issue_id="cn001", body="Case thread", author="alice", author_source="test",
            discussion_channel="case", baseline_scope="scope", require_existing_model_run=False,
        )
        campaign_comment = self.db.create_review_comment(
            issue_id="cn001", body="Campaign thread", author="alice", author_source="test",
            discussion_channel="campaign", campaign_id=campaign_id, require_existing_model_run=False,
        )
        self.assertEqual(model_comment["discussion_channel"], "model_review")
        self.assertEqual(case_comment["discussion_channel"], "case")
        self.assertEqual(campaign_comment["discussion_channel"], "campaign")
        self.assertEqual(len(self.db.list_review_comments(issue_id="cn001", model_run_id=self.run_a["id"])), 1)
        self.assertEqual(len(self.db.list_review_comments(issue_id="cn001", discussion_channel="case", baseline_scope="scope")), 1)
        self.assertEqual(len(self.db.list_review_comments(issue_id="cn001", discussion_channel="campaign", campaign_id=campaign_id)), 1)
        with self.assertRaises(ValueError):
            self.db.create_review_comment(
                issue_id="cn001", body="Wrong channel reply", author="alice",
                discussion_channel="campaign", campaign_id=campaign_id,
                reply_to_id=int(case_comment["id"]), require_existing_model_run=False,
            )

    def test_label_analysis_uses_frozen_reference_and_per_issue_requirements(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO review_worksets (
                    id, baseline_scope, name, selection_source_run_id,
                    source_filter_json, member_count, members_sha256, created_by, created_at
                ) VALUES (?, ?, ?, ?, '{}', 2, ?, ?, ?)
                """,
                ("ws-label", "scope", "Labeling workset", self.run_a["id"], "e" * 64, "admin", "2026-09-21T00:00:00Z"),
            )
            conn.executemany(
                "INSERT INTO review_workset_items (workset_id, issue_id, ordinal) VALUES (?, ?, ?)",
                [("ws-label", "cn001", 1), ("ws-label", "cn002", 2)],
            )
        campaign = self.db.create_campaign(
            spec={
                "purpose": "labeling",
                "workset_id": "ws-label",
                "name": "Label analysis",
                "members": [
                    {"issue_id": "cn001", "assignees": ["alice", "bob"]},
                    {"issue_id": "cn002", "assignees": ["alice"]},
                ],
            },
            actor="admin",
            actor_source="test",
            actor_verified=True,
            idempotency_key="create-label-analysis",
        )
        campaign_id = campaign["campaign"]["id"]
        for issue_id, author, output, tags, evidence, excluded in (
            ("cn001", "alice", "正确触发", ["scene:merge"], ["gap:signal"], False),
            ("cn001", "bob", "正确触发", ["scene:merge"], [], False),
            ("cn002", "alice", "误触发", ["scene:parking"], [], True),
        ):
            self.db.create_label_revision(
                issue_id=issue_id,
                expected_output=output,
                tags=tags,
                evidence_gaps=evidence,
                rationale="test label",
                is_excluded=excluded,
                author=author,
                author_source="test",
                author_verified=True,
                task_id=campaign_id,
                source_run_id=self.run_a["id"],
                expected_previous_revision_id=None,
            )
        detail = self.db.get_campaign(campaign_id)
        self.assertEqual(detail["progress"]["required_submitter_count"], 3)
        self.assertEqual(detail["progress"]["completed_issue_count"], 2)
        self.assertEqual(detail["progress"]["label_output_counts"], {"误触发": 1, "正确触发": 1, "无需协助": 0})
        self.assertEqual(detail["progress"]["reference_relation_counts"]["matches_gt"], 2)
        self.assertEqual(detail["progress"]["tag_counts"], {"scene:merge": 1, "scene:parking": 1})
        self.assertEqual(detail["progress"]["evidence_gap_counts"], {"gap:signal": 1})
        self.assertEqual(detail["progress"]["scenario_counts"], {"scenario-a": 1, "scenario-b": 1})
        self.assertEqual(detail["progress"]["excluded_issue_count"], 1)
        self.assertEqual(detail["progress"]["rationale_issue_count"], 2)
        self.assertEqual({item["reference_relation"] for item in detail["issues"]}, {"matches_gt"})
        export = self.db.campaign_label_analysis_export(campaign_id, query="test label")
        self.assertEqual(export["total"], 2)
        self.assertEqual(len(export["issues"][0]["label_revisions"]), 2)
        self.assertIn("test label", export["issues"][0]["label_revisions"][0]["rationale"])
        case_comment = self.db.create_review_comment(
            issue_id="cn001", body="Case public", author="alice", author_source="test",
            discussion_channel="case", baseline_scope="scope", require_existing_model_run=False,
        )
        campaign_comment = self.db.create_review_comment(
            issue_id="cn001", body="Campaign evidence", author="alice", author_source="test",
            discussion_channel="campaign", campaign_id=campaign_id, require_existing_model_run=False,
        )
        self.db.link_label_comment(
            comment_id=campaign_comment["id"], task_id=campaign_id,
            source_run_id=self.run_a["id"], policy_version="test-v1",
        )
        label_comments = self.db.list_label_comments(issue_id="cn001", task_id=campaign_id)
        self.assertEqual({item["discussion_channel"] for item in label_comments}, {"case", "campaign"})
        self.assertIn(case_comment["id"], {item["id"] for item in label_comments})
        self.assertIn(campaign_comment["id"], {item["id"] for item in label_comments})

        self.db.close_campaign(
            campaign_id=campaign_id,
            actor="admin",
            actor_source="test",
            actor_verified=True,
            expected_revision=1,
            idempotency_key="close-label-analysis",
            reason="label set frozen",
        )
        with self.assertRaises(ValueError):
            self.db.create_label_revision(
                issue_id="cn001",
                expected_output="正确触发",
                tags=[],
                evidence_gaps=[],
                rationale="must stay closed",
                is_excluded=False,
                author="alice",
                author_source="test",
                author_verified=True,
                task_id=campaign_id,
                source_run_id=self.run_a["id"],
                expected_previous_revision_id=None,
            )

    def test_legacy_labeling_task_creator_now_creates_canonical_campaign(self) -> None:
        workset = self.db.create_review_workset(
            baseline_scope="scope",
            issue_ids=["cn001"],
            name="Compatibility workset",
            selection_source_run_id=self.run_a["id"],
            created_by="admin",
            created_by_source="test",
            created_by_verified=True,
        )
        task = self.db.create_labeling_task(
            workset_id=workset["id"],
            assignments=[{
                "name": "alice",
                "items": [{"issue_id": "cn001", "assignment_kind": "base", "ordinal": 1}],
            }],
            created_by="admin",
            created_by_source="test",
            created_by_verified=True,
            seed=7,
            reviewers_per_issue=1,
            overlap_ratio=0,
        )
        self.assertEqual(task["purpose"], "labeling")
        self.assertEqual(task["workset_id"], workset["id"])
        detail = self.db.get_campaign(task["id"])
        self.assertEqual(detail["campaign"]["selection_source_run_id"], self.run_a["id"])
        with self.db.connect() as conn:
            split = conn.execute(
                "SELECT purpose, evaluation_run_id, selection_source_run_id FROM issue_work_splits WHERE id = ?",
                (task["id"],),
            ).fetchone()
        self.assertEqual(split["purpose"], "labeling")
        self.assertFalse(split["evaluation_run_id"])
        self.assertFalse(split["selection_source_run_id"])

    def test_legacy_mapping_is_sha_pinned_and_ambiguous_rows_stay_read_only(self) -> None:
        assignments = [
            {"name": "alice", "items": [{"issue_id": "cn001", "assignment_kind": "base", "ordinal": 1}]},
        ]
        legacy = self.db.apply_work_split(
            assignments=assignments,
            created_by="admin",
            reviewers_per_issue=1,
            overlap_ratio=0,
            model_run_id="",
        )
        unresolved = self.db.apply_work_split(
            assignments=[
                {"name": "bob", "items": [{"issue_id": "cn002", "assignment_kind": "base", "ordinal": 1}]},
            ],
            created_by="admin",
            reviewers_per_issue=1,
            overlap_ratio=0,
            model_run_id="",
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO review_worksets (id, baseline_scope, name, selection_source_run_id, source_filter_json, member_count, members_sha256, created_by, created_at) "
                "VALUES (?, ?, ?, '', '{}', 1, ?, ?, ?)",
                ("ws-legacy", "scope", "Legacy labels", "d" * 64, "admin", "2026-09-21T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO review_workset_items (workset_id, issue_id, ordinal) VALUES (?, ?, 1)",
                ("ws-legacy", "cn001"),
            )
            conn.execute(
                "UPDATE issue_work_splits SET task_kind='labeling', workset_id='ws-legacy' WHERE id = ?",
                (legacy["split_id"],),
            )
            source_sha = campaign_inventory_fingerprint(conn)
        inventory = {
            "source_inventory_sha256": source_sha,
            "splits": [
                {"legacy_split_id": legacy["split_id"], "proposed_purpose": "labeling",
                 "mapping_status": "mapped_from_explicit_label_evidence", "mapping_evidence": ["linked_review_workset"]},
                {"legacy_split_id": unresolved["split_id"], "proposed_purpose": None,
                 "mapping_status": "ambiguous_legacy_read_only", "mapping_evidence": []},
            ],
        }
        applied = self.db.apply_legacy_campaign_inventory(
            inventory=inventory, expected_inventory_sha256=source_sha,
            policy_version="test-v1", actor="admin",
        )
        self.assertEqual(applied["mapped"], 1)
        self.assertEqual(applied["read_only"], 1)
        self.assertEqual(applied["inventory_sha256"], source_sha)
        repeated = self.db.apply_legacy_campaign_inventory(
            inventory=inventory, expected_inventory_sha256=source_sha,
            policy_version="test-v1", actor="admin",
        )
        self.assertEqual(repeated["already_applied"], 2)
        migrated = self.db.get_campaign(legacy["split_id"])
        read_only = self.db.get_campaign(unresolved["split_id"])
        self.assertEqual(migrated["campaign"]["purpose"], "labeling")
        self.assertTrue(read_only["campaign"]["legacy_read_only"])
        with self.assertRaises(CampaignReadOnlyError):
            self.db.update_campaign_assignment(
                campaign_id=unresolved["split_id"], issue_id="cn002",
                action="assign", assignee="carol", actor="admin",
                expected_revision=1, idempotency_key="read-only-mutation",
            )


if __name__ == "__main__":
    unittest.main()
