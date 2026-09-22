from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database


class LegacyCutoverDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "s6.sqlite")
        self.db.init()
        self.db.upsert_issues(
            [
                {"issue_id": "s6-model", "gt_label": "正确触发"},
                {"issue_id": "s6-label", "gt_label": "无需协助"},
                {"issue_id": "s6-mixed", "gt_label": "正确触发"},
            ],
            source="s6-test", replace_gt=True, baseline_scope="s6-scope",
        )

    def test_classification_is_append_only_and_idempotent(self) -> None:
        run, _ = self.db.import_model_run(
            name="s6-run", source_name="s6.json", source_sha256="s6-run-hash", metadata={},
            rows=[{"issue_id": "s6-model", "model_label": "正确触发"}],
        )
        self.db.create_annotation(
            issue_id="s6-model", model_run_id=run["id"], label="", review_status="reviewed",
            tags=[], missing_evidence=[], note="", author="reviewer",
        )
        self.db.create_annotation(
            issue_id="s6-label", label="误触发", review_status="reviewed",
            tags=["legacy"], missing_evidence=[], note="label history", author="reviewer",
        )
        self.db.create_annotation(
            issue_id="s6-mixed", model_run_id=run["id"], label="误触发",
            review_status="reviewed", tags=["tag"], missing_evidence=[], note="mixed", author="reviewer",
        )
        dry = self.db.classify_legacy_annotations(scopes=["s6-scope"], apply=False)
        self.assertEqual(dry["counts"]["model_review_mapped"], 1)
        self.assertEqual(dry["counts"]["label_history_mapped"], 1)
        self.assertEqual(dry["counts"]["legacy_mixed"], 1)
        applied = self.db.classify_legacy_annotations(scopes=["s6-scope"], apply=True)
        self.assertTrue(applied["applied"])
        replay = self.db.classify_legacy_annotations(scopes=["s6-scope"], apply=True)
        self.assertEqual(len(self.db.legacy_classifications(["s6-scope"])), 3)
        self.assertEqual(replay["counts"], applied["counts"])

    def test_read_policy_is_epoch_guarded_and_canonical_projection_is_exact(self) -> None:
        policy = self.db.set_legacy_read_policy(
            baseline_scope="s6-scope", policy="shadow", policy_version="s6-v1",
            inventory_sha256="a" * 64, updated_by="admin", expected_epoch=0,
        )
        self.assertEqual(policy["epoch"], 1)
        with self.assertRaises(ValueError):
            self.db.set_legacy_read_policy(
                baseline_scope="s6-scope", policy="canonical", policy_version="s6-v1",
                inventory_sha256="a" * 64, updated_by="stale", expected_epoch=0,
            )
        projection = self.db.canonical_issue_projection(
            issue_id="s6-model", model_run_id="missing-run", campaign_id="", reference_id="", reviewer="reviewer",
        )
        self.assertIsNotNone(projection)
        self.assertIsNone(projection["model_review"])

    def test_shadow_receipt_and_legacy_resolver_preserve_source(self) -> None:
        annotation = self.db.create_annotation(
            issue_id="s6-label", label="误触发", review_status="reviewed",
            tags=[], missing_evidence=[], note="historic", author="reviewer",
        )
        self.db.classify_legacy_annotations(scopes=["s6-scope"], apply=True)
        resolved = self.db.resolve_legacy_evidence(kind="annotation", value=str(annotation["id"]))
        self.assertEqual(resolved["source_id"], annotation["id"])
        receipt = self.db.record_legacy_shadow_receipt(
            baseline_scope="s6-scope", component="gallery", policy_version="s6-v1",
            inventory_sha256="b" * 64, legacy_count=3, canonical_count=2,
            diffs=[{"kind": "legacy_mixed", "issue_id": "s6-mixed"}],
            expected_diffs=["legacy_mixed"],
        )
        self.assertEqual(receipt["status"], "expected_diff")
        self.assertEqual(len(self.db.legacy_shadow_receipts(["s6-scope"])), 1)


if __name__ == "__main__":
    unittest.main()
