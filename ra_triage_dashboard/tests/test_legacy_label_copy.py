from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.legacy_label_copy import apply_legacy_label_copy, plan_legacy_label_copy


class LegacyLabelCopyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "label-copy.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues(
            [
                {"issue_id": "cn1", "gt_label": "正确触发"},
                {"issue_id": "cn2", "gt_label": "误触发"},
                {"issue_id": "cn3", "gt_label": "无需协助"},
                {"issue_id": "cn4", "gt_label": "正确触发"},
            ],
            source="test",
            replace_gt=True,
            baseline_scope="scope",
        )
        self.db.apply_gt_sync_snapshot(
            scope="scope",
            rows=[
                {"issue_id": "cn1", "gt_label": "正确触发"},
                {"issue_id": "cn2", "gt_label": "误触发"},
                {"issue_id": "cn3", "gt_label": "无需协助"},
                {"issue_id": "cn4", "gt_label": "正确触发"},
            ],
            source_name="Trail",
            source_view_id=1000,
            source_field="ra_merge_result",
            trigger="test",
            requested_by="tester",
            requested_by_source="test",
            requested_by_verified=True,
            expected_issue_ids=["cn1", "cn2", "cn3", "cn4"],
        )
        self.runs = []
        for index in range(2):
            run, _ = self.db.import_model_run(
                name=f"run-{index}",
                source_name=f"run-{index}.json",
                source_sha256=str(index + 1) * 64,
                metadata={},
                rows=[{"issue_id": issue, "model_label": "误触发"} for issue in ("cn1", "cn2", "cn3", "cn4")],
            )
            self.runs.append(run)

    def add(self, issue_id: str, run_index: int, label: str, status: str, author: str) -> dict:
        return self.db.create_annotation(
            issue_id=issue_id,
            model_run_id=self.runs[run_index]["id"],
            label=label,
            review_status=status,
            tags=["reason-only-tag"],
            missing_evidence=["camera"],
            note="model diagnosis must stay in Review",
            author=author,
            author_source="test",
            author_verified=True,
        )

    def test_label_only_copy_is_deduped_frozen_and_idempotent(self) -> None:
        first = self.add("cn1", 0, "误触发", "needs_gt_review", "alice")
        second = self.add("cn1", 1, "误触发", "needs_gt_review", "alice")
        self.add("cn2", 0, "误触发", "reviewed", "alice")
        self.add("cn2", 1, "正确触发", "needs_gt_review", "bob")
        self.add("cn3", 0, "", "pending", "alice")
        self.add("cn4", 0, "", "reviewed", "alice")
        with self.db.connect() as conn:
            before = [dict(row) for row in conn.execute("SELECT * FROM annotations ORDER BY id").fetchall()]

        plan = plan_legacy_label_copy(self.db, scopes=["scope"])
        stats = plan["reports"][0]
        self.assertEqual(stats["scanned_reviews"], 6)
        self.assertEqual(stats["effective_label_sources"], 5)
        self.assertEqual(stats["reviewer_dedup_votes"], 4)
        self.assertEqual(stats["resolved_cases"], 2)
        self.assertEqual(stats["conflict_cases"], 1)
        self.assertEqual(stats["gt_review_pending_cases"], 2)
        self.assertEqual(stats["skipped_no_label_sources"], 1)

        applied = apply_legacy_label_copy(self.db, scopes=["scope"], imported_by="tester")
        self.assertFalse(applied["applied"][0]["duplicate"])
        cn1 = self.db.project_issue_label_states("scope", ["cn1"])["cn1"]
        self.assertEqual(cn1["state"], "resolved")
        self.assertEqual(cn1["expected_output"], "误触发")
        self.assertTrue(cn1["gt_review_pending"])
        imported_source = next(item for item in cn1["sources"] if item["source_type"] == "legacy_model_review")
        self.assertEqual(
            [item["source_annotation_id"] for item in imported_source["legacy_sources"]],
            [first["id"], second["id"]],
        )
        self.assertEqual(imported_source["frozen_gt_label"], "正确触发")
        self.assertTrue(imported_source["frozen_gt_snapshot_id"])
        cn2 = self.db.project_issue_label_states("scope", ["cn2"])["cn2"]
        self.assertEqual(cn2["state"], "conflict")
        cn4 = self.db.project_issue_label_states("scope", ["cn4"])["cn4"]
        self.assertEqual(cn4["expected_output"], "正确触发")
        self.assertEqual(cn4["gt_relation"], "matches_gt")
        self.assertEqual(self.db.project_issue_label_states("scope", ["cn3"])["cn3"]["state"], "none")

        replay = apply_legacy_label_copy(self.db, scopes=["scope"], imported_by="tester")
        self.assertTrue(replay["applied"][0]["duplicate"])
        self.assertEqual(replay["applied"][0]["inserted_votes"], 0)
        self.assertEqual(replay["applied"][0]["inserted_sources"], 0)
        batches = self.db.list_label_import_batches(["scope"], "legacy_model_review")
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["status"], "imported")
        with self.db.connect() as conn:
            after = [dict(row) for row in conn.execute("SELECT * FROM annotations ORDER BY id").fetchall()]
            copied = conn.execute("SELECT * FROM label_revisions ORDER BY id").fetchall()
        self.assertEqual(json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True))
        self.assertTrue(all(not row["rationale"] and row["tags_json"] == "[]" and row["evidence_gaps_json"] == "[]" for row in copied))
