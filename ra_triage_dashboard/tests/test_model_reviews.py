from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.model_reviews import MODEL_REVIEW_PUBLIC_ID_OFFSET


class ModelReviewStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "model-review.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues(
            [{"issue_id": "cn1", "gt_label": "正确触发"}],
            source="test",
            replace_gt=True,
            baseline_scope="scope",
        )
        rows = [{"issue_id": "cn1", "model_label": "误触发"}]
        self.run_a, _ = self.db.import_model_run(
            name="run-a", source_name="a.json", source_sha256="a" * 64,
            metadata={}, rows=rows,
        )
        self.run_b, _ = self.db.import_model_run(
            name="run-b", source_name="b.json", source_sha256="b" * 64,
            metadata={}, rows=rows,
        )

    def create(self, run_id: str, status: str, reason: str, **kwargs):
        return self.db.create_model_review(
            issue_id="cn1",
            model_run_id=run_id,
            status=status,
            reason=reason,
            missing_evidence=kwargs.pop("missing_evidence", []),
            reviewer=kwargs.pop("reviewer", "alice"),
            **kwargs,
        )

    def test_status_transitions_are_append_only_and_headed(self) -> None:
        pending = self.create(self.run_a["id"], "pending", "")
        progress = self.create(
            self.run_a["id"], "in_progress", "checking routing",
            expected_previous_annotation_id=pending["id"],
        )
        completed = self.create(
            self.run_a["id"], "completed", "routing direction was missed",
            missing_evidence=["routing_direction"],
            expected_previous_annotation_id=progress["id"],
        )
        revisions = self.db.model_review_revisions(
            issue_id="cn1", model_run_id=self.run_a["id"]
        )
        self.assertEqual(
            [item["model_review_status"] for item in revisions],
            ["completed", "in_progress", "pending"],
        )
        self.assertEqual(completed["supersedes_id"], progress["id"])
        current = self.db.current_model_review(
            issue_id="cn1", model_run_id=self.run_a["id"], reviewer="alice"
        )
        self.assertEqual(current["id"], completed["id"])
        self.assertGreater(current["id"], MODEL_REVIEW_PUBLIC_ID_OFFSET)

    def test_run_isolation_and_compatibility_projection(self) -> None:
        run_a = self.create(self.run_a["id"], "completed", "run A reason")
        run_b = self.create(self.run_b["id"], "blocked_by_label", "run B reason")
        row_a = self.db.list_cases(
            baseline_scopes=["scope"], model_run_id=self.run_a["id"], page_size=10
        )["items"][0]["annotation"]
        row_b = self.db.list_cases(
            baseline_scopes=["scope"], model_run_id=self.run_b["id"], page_size=10
        )["items"][0]["annotation"]
        self.assertEqual(row_a["id"], run_a["id"])
        self.assertEqual(row_a["note"], "run A reason")
        self.assertEqual(row_a["model_review_status"], "completed")
        self.assertEqual(row_b["id"], run_b["id"])
        self.assertEqual(row_b["note"], "run B reason")
        self.assertEqual(row_b["model_review_status"], "blocked_by_label")

    def test_new_head_wins_while_legacy_history_remains(self) -> None:
        legacy = self.db.create_annotation(
            issue_id="cn1", model_run_id=self.run_a["id"], label="误触发",
            review_status="needs_gt_review", tags=[], missing_evidence=[],
            note="legacy reason", author="alice",
        )
        new = self.create(
            self.run_a["id"], "in_progress", "new reason",
            expected_previous_annotation_id=legacy["id"],
        )
        case = self.db.get_case("cn1")
        self.assertEqual(case["annotations"][0]["id"], new["id"])
        self.assertEqual(case["annotations"][0]["review_domain"], "model_review")
        self.assertTrue(any(item["id"] == legacy["id"] for item in case["annotations"]))
        shadow = self.db.model_review_shadow_comparison(
            model_run_id=self.run_a["id"], baseline_scopes=["scope"]
        )
        self.assertEqual(shadow["counts"]["different"], 1)

    def test_shadow_does_not_compare_legacy_gt_status_as_model_progress(self) -> None:
        legacy = self.db.create_annotation(
            issue_id="cn1", model_run_id=self.run_a["id"], label="误触发",
            review_status="needs_gt_review", tags=[], missing_evidence=["routing_direction"],
            note="same diagnosis", author="alice",
        )
        current = self.create(
            self.run_a["id"], "completed", "same diagnosis",
            missing_evidence=["routing_direction"],
        )
        self.assertEqual(current["legacy_base_annotation_id"], legacy["id"])
        shadow = self.db.model_review_shadow_comparison(
            model_run_id=self.run_a["id"], baseline_scopes=["scope"]
        )
        self.assertEqual(shadow["counts"]["matched"], 1)

    def test_attachment_metadata_belongs_to_model_review_revision(self) -> None:
        attachment = {
            "id": "attachment-1", "original_name": "evidence.png",
            "stored_name": "evidence.png", "media_type": "image/png",
            "size_bytes": 4, "width": 1, "height": 1, "sha256": "c" * 64,
        }
        review = self.create(
            self.run_a["id"], "completed", "with evidence",
            attachments=[attachment],
        )
        stored = self.db.get_model_review_attachment("attachment-1")
        self.assertEqual(int(stored["annotation_id"]), review["id"])
        self.assertEqual(str(stored["review_domain"]), "model_review")

    def test_facets_use_current_heads_only(self) -> None:
        first = self.create(self.run_a["id"], "pending", "")
        self.create(
            self.run_a["id"], "completed", "done",
            expected_previous_annotation_id=first["id"],
        )
        facets = self.db.model_review_facets(
            model_run_id=self.run_a["id"], baseline_scopes=["scope"]
        )
        self.assertEqual(facets["total"], 1)
        self.assertEqual(facets["statuses"], [{"value": "completed", "count": 1}])
        self.assertEqual(
            facets["reviewers"],
            [{"value": "alice", "count": 1, "verified_count": 0, "unverified_count": 1}],
        )

    def test_reviewer_facets_preserve_verified_sso_counts(self) -> None:
        self.create(
            self.run_a["id"], "completed", "verified", reviewer="alice",
            reviewer_source="sso", reviewer_verified=True,
        )
        self.create(
            self.run_a["id"], "completed", "unverified", reviewer="bob",
            reviewer_source="legacy", reviewer_verified=False,
        )
        facets = self.db.model_review_facets(
            model_run_id=self.run_a["id"], baseline_scopes=["scope"]
        )
        self.assertEqual(
            facets["reviewers"],
            [
                {"value": "alice", "count": 1, "verified_count": 1, "unverified_count": 0},
                {"value": "bob", "count": 1, "verified_count": 0, "unverified_count": 1},
            ],
        )

    def test_model_review_status_filter_uses_s3_domain(self) -> None:
        completed = self.create(self.run_a["id"], "completed", "done")
        pending = self.create(self.run_b["id"], "pending", "")
        result = self.db.list_cases(
            baseline_scopes=["scope"],
            model_run_id=self.run_a["id"],
            model_review_status="completed",
            page_size=10,
        )
        self.assertEqual([item["annotation"]["id"] for item in result["items"]], [completed["id"]])
        self.assertNotEqual(completed["id"], pending["id"])
        overview = self.db.overview(
            baseline_scopes=["scope"], model_run_id=self.run_a["id"]
        )
        self.assertEqual(overview["model_review_status_counts"]["completed"], 1)
        self.assertEqual(overview["reviewed_failures"], 1)

    def test_label_conflict_forces_blocked_state(self) -> None:
        review = self.create(
            self.run_a["id"], "completed", "diagnosis finished",
            label_state={"state": "conflict", "expected_output": ""},
        )
        self.assertEqual(review["model_review_status"], "blocked_by_label")
        self.assertEqual(review["review_status"], "needs_gt_review")


if __name__ == "__main__":
    unittest.main()
