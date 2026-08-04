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
            {
                "issue_id": "cn10003",
                "gt_label": "正确触发",
                "annotation": {
                    "label": "正确触发",
                    "review_status": "reviewed",
                    "tags": [],
                    "missing_evidence": [],
                    "note": "",
                },
                "prediction": {"label": "正确触发"},
            },
        ]
        result = build_review_reason_analysis(
            rows,
            evidence_catalog={
                "routing_direction": {"label": "routing 方向"},
                "passable_space": {"label": "可绕行空间"},
            },
            has_model_run=True,
            page=1,
            page_size=1,
        )
        self.assertEqual(result["summary"]["latest_reviews"], 3)
        self.assertEqual(result["summary"]["with_reason"], 2)
        self.assertEqual(result["summary"]["unclustered_reason"], 1)
        self.assertEqual(result["summary"]["model_matches"], 1)
        self.assertEqual(result["summary"]["model_mismatches"], 1)
        self.assertEqual(result["summary"]["missing_predictions"], 1)
        self.assertEqual(result["summary"]["manual_gt_disagreements"], 1)
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["comparison_status"], "mismatch")
        self.assertEqual(
            result["confusion"]["model_labels"],
            ["误触发", "正确触发", "无需协助", "NONE"],
        )
        self.assertEqual(result["confusion"]["matches"], 1)
        self.assertEqual(result["confusion"]["mismatches"], 1)
        self.assertEqual(result["confusion"]["none"], 1)
        none_row = next(
            row
            for row in result["confusion"]["rows"]
            if row["gt_label"] == "无需协助"
        )
        self.assertEqual(none_row["cells"][-1]["count"], 1)
        self.assertEqual(
            [item["key"] for item in result["evidence_clusters"]],
            ["passable_space", "routing_direction"],
        )

        routing = build_review_reason_analysis(
            rows,
            theme="routing_intent",
            has_model_run=True,
        )
        self.assertEqual(routing["total"], 1)
        self.assertEqual(routing["items"][0]["issue_id"], "cn10001")

        without_run = build_review_reason_analysis(rows)
        self.assertEqual(without_run["summary"]["missing_predictions"], 0)
        self.assertEqual(
            without_run["confusion"]["model_labels"],
            ["误触发", "正确触发", "无需协助"],
        )
        self.assertTrue(
            all(not item["comparison_status"] for item in without_run["items"])
        )

        tagged_rows = [
            {
                "issue_id": "cn10001",
                "gt_label": "误触发",
                "annotation": {
                    "label": "误触发",
                    "review_status": "reviewed",
                    "tags": ["gate", "intent_straight", "traffic_light", "egress_swag"],
                    "missing_evidence": ["routing_direction"],
                    "note": "双环聚类样例",
                },
                "prediction": {"label": "误触发"},
            },
            {
                "issue_id": "cn10002",
                "gt_label": "正确触发",
                "annotation": {
                    "label": "正确触发",
                    "review_status": "reviewed",
                    "tags": ["obstacle_not_avoided", "lead_vehicle_departed"],
                    "missing_evidence": [],
                    "note": "应触发与无需协助",
                },
                "prediction": {"label": "正确触发"},
            },
        ]
        tag_catalog = {
            "gate": {
                "label": "道闸",
                "section": "scene",
                "group": "environment",
            },
            "intent_straight": {
                "label": "直行",
                "section": "scene",
                "group": "self_intent",
            },
            "traffic_light": {
                "label": "等灯",
                "section": "interaction_decision",
                "group": "false_trigger",
            },
            "obstacle_not_avoided": {
                "label": "未避障",
                "section": "interaction_decision",
                "group": "true_trigger",
            },
            "egress_swag": {
                "label": "SWAG",
                "section": "egress",
                "group": "ra",
            },
            "lead_vehicle_departed": {
                "label": "前车驶离",
                "section": "egress",
                "group": "no_assist",
            },
        }
        clustered = build_review_reason_analysis(
            tagged_rows,
            evidence_catalog={"routing_direction": {"label": "routing 方向"}},
            tag_catalog=tag_catalog,
            include_reason_themes=False,
        )
        panels = {panel["key"]: panel for panel in clustered["cluster_panels"]}
        self.assertEqual(
            [panel["key"] for panel in clustered["cluster_panels"]],
            ["evidence", "scene", "trigger", "egress"],
        )
        self.assertEqual(panels["evidence"]["layout"], "single")
        self.assertEqual(panels["scene"]["layout"], "dual")
        self.assertEqual(
            [group["key"] for group in panels["scene"]["groups"]],
            ["environment", "self_intent"],
        )
        self.assertEqual(panels["scene"]["groups"][0]["annotated_count"], 1)
        self.assertEqual(
            [item["key"] for item in panels["scene"]["groups"][0]["items"]],
            ["gate"],
        )
        self.assertEqual(
            [group["key"] for group in panels["trigger"]["groups"]],
            ["false_trigger", "true_trigger"],
        )
        self.assertEqual(
            [group["key"] for group in panels["egress"]["groups"]],
            ["ra", "no_assist"],
        )
        self.assertEqual(panels["evidence"]["groups"][0]["annotated_count"], 1)

        structured_only = build_review_reason_analysis(
            rows,
            has_model_run=True,
            include_reason_themes=False,
        )
        self.assertEqual(structured_only["method"]["id"], "structured-review-fields-v1")
        self.assertEqual(structured_only["method"]["catalog"], [])
        self.assertEqual(structured_only["reason_clusters"], [])
        self.assertEqual(structured_only["summary"]["unclustered_reason"], 0)
        self.assertTrue(all(item["reason_themes"] == [] for item in structured_only["items"]))

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
                    {
                        "issue_id": "cn20003",
                        "gt_label": "无需协助",
                        "title": "未预测",
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
            database.create_annotation(
                issue_id="cn20003",
                label="无需协助",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="该 Run 没有输出",
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

            tagged = database.review_reason_rows(
                baseline_scope=scope,
                tag="temporary_stop",
            )
            self.assertEqual([item["issue_id"] for item in tagged], ["cn20001"])

            structured_filters = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run["id"],
                model_label="正确触发",
                tag_filters=("temporary_stop",),
            )
            self.assertEqual([item["issue_id"] for item in structured_filters], ["cn20001"])

            human_search = database.review_reason_rows(
                baseline_scope=scope,
                search="bob",
            )
            self.assertEqual(
                [item["issue_id"] for item in human_search],
                ["cn20001"],
            )
            model_only_search = database.review_reason_rows(
                baseline_scope=scope,
                search="排队",
            )
            self.assertEqual(model_only_search, [])
            translated_tag_search = database.review_reason_rows(
                baseline_scope=scope,
                search="前车双闪",
                search_aliases=("temporary_stop",),
            )
            self.assertEqual(
                [item["issue_id"] for item in translated_tag_search],
                ["cn20001"],
            )

            matches = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="match",
            )
            self.assertEqual(
                [item["issue_id"] for item in matches],
                ["cn20002"],
            )

            missing_predictions = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="none",
            )
            self.assertEqual(
                [item["issue_id"] for item in missing_predictions],
                ["cn20003"],
            )

            cases = database.list_cases(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="match",
            )
            self.assertEqual([item["issue_id"] for item in cases["items"]], ["cn20002"])
            cases = database.list_cases(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="none",
            )
            self.assertEqual([item["issue_id"] for item in cases["items"]], ["cn20003"])
            cases = database.list_cases(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="mismatch",
            )
            self.assertEqual([item["issue_id"] for item in cases["items"]], ["cn20001"])
            model_label_cases = database.list_cases(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="mismatch",
                model_label="正确触发",
            )
            self.assertEqual(
                [item["issue_id"] for item in model_label_cases["items"]],
                ["cn20001"],
            )
            human_label_cases = database.list_cases(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="mismatch",
                annotation_label="误触发",
            )
            self.assertEqual(
                [item["issue_id"] for item in human_label_cases["items"]],
                ["cn20001"],
            )

            # The gallery is ordered only by issue_id, so a repeated request
            # with identical filters must preserve the same order.
            first_order = [
                item["issue_id"]
                for item in database.list_cases(
                    baseline_scope=scope,
                    model_run_id=run["id"],
                    comparison_status="all",
                    page_size=50,
                )["items"]
            ]
            second_order = [
                item["issue_id"]
                for item in database.list_cases(
                    baseline_scope=scope,
                    model_run_id=run["id"],
                    comparison_status="all",
                    page_size=50,
                )["items"]
            ]
            self.assertEqual(first_order, second_order)

            with self.assertRaisesRegex(ValueError, "requires model_run_id"):
                database.review_reason_rows(
                    baseline_scope=scope,
                    comparison_status="match",
                )
            with self.assertRaisesRegex(ValueError, "requires model_run_id"):
                database.list_cases(
                    baseline_scope=scope,
                    comparison_status="match",
                )

            old_note_search = database.review_reason_rows(
                baseline_scope=scope,
                search="旧版本",
            )
            self.assertEqual(old_note_search, [])


if __name__ == "__main__":
    unittest.main()
