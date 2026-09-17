from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database, LabelAnnotationConflictError
from ra_triage_dashboard.app.labeling_migration import migrate_legacy_labeling
from ra_triage_dashboard.app.routers.labeling import _public_label_attachment
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class CaseLabelingTest(unittest.TestCase):
    def make_db(self, root: str) -> Database:
        database = Database(Path(root) / "labeling.sqlite")
        database.init()
        database.upsert_issues(
            [
                {"issue_id": "cn1", "gt_label": "正确触发"},
                {"issue_id": "cn2", "gt_label": ""},
            ],
            source="test",
            replace_gt=True,
            baseline_scope="scope",
        )
        return database

    def test_free_label_revision_is_independent_gt_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            saved = database.create_label_revision(
                issue_id="cn1",
                expected_output="误触发",
                tags=["traffic_light"],
                evidence_gaps=[],
                rationale="GT 应为误触发",
                is_excluded=False,
                author="alice",
                author_source="kylin_ticket",
                author_verified=True,
                expected_previous_revision_id=None,
                attachments=[{
                    "id": "22222222-2222-4222-8222-222222222222",
                    "original_name": "new.png", "stored_name": "new.png",
                    "media_type": "image/png", "size_bytes": 20,
                    "width": 4, "height": 4, "sha256": "b" * 64,
                }],
            )
            label_case = saved["label_case"]
            self.assertEqual(label_case["resolution"]["state"], "resolved")
            self.assertEqual(label_case["resolution"]["method"], "single")
            detail = database.get_label_case(label_case["id"])
            self.assertEqual(len(detail["revisions"][0]["attachments"]), 1)
            self.assertEqual(
                database.get_label_attachment("22222222-2222-4222-8222-222222222222")["stored_name"],
                "new.png",
            )
            candidates = database.label_gt_candidates(["scope"])
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["issue_id"], "cn1")
            self.assertEqual(candidates[0]["expected_output"], "误触发")

    def test_public_label_attachment_exposes_only_opaque_url(self) -> None:
        public = _public_label_attachment({
            "id": "asset-1", "original_name": "private.png",
            "stored_name": "server-path.png", "media_type": "image/png",
            "size_bytes": 10, "width": 2, "height": 2, "sha256": "a" * 64,
        })
        self.assertNotIn("stored_name", public)
        self.assertNotIn("sha256", public)
        self.assertNotIn("original_name", public)
        self.assertTrue(public["url"].endswith("/api/labeling/attachments/asset-1"))

    def test_task_conflict_requires_adjudication_and_stales_on_new_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            assignments = distribute_issue_ids(
                ["cn1"],
                [{"name": "alice"}, {"name": "bob"}],
                seed=1,
                reviewers_per_issue=2,
            )
            split = database.apply_work_split(
                assignments=assignments,
                created_by="admin",
                reviewers_per_issue=2,
            )
            workset = database.create_review_workset(
                baseline_scope="scope",
                issue_ids=["cn1"],
                name="double label",
                created_by="admin",
            )
            database.bind_labeling_task(task_id=split["split_id"], workset_id=workset["id"])
            alice = database.create_label_revision(
                issue_id="cn1", task_id=split["split_id"],
                expected_output="误触发", tags=[], evidence_gaps=[], rationale="a",
                is_excluded=False, author="alice", author_source="kylin_ticket",
                author_verified=True, expected_previous_revision_id=None,
            )
            bob = database.create_label_revision(
                issue_id="cn1", task_id=split["split_id"],
                expected_output="正确触发", tags=[], evidence_gaps=[], rationale="b",
                is_excluded=False, author="bob", author_source="kylin_ticket",
                author_verified=True, expected_previous_revision_id=None,
            )
            label_case = bob["label_case"]
            self.assertEqual(label_case["resolution"]["state"], "conflict")
            blocked = database.label_gt_candidates(["scope"])
            self.assertEqual(blocked[0]["status"], "unresolved")
            self.assertEqual(blocked[0]["blocked_sources"][0]["state"], "conflict")
            source_ids = [item["id"] for item in label_case["resolution"]["heads"]]
            adjudicated = database.adjudicate_label_case(
                label_case_id=label_case["id"],
                source_revision_ids=source_ids,
                expected_output="误触发",
                tags=[], evidence_gaps=[], rationale="裁决采用误触发",
                is_excluded=False, actor="carol", actor_source="kylin_ticket",
                actor_verified=True, expected_previous_resolution_id=None,
            )
            self.assertEqual(adjudicated["resolution"]["method"], "adjudication")
            self.assertEqual(adjudicated["resolution"]["expected_output"], "误触发")
            alice_next = database.create_label_revision(
                issue_id="cn1", task_id=split["split_id"],
                expected_output="正确触发", tags=[], evidence_gaps=[], rationale="a2",
                is_excluded=False, author="alice", author_source="kylin_ticket",
                author_verified=True,
                expected_previous_revision_id=alice["id"],
            )
            self.assertEqual(alice_next["label_case"]["resolution"]["state"], "stale")
            blocked = database.label_gt_candidates(["scope"])
            self.assertEqual(blocked[0]["status"], "unresolved")
            self.assertEqual(blocked[0]["blocked_sources"][0]["state"], "stale")

    def test_free_label_cannot_be_adjudicated_as_task_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            first = database.create_label_revision(
                issue_id="cn1", expected_output="误触发", tags=[], evidence_gaps=[],
                rationale="first", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=None,
            )
            database.create_label_revision(
                issue_id="cn1", expected_output="正确触发", tags=[], evidence_gaps=[],
                rationale="second", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=first["id"],
            )
            with self.assertRaisesRegex(ValueError, "自由标注"):
                database.adjudicate_label_case(
                    label_case_id=first["label_case"]["id"],
                    source_revision_ids=[first["id"]],
                    expected_output="误触发", tags=[], evidence_gaps=[], rationale="stale",
                    is_excluded=False, actor="writer", actor_source="kylin_ticket",
                    actor_verified=True, expected_previous_resolution_id=None,
                )

    def test_gt_export_preview_detects_source_or_gt_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            first = database.create_label_revision(
                issue_id="cn1", expected_output="误触发", tags=[], evidence_gaps=[],
                rationale="candidate", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=None,
            )
            preview = database.create_label_gt_export_preview(
                baseline_scopes=["scope"], created_by="alice",
                created_by_source="kylin_ticket", created_by_verified=True,
            )
            self.assertEqual(preview["item_count"], 1)
            self.assertEqual(database.validate_label_gt_export_batch(preview["id"])["stale_issue_ids"], [])
            database.create_label_revision(
                issue_id="cn1", expected_output="无需协助", tags=[], evidence_gaps=[],
                rationale="changed", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=first["id"],
            )
            stale = database.validate_label_gt_export_batch(preview["id"])
            self.assertEqual(stale["status"], "stale")
            self.assertEqual(stale["stale_issue_ids"], ["cn1"])

    def test_legacy_labeling_migration_preserves_rationale_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            legacy = database.create_annotation(
                issue_id="cn1", model_run_id="", work_split_id="",
                label="误触发", review_status="needs_gt_review",
                tags=["traffic_light"], missing_evidence=["missing_camera"],
                note="原始标注依据", author="alice",
                author_source="kylin_ticket", author_verified=True,
                attachments=[{
                    "id": "11111111-1111-4111-8111-111111111111",
                    "original_name": "evidence.png",
                    "stored_name": "evidence.png",
                    "media_type": "image/png",
                    "size_bytes": 10,
                    "width": 2,
                    "height": 2,
                    "sha256": "a" * 64,
                }],
                expected_previous_annotation_id=None,
            )
            comment = database.create_review_comment(
                issue_id="cn1", model_run_id="", body="原始标注讨论",
                author="alice", author_source="kylin_ticket", author_verified=True,
            )
            first = migrate_legacy_labeling(
                database,
                scopes=["scope"],
                tag_catalog=[],
                policy_version="test-v1",
            )
            second = migrate_legacy_labeling(
                database,
                scopes=["scope"],
                tag_catalog=[],
                policy_version="test-v1",
            )
            self.assertEqual(first["revision_count"], 1)
            self.assertEqual(second["revision_count"], 1)
            cases = database.label_cases_for_issue("cn1")
            self.assertEqual(len(cases), 1)
            detail = database.get_label_case(cases[0]["id"])
            self.assertEqual(len(detail["revisions"]), 1)
            self.assertEqual(detail["revisions"][0]["source_annotation_id"], legacy["id"])
            self.assertEqual(detail["revisions"][0]["rationale"], "原始标注依据")
            self.assertEqual(detail["revisions"][0]["evidence_gaps"], ["missing_camera"])
            self.assertEqual(len(detail["revisions"][0]["attachments"]), 1)
            self.assertEqual(
                detail["revisions"][0]["attachments"][0]["source_review_attachment_id"],
                "11111111-1111-4111-8111-111111111111",
            )
            comments = database.list_label_comments(issue_id="cn1")
            self.assertEqual([item["id"] for item in comments], [comment["id"]])
            self.assertEqual(comments[0]["body"], "原始标注讨论")
            with self.assertRaisesRegex(ValueError, "迁移后的标注来源"):
                database.delete_annotation(issue_id="cn1", annotation_id=legacy["id"])

    def test_legacy_blind_task_migrates_as_labeling_workset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            assignments = distribute_issue_ids(
                ["cn1"], [{"name": "alice"}, {"name": "bob"}],
                seed=2, reviewers_per_issue=2,
            )
            split = database.apply_work_split(
                assignments=assignments, created_by="admin",
                reviewers_per_issue=2,
            )
            for author, label in (("alice", "误触发"), ("bob", "正确触发")):
                database.create_annotation(
                    issue_id="cn1", model_run_id="",
                    work_split_id=split["split_id"], label=label,
                    review_status="needs_gt_review", tags=[], missing_evidence=[],
                    note=f"{author} rationale", author=author,
                    author_source="kylin_ticket", author_verified=True,
                    expected_previous_annotation_id=None,
                )
            migrated = migrate_legacy_labeling(
                database, scopes=["scope"], tag_catalog=[], policy_version="test-task-v1"
            )
            self.assertEqual(migrated["task_count"], 1)
            tasks = database.list_labeling_tasks(["scope"])
            self.assertEqual([item["id"] for item in tasks], [split["split_id"]])
            cases = database.label_cases_for_issue("cn1", split["split_id"])
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["resolution"]["state"], "conflict")
            self.assertEqual(cases[0]["resolution"]["submitted_count"], 2)


if __name__ == "__main__":
    unittest.main()
