from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.review_analysis import (
    build_review_reason_analysis,
    classify_review_reason,
)


class ReviewReasonAnalysisTest(unittest.TestCase):
    def test_reason_classification_is_explainable_and_multi_label(self) -> None:
        matches = classify_review_reason(
            "模型没有结合 routing 右转方向，也漏掉右侧可绕行空间。"
        )
        self.assertEqual(
            [item["key"] for item in matches],
            ["routing_intent", "passable_space"],
        )
        self.assertIn("routing", matches[0]["matched_keywords"])
        self.assertIn("绕行", matches[1]["matched_keywords"])

        # ASCII keywords use token boundaries: the "ra" inside "camera" must
        # not create an RA/SWAG cluster.
        camera_matches = classify_review_reason("Camera 被大车遮挡")
        self.assertEqual(
            [item["key"] for item in camera_matches],
            ["visibility_modality"],
        )

    def test_analysis_aggregates_latest_review_rows_and_paginates(self) -> None:
        rows = [
            {
                "issue_id": "cn10001",
                "gt_label": "误触发",
                "annotation": {
                    "label": "误触发",
                    "review_status": "reviewed",
                    "tags": [],
                    "missing_evidence": [
                        "routing_direction",
                        "passable_space",
                    ],
                    "note": "右转 routing 和绕行空间都没有判断。",
                },
                "prediction": {"label": "正确触发"},
            },
            {
                "issue_id": "cn10002",
                "gt_label": "无需协助",
                "annotation": {
                    "label": "正确触发",
                    "review_status": "needs_gt_review",
                    "tags": [],
                    "missing_evidence": [],
                    "note": "这个表述暂时无法落到已有主题。",
                },
                "prediction": {"label": ""},
            },
        ]
        result = build_review_reason_analysis(
            rows,
            evidence_catalog={
                "routing_direction": {"label": "routing 方向"},
                "passable_space": {"label": "可绕行空间"},
            },
            page=1,
            page_size=1,
        )
        self.assertEqual(result["summary"]["latest_reviews"], 2)
        self.assertEqual(result["summary"]["with_reason"], 2)
        self.assertEqual(result["summary"]["unclustered_reason"], 1)
        self.assertEqual(result["summary"]["model_mismatches"], 1)
        self.assertEqual(result["summary"]["missing_predictions"], 1)
        self.assertEqual(result["summary"]["manual_gt_disagreements"], 1)
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(
            [item["key"] for item in result["evidence_clusters"]],
            ["passable_space", "routing_direction"],
        )

        routing = build_review_reason_analysis(rows, theme="routing_intent")
        self.assertEqual(routing["total"], 1)
        self.assertEqual(routing["items"][0]["issue_id"], "cn10001")

    def test_database_uses_only_latest_annotation_and_selected_run_failures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            scope = "test-baseline"
            database.upsert_issues(
                [
                    {
                        "issue_id": "cn20001",
                        "gt_label": "误触发",
                        "title": "右转 case",
                    },
                    {
                        "issue_id": "cn20002",
                        "gt_label": "正确触发",
                        "title": "正常触发",
                    },
                ],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = database.import_model_run(
                name="test run",
                source_name="test.json",
                source_sha256="1" * 64,
                metadata={},
                rows=[
                    {
                        "issue_id": "cn20001",
                        "model_label": "正确触发",
                        "model_reason": "排队",
                    },
                    {
                        "issue_id": "cn20002",
                        "model_label": "正确触发",
                        "model_reason": "正确",
                    },
                ],
            )
            database.create_annotation(
                issue_id="cn20001",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=["routing_direction"],
                note="旧版本：routing 缺失",
                author="alice",
            )
            database.create_annotation(
                issue_id="cn20001",
                label="误触发",
                review_status="reviewed",
                tags=["temporary_stop"],
                missing_evidence=["hazard_signal"],
                note="最新版本：双闪遗漏",
                author="bob",
            )
            database.create_annotation(
                issue_id="cn20002",
                label="正确触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="判断正确",
                author="alice",
            )

            failures = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run["id"],
                failure_only=True,
            )
            self.assertEqual([item["issue_id"] for item in failures], ["cn20001"])
            self.assertEqual(failures[0]["annotation"]["author"], "bob")
            self.assertEqual(
                failures[0]["annotation"]["missing_evidence"],
                ["hazard_signal"],
            )

            old_note_search = database.review_reason_rows(
                baseline_scope=scope,
                search="旧版本",
            )
            self.assertEqual(old_note_search, [])


if __name__ == "__main__":
    unittest.main()
