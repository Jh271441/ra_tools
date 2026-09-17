from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.labeling_migration import (
    labeling_inventory_fingerprint,
    migrate_legacy_labeling,
    reconcile_legacy_labeling,
)
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class LabelingReconciliationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / "labeling.sqlite")
        self.database.init()
        self.database.upsert_issues(
            [{"issue_id": "cn1", "gt_label": "正确触发"},
             {"issue_id": "cn2", "gt_label": ""}],
            source="fixture", replace_gt=True, baseline_scope="scope",
        )
        self.annotation = self.database.create_annotation(
            issue_id="cn1", label="误触发", review_status="needs_gt_review",
            tags=["traffic_light"], missing_evidence=["missing_camera"],
            note="原文\n含空白  ", author="alice", author_source="kylin_ticket",
            author_verified=True,
            attachments=[{
                "id": "review-attachment", "original_name": "evidence.png",
                "stored_name": "review.png", "media_type": "image/png",
                "size_bytes": 12, "width": 2, "height": 2, "sha256": "a" * 64,
            }],
        )
        self.comment = self.database.create_review_comment(
            issue_id="cn1", body="讨论", author="alice",
            author_source="kylin_ticket", author_verified=True,
            attachments=[{
                "id": "comment-attachment", "original_name": "comment.png",
                "stored_name": "comment.png", "media_type": "image/png",
                "size_bytes": 8, "width": 2, "height": 2, "sha256": "b" * 64,
            }],
        )

    def migrate(self) -> dict:
        return migrate_legacy_labeling(
            self.database, scopes=["scope"], tag_catalog=[], policy_version="test-v1"
        )

    def reconcile(self) -> dict:
        return reconcile_legacy_labeling(
            self.database, scopes=["scope"], policy_version="test-v1", tag_catalog=[]
        )

    def test_reconciliation_preserves_content_and_does_not_claim_file_verification(self) -> None:
        self.migrate()
        result = self.reconcile()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["source_attachment_count"], 1)
        self.assertEqual(result["mapped_attachment_count"], 1)
        self.assertEqual(result["attachment_file_verification"], "not_performed")

    def test_reconciliation_rejects_target_content_or_attachment_corruption(self) -> None:
        self.migrate()
        with self.database.connect() as conn:
            conn.execute("UPDATE label_revisions SET rationale = '改写', author_verified = 0")
            conn.execute("UPDATE label_attachments SET sha256 = 'wrong'")
        result = self.reconcile()
        self.assertFalse(result["passed"])
        mismatch_by_kind = {item["kind"]: item for item in result["content_mismatches"]}
        self.assertIn("rationale", mismatch_by_kind["annotation"]["fields"])
        self.assertIn("author_verified", mismatch_by_kind["annotation"]["fields"])
        self.assertIn("sha256", mismatch_by_kind["attachment"]["fields"])

    def test_reconciliation_rejects_missing_attachment_even_when_mapping_ids_match(self) -> None:
        self.migrate()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM label_attachments")
        result = self.reconcile()
        self.assertFalse(result["passed"])
        self.assertEqual(result["mapped_annotation_count"], result["source_annotation_count"])
        self.assertEqual(result["missing_attachment_ids"], ["review-attachment"])

    def test_fingerprint_covers_previously_omitted_source_fields(self) -> None:
        previous = labeling_inventory_fingerprint(self.database, scopes=["scope"])
        for sql in (
            "UPDATE annotations SET is_excluded = 1",
            "UPDATE review_comments SET author_verified = 0",
            "UPDATE review_attachments SET size_bytes = 15",
            "UPDATE comment_attachments SET sha256 = 'changed'",
        ):
            with self.subTest(sql=sql):
                with self.database.connect() as conn:
                    conn.execute(sql)
                current = labeling_inventory_fingerprint(self.database, scopes=["scope"])
                self.assertNotEqual(previous, current)
                previous = current

    def test_repeated_backfill_does_not_hide_stale_copied_content(self) -> None:
        with self.database.connect() as conn:
            source = conn.execute("SELECT note FROM annotations").fetchone()
        original_note = source["note"]
        self.migrate()
        with self.database.connect() as conn:
            conn.execute("UPDATE annotations SET note = '源正文变化'")
        self.migrate()
        result = self.reconcile()
        self.assertFalse(result["passed"])
        self.assertIn("rationale", result["content_mismatches"][0]["fields"])
        with self.database.connect() as conn:
            target = conn.execute("SELECT rationale FROM label_revisions").fetchone()
        self.assertEqual(target["rationale"], original_note)

    def test_fingerprint_covers_live_assignment_and_transfer_history(self) -> None:
        assignments = distribute_issue_ids(
            ["cn1", "cn2"], [{"name": "alice"}, {"name": "bob"}], seed=5
        )
        split = self.database.apply_work_split(assignments=assignments, created_by="admin")
        self.migrate()
        self.assertTrue(self.reconcile()["passed"])
        previous = labeling_inventory_fingerprint(self.database, scopes=["scope"])
        with self.database.connect() as conn:
            conn.execute("UPDATE review_work_assignments SET assigned_by = 'other'")
        changed = labeling_inventory_fingerprint(self.database, scopes=["scope"])
        self.assertNotEqual(previous, changed)
        with self.database.connect() as conn:
            conn.execute(
                """INSERT INTO review_work_assignment_changes
                   (split_id, issue_id, from_assignee, to_assignee, changed_by, changed_at)
                   VALUES (?, 'cn1', 'alice', 'bob', 'admin', '2026-09-18T00:00:00+00:00')""",
                (split["split_id"],),
            )
        self.assertNotEqual(changed, labeling_inventory_fingerprint(self.database, scopes=["scope"]))
        self.assertFalse(self.reconcile()["passed"])

    def test_source_change_during_backfill_cannot_be_certified(self) -> None:
        original = self.database.migrate_legacy_label_revision

        def migrate_then_change(**kwargs):
            result = original(**kwargs)
            with self.database.connect() as conn:
                conn.execute("UPDATE annotations SET note = '并发更新'")
            return result

        with patch.object(self.database, "migrate_legacy_label_revision", migrate_then_change):
            with self.assertRaisesRegex(ValueError, "回填期间源数据发生变化"):
                self.migrate()
        self.assertEqual(self.database.labeling_scope_states(["scope"]), [])

    def test_version_edge_and_comment_context_are_reconciled(self) -> None:
        self.database.create_annotation(
            issue_id="cn1", label="无需协助", review_status="needs_gt_review",
            tags=[], missing_evidence=[], note="新版", author="alice",
        )
        self.migrate()
        self.assertTrue(self.reconcile()["passed"])
        with self.database.connect() as conn:
            conn.execute("UPDATE label_revisions SET supersedes_id = NULL WHERE supersedes_id IS NOT NULL")
            conn.execute("UPDATE label_comment_links SET source_run_id = 'wrong'")
        result = self.reconcile()
        self.assertFalse(result["passed"])
        fields = {field for item in result["content_mismatches"] for field in item["fields"]}
        self.assertIn("supersedes_id", fields)
        self.assertIn("source_run_id", fields)


if __name__ == "__main__":
    unittest.main()
