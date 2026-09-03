from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.support.catalogs import resolve_review_exclusion_filter
from ra_triage_dashboard.app.review_analysis import (
    build_review_reason_analysis,
    classify_review_reason,
)
from ra_triage_dashboard.app.routers.cases import (
    _case_result_with_status_filter,
    _with_effective_case_review_status,
)


class ReviewReasonAnalysisTest(unittest.TestCase):
    def test_stage1_true_stuck_matches_both_true_stuck_gt_outcomes(self) -> None:
        rows = [
            {
                "issue_id": f"cn-stage1-{index}",
                "gt_label": gt_label,
                "annotation": {"label": gt_label},
                "prediction": {"label": "真实卡住"},
            }
            for index, gt_label in enumerate(
                ("正确触发", "无需协助", "误触发"), start=1
            )
        ]
        result = build_review_reason_analysis(
            rows, has_model_run=True, include_reason_themes=False
        )
        self.assertEqual(
            [item["comparison_status"] for item in result["items"]],
            ["match", "match", "mismatch"],
        )
        self.assertEqual(result["summary"]["model_matches"], 2)
        self.assertEqual(result["summary"]["model_mismatches"], 1)
        self.assertEqual(result["summary"]["missing_predictions"], 0)
        self.assertIn("真实卡住", result["confusion"]["model_labels"])

    def test_database_stage1_comparison_filters_and_run_failure_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            scope = "stage1-compat"
            database.upsert_issues(
                [
                    {"issue_id": "cn-stage1-fp", "gt_label": "误触发"},
                    {"issue_id": "cn-stage1-ra", "gt_label": "正确触发"},
                    {"issue_id": "cn-stage1-na", "gt_label": "无需协助"},
                    {"issue_id": "cn-stage1-wrong", "gt_label": "误触发"},
                ],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = database.import_model_run(
                name="stage1",
                source_name="stage1.xlsx",
                source_sha256="1" * 64,
                metadata={},
                rows=[
                    {"issue_id": "cn-stage1-fp", "model_label": "误触发"},
                    {"issue_id": "cn-stage1-ra", "model_label": "真实卡住"},
                    {"issue_id": "cn-stage1-na", "model_label": "真实卡住"},
                    {"issue_id": "cn-stage1-wrong", "model_label": "真实卡住"},
                ],
            )
            matches = database.list_cases(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="match",
                page_size=20,
            )
            mismatches = database.list_cases(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="mismatch",
                page_size=20,
            )
            self.assertEqual(matches["total"], 3)
            self.assertEqual(mismatches["total"], 1)
            self.assertEqual(mismatches["items"][0]["issue_id"], "cn-stage1-wrong")
            self.assertTrue(mismatches["items"][0]["prediction"]["mismatch"])
            listed = database.list_model_runs(baseline_scope=scope)
            self.assertEqual(listed[0]["failure_count"], 1)
            for issue_id, label in (
                ("cn-stage1-fp", "误触发"),
                ("cn-stage1-ra", "正确触发"),
                ("cn-stage1-na", "无需协助"),
                ("cn-stage1-wrong", "误触发"),
            ):
                database.create_annotation(
                    issue_id=issue_id,
                    model_run_id=run["id"],
                    label=label,
                    review_status="reviewed",
                    tags=[],
                    missing_evidence=[],
                    note="stage1 compatibility",
                    author="tester",
                )
            analysis_matches = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="match",
            )
            analysis_mismatches = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run["id"],
                comparison_status="mismatch",
            )
            self.assertEqual(len(analysis_matches), 3)
            self.assertEqual(len(analysis_mismatches), 1)
            self.assertEqual(analysis_mismatches[0]["issue_id"], "cn-stage1-wrong")

    def test_model_run_with_scope_counts_matches_list_model_runs_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            scope = "single-run-scope"
            database.upsert_issues(
                [
                    {"issue_id": "cn-one-fp", "gt_label": "误触发"},
                    {"issue_id": "cn-one-ra", "gt_label": "正确触发"},
                    {"issue_id": "cn-one-wrong", "gt_label": "误触发"},
                ],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = database.import_model_run(
                name="single",
                source_name="single.xlsx",
                source_sha256="2" * 64,
                metadata={},
                rows=[
                    {"issue_id": "cn-one-fp", "model_label": "误触发"},
                    {"issue_id": "cn-one-ra", "model_label": "真实卡住"},
                    {"issue_id": "cn-one-wrong", "model_label": "真实卡住"},
                ],
            )
            listed = database.list_model_runs(baseline_scope=scope)
            listed_row = next(r for r in listed if r["id"] == run["id"])
            single = database.model_run_with_scope_counts(
                run["id"], baseline_scopes=[scope]
            )
            self.assertIsNotNone(single)
            # The single-run lookup must expose the identical scope-derived
            # counts that http_support reads off the full-list scan it replaces.
            for key in (
                "id",
                "name",
                "kind",
                "prediction_count",
                "baseline_prediction_count",
                "failure_count",
            ):
                self.assertEqual(single[key], listed_row[key], key)
            self.assertEqual(single["failure_count"], 1)
            # A missing run resolves to None so callers keep their 404 branch.
            self.assertIsNone(
                database.model_run_with_scope_counts(
                    "no-such-run", baseline_scopes=[scope]
                )
            )

    def test_exclusion_filter_normalizes_explicit_slices(self) -> None:
        self.assertEqual(resolve_review_exclusion_filter(""), ("all", None))
        self.assertEqual(resolve_review_exclusion_filter("included"), ("included", False))
        self.assertEqual(resolve_review_exclusion_filter("false"), ("included", False))
        self.assertEqual(resolve_review_exclusion_filter("excluded"), ("excluded", True))
        self.assertEqual(resolve_review_exclusion_filter("TRUE"), ("excluded", True))
        with self.assertRaises(HTTPException) as context:
            resolve_review_exclusion_filter("unexpected")
        self.assertEqual(context.exception.status_code, 400)

    def test_exclusion_slice_is_applied_by_the_analysis_aggregator(self) -> None:
        rows = [
            {
                "issue_id": "cn-excluded",
                "gt_label": "误触发",
                "annotation": {
                    "is_excluded": True,
                    "label": "误触发",
                    "note": "不是模型问题",
                    "missing_evidence": ["not_model_issue"],
                },
            },
            {
                "issue_id": "cn-included",
                "gt_label": "误触发",
                "annotation": {
                    "is_excluded": False,
                    "label": "误触发",
                    "note": "真正需要分析",
                    "missing_evidence": ["routing_direction"],
                },
            },
        ]
        result = build_review_reason_analysis(rows, include_reason_themes=False)
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            [item["issue_id"] for item in result["items"]],
            ["cn-excluded", "cn-included"],
        )
        self.assertEqual(result["summary"]["with_structured_evidence"], 2)

        included = build_review_reason_analysis(
            rows,
            include_reason_themes=False,
            is_excluded=False,
        )
        self.assertEqual(included["total"], 1)
        self.assertEqual([item["issue_id"] for item in included["items"]], ["cn-included"])

        excluded = build_review_reason_analysis(
            rows,
            include_reason_themes=False,
            is_excluded=True,
        )
        self.assertEqual(excluded["total"], 1)
        self.assertEqual([item["issue_id"] for item in excluded["items"]], ["cn-excluded"])

    def test_case_gallery_exclusion_filter_keeps_unreviewed_cases_included(self) -> None:
        """The gallery's normal slice is not Review-only."""

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            scope = "test-case-exclusion"
            database.upsert_issues(
                [
                    {"issue_id": "cn-excluded", "gt_label": "误触发"},
                    {"issue_id": "cn-included", "gt_label": "误触发"},
                    {"issue_id": "cn-unreviewed", "gt_label": "误触发"},
                ],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            database.create_annotation(
                issue_id="cn-excluded",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="not a model issue",
                author="tester",
                is_excluded=True,
            )
            database.create_annotation(
                issue_id="cn-included",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="keep in queue",
                author="tester",
                is_excluded=False,
            )

            included = database.list_cases(
                baseline_scope=scope, is_excluded=False, page_size=20
            )
            self.assertEqual(
                [item["issue_id"] for item in included["items"]],
                ["cn-included", "cn-unreviewed"],
            )
            excluded = database.list_cases(
                baseline_scope=scope, is_excluded=True, page_size=20
            )
            self.assertEqual(
                [item["issue_id"] for item in excluded["items"]],
                ["cn-excluded"],
            )
            self.assertEqual(
                database.list_case_issue_ids(
                    baseline_scope=scope, is_excluded=False
                ),
                ["cn-included", "cn-unreviewed"],
            )

    def test_historical_tags_drive_effective_output_and_automatic_status(self) -> None:
        tag_catalog = {
            "queue": {"label": "排队", "group": "false_trigger"},
            "waypoint": {"label": "RA", "group": "ra"},
            "obstacle": {"label": "未避障", "group": "true_trigger"},
        }
        rows = [
            {
                "issue_id": "cn1",
                "gt_label": "误触发",
                "annotation": {
                    "label": "",
                    "review_status": "pending",
                    "tags": ["queue"],
                },
            },
            {
                "issue_id": "cn2",
                "gt_label": "误触发",
                "annotation": {
                    "label": "",
                    "review_status": "reviewed",
                    "tags": ["waypoint"],
                },
            },
            {
                "issue_id": "cn3",
                "gt_label": "正确触发",
                "annotation": {
                    "label": "",
                    "review_status": "reviewed",
                    "tags": ["obstacle"],
                },
            },
            {
                "issue_id": "cn4",
                "gt_label": "正确触发",
                "annotation": {
                    "label": "",
                    "review_status": "needs_gt_review",
                    "tags": ["queue", "waypoint"],
                },
            },
        ]
        result = build_review_reason_analysis(
            rows,
            tag_catalog=tag_catalog,
            include_reason_themes=False,
        )
        annotations = {
            item["issue_id"]: item["annotation"] for item in result["items"]
        }
        self.assertEqual(annotations["cn1"]["expected_output"], "误触发")
        self.assertEqual(annotations["cn1"]["review_status"], "reviewed")
        self.assertEqual(annotations["cn1"]["expected_output_source"], "tags")
        self.assertEqual(annotations["cn2"]["expected_output"], "正确触发")
        self.assertEqual(
            annotations["cn2"]["review_status"], "needs_gt_review"
        )
        self.assertEqual(annotations["cn3"]["review_status"], "pending")
        self.assertEqual(annotations["cn3"]["expected_output_source"], "missing")
        self.assertEqual(annotations["cn4"]["review_status"], "pending")
        self.assertEqual(annotations["cn4"]["expected_output_source"], "conflict")
        self.assertEqual(
            result["summary"]["review_status_counts"],
            {"pending": 2, "reviewed": 1, "needs_gt_review": 1},
        )

        needs_gt = build_review_reason_analysis(
            rows,
            tag_catalog=tag_catalog,
            include_reason_themes=False,
            review_statuses=("needs_gt_review",),
        )
        self.assertEqual([item["issue_id"] for item in needs_gt["items"]], ["cn2"])

        false_trigger = build_review_reason_analysis(
            rows,
            tag_catalog=tag_catalog,
            include_reason_themes=False,
            annotation_labels=("误触发",),
        )
        self.assertEqual(
            [item["issue_id"] for item in false_trigger["items"]],
            ["cn1"],
        )

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
            ["误触发", "正确触发", "无需协助", "真实卡住", "NONE"],
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
                model_run_id=run["id"],
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=["routing_direction"],
                note="旧版本：routing 缺失",
                author="alice",
            )
            database.create_annotation(
                issue_id="cn20001",
                model_run_id=run["id"],
                label="误触发",
                review_status="reviewed",
                tags=["temporary_stop"],
                missing_evidence=["hazard_signal"],
                note="最新版本：双闪遗漏",
                author="bob",
            )
            database.create_annotation(
                issue_id="cn20002",
                model_run_id=run["id"],
                label="正确触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="判断正确",
                author="alice",
            )
            database.create_annotation(
                issue_id="cn20003",
                model_run_id=run["id"],
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
            review_rows = database.review_reason_rows(baseline_scope=scope)
            self.assertEqual(
                [item["issue_id"] for item in review_rows],
                ["cn20001", "cn20002", "cn20003"],
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

    def test_selected_run_prefers_own_review_and_exposes_legacy_history_to_progress_views(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            scope = "test-run-binding"
            database.upsert_issues(
                [
                    {
                        "issue_id": "cn30001",
                        "gt_label": "误触发",
                        "title": "同 issue 多 Run",
                    },
                    {
                        "issue_id": "cn30002",
                        "gt_label": "误触发",
                        "title": "只有历史 Review",
                    },
                ],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run_a, _ = database.import_model_run(
                name="run-a",
                source_name="a.json",
                source_sha256="a" * 64,
                metadata={},
                rows=[
                    {"issue_id": "cn30001", "model_label": "正确触发"},
                    {"issue_id": "cn30002", "model_label": "正确触发"},
                ],
            )
            run_b, _ = database.import_model_run(
                name="run-b",
                source_name="b.json",
                source_sha256="b" * 64,
                metadata={},
                rows=[{"issue_id": "cn30001", "model_label": "无需协助"}],
            )
            database.create_annotation(
                issue_id="cn30001",
                model_run_id=run_a["id"],
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=["run_a_missing"],
                note="Run A review",
                author="alice",
            )
            database.create_annotation(
                issue_id="cn30001",
                model_run_id=run_b["id"],
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=["run_b_missing"],
                note="Run B review",
                author="bob",
            )
            database.create_annotation(
                issue_id="cn30001",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=["legacy_missing"],
                note="Legacy review",
                author="legacy",
            )
            database.create_annotation(
                issue_id="cn30002",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=["legacy_only_missing"],
                note="Pre-Run shared Review",
                author="legacy",
            )

            # The strict default is used by safety-sensitive consumers such
            # as Trail candidate generation. A Run-bound Review always wins
            # over an unbound historical Review for the same Issue.
            rows_a = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run_a["id"],
            )
            self.assertEqual([row["annotation"]["author"] for row in rows_a], ["alice"])
            self.assertEqual(rows_a[0]["annotation"]["model_run_id"], run_a["id"])
            rows_b = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run_b["id"],
            )
            self.assertEqual([row["annotation"]["author"] for row in rows_b], ["bob"])
            self.assertEqual(rows_b[0]["annotation"]["model_run_id"], run_b["id"])

            # Review-progress surfaces can use the compatibility projection:
            # legacy history is visible only for Issues with no selected-Run
            # Review, so it does not appear as a synthetic pending Review.
            projected_rows_a = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run_a["id"],
                include_unbound_fallback=True,
            )
            self.assertEqual(
                [row["annotation"]["author"] for row in projected_rows_a],
                ["alice", "legacy"],
            )
            self.assertEqual(
                projected_rows_a[1]["annotation"]["model_run_id"], ""
            )
            progress_cases = database.list_cases(
                baseline_scope=scope,
                model_run_id=run_a["id"],
                comparison_status="all",
                page_size=50,
            )
            self.assertEqual(
                [item["annotation"]["author"] for item in progress_cases["items"]],
                ["alice", "legacy"],
            )
            self.assertEqual(
                progress_cases["items"][1]["annotation"]["review_status"],
                "reviewed",
            )
            self.assertEqual(
                _with_effective_case_review_status(
                    progress_cases["items"][1], ()
                )["annotation"]["review_status"],
                "reviewed",
            )
            # This is the same post-read status projection used by
            # `/api/cases?review_status=...`; a historical Review must not be
            # returned in the synthetic pending slice merely because it is
            # unbound to the selected Run.
            with patch(
                "ra_triage_dashboard.app.routers.cases.database.list_cases",
                return_value=progress_cases,
            ), patch(
                "ra_triage_dashboard.app.routers.cases._review_tag_catalog",
                return_value=(),
            ):
                pending_cases = _case_result_with_status_filter(
                    filters={},
                    review_statuses=("pending",),
                    page=1,
                    page_size=50,
                )
            self.assertEqual(pending_cases["total"], 0)
            self.assertEqual(
                database.list_case_issue_ids(
                    baseline_scope=scope,
                    model_run_id=run_a["id"],
                    comparison_status="all",
                ),
                ["cn30001", "cn30002"],
            )

            reviewers_a = database.list_reviewers(
                baseline_scope=scope,
                model_run_id=run_a["id"],
            )
            self.assertEqual(
                [item["name"] for item in reviewers_a], ["alice", "legacy"]
            )
            clusters_a = database.review_clusters(
                baseline_scope=scope,
                model_run_id=run_a["id"],
                failure_only=False,
            )
            self.assertEqual(
                {item["key"] for item in clusters_a},
                {"legacy_only_missing", "run_a_missing"},
            )
            self.assertEqual(
                database.overview(baseline_scope=scope, model_run_id=run_a["id"])["labelled"],
                2,
            )

            all_rows = database.review_reason_rows(baseline_scope=scope)
            self.assertEqual(
                [row["annotation"]["author"] for row in all_rows],
                ["legacy", "legacy"],
            )

    def test_progress_view_reuses_previous_bound_run_review_without_relaxing_strict_rows(
        self,
    ) -> None:
        """A prior Model Run is evidence for progress, not Trail write input."""
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            scope = "test-bound-history-progress"
            database.upsert_issues(
                [{"issue_id": "cn30003", "gt_label": "误触发"}],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run_a, _ = database.import_model_run(
                name="current-run",
                source_name="current.json",
                source_sha256="c" * 64,
                metadata={},
                rows=[{"issue_id": "cn30003", "model_label": "正确触发"}],
            )
            run_b, _ = database.import_model_run(
                name="previous-run",
                source_name="previous.json",
                source_sha256="d" * 64,
                metadata={},
                rows=[{"issue_id": "cn30003", "model_label": "无需协助"}],
            )
            database.create_annotation(
                issue_id="cn30003",
                model_run_id=run_b["id"],
                label="误触发",
                review_status="reviewed",
                tags=["traffic_light"],
                missing_evidence=["previous_run_missing"],
                note="Previous Run review",
                author="caoliwen_i",
            )

            # Strict consumers remain isolated to the selected Run. This is
            # the contract used by Trail candidate generation and writers.
            self.assertEqual(
                database.review_reason_rows(
                    baseline_scope=scope,
                    model_run_id=run_a["id"],
                ),
                [],
            )
            self.assertEqual(
                database.review_reason_rows(
                    baseline_scope=scope,
                    model_run_id=run_a["id"],
                    include_unbound_fallback=True,
                ),
                [],
            )

            # Gallery / reviewer progress opts into the read-only previous
            # Run fallback so the same completed human Review is not shown as
            # a synthetic pending case on a later model Run.
            projected = database.review_reason_rows(
                baseline_scope=scope,
                model_run_id=run_a["id"],
                include_unbound_fallback=True,
                include_bound_history_fallback=True,
            )
            self.assertEqual(len(projected), 1)
            self.assertEqual(projected[0]["annotation"]["author"], "caoliwen_i")
            self.assertEqual(projected[0]["annotation"]["model_run_id"], run_b["id"])

            progress_cases = database.list_cases(
                baseline_scope=scope,
                model_run_id=run_a["id"],
                comparison_status="all",
                page_size=50,
            )
            self.assertEqual(progress_cases["total"], 1)
            self.assertEqual(
                progress_cases["items"][0]["annotation"]["review_status"],
                "reviewed",
            )
            self.assertEqual(
                progress_cases["items"][0]["annotation"]["model_run_id"], run_b["id"]
            )
            self.assertEqual(
                database.overview(
                    baseline_scope=scope, model_run_id=run_a["id"]
                )["labelled"],
                1,
            )
            self.assertEqual(
                database.list_reviewers(
                    baseline_scope=scope, model_run_id=run_a["id"]
                ),
                [
                    {
                        "name": "caoliwen_i",
                        "verified": False,
                        "verified_count": 0,
                        "unverified_count": 1,
                        "review_count": 1,
                    }
                ],
            )

    def test_unselected_run_keeps_prediction_namespace_for_exclusion_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            scope = "trail-all-runs"
            database.upsert_issues(
                [{"issue_id": "cn40001", "gt_label": "误触发"}],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = database.import_model_run(
                name="aggregate run",
                source_name="aggregate.json",
                source_sha256="4" * 64,
                metadata={},
                rows=[
                    {
                        "issue_id": "cn40001",
                        "model_label": "正确触发",
                        "model_reason": "排队",
                        "model_confidence": 0.91,
                    }
                ],
            )
            database.create_annotation(
                issue_id="cn40001",
                model_run_id=run["id"],
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=["not_model_issue"],
                note="应该排除",
                author="alice",
                is_excluded=True,
            )

            rows = database.review_reason_rows(
                baseline_scope=scope,
                is_excluded=True,
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["annotation"]["model_run_id"], run["id"])
            self.assertEqual(rows[0]["prediction"]["model_run_id"], run["id"])
            self.assertEqual(rows[0]["prediction"]["label"], "正确触发")
            self.assertEqual(rows[0]["prediction"]["reason"], "排队")
            self.assertEqual(
                database.review_reason_rows(
                    baseline_scope=scope,
                    is_excluded=False,
                ),
                [],
            )
            self.assertEqual(
                database.review_clusters(
                    baseline_scope=scope,
                    is_excluded=False,
                ),
                [],
            )
            self.assertEqual(
                database.review_clusters(
                    baseline_scope=scope,
                    is_excluded=True,
                ),
                [{"key": "not_model_issue", "count": 1}],
            )


if __name__ == "__main__":
    unittest.main()
