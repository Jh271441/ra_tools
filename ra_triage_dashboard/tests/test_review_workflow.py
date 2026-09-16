from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl
from fastapi import HTTPException
from starlette.requests import Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.support.annotations import _create_annotation_record
from ra_triage_dashboard.app.review_workflow import (
    derive_review_status,
    effective_expected_output,
    infer_expected_output_from_tags,
    resolve_expected_output,
)
from ra_triage_dashboard.app.routers.analysis import (
    _review_analysis_export_response,
    _trail_expected_output_rows,
)
from ra_triage_dashboard.app.routers import analysis as analysis_router
from ra_triage_dashboard.app.routers.cases import (
    _case_result_with_status_filter,
    _with_effective_case_review_status,
)


TAG_CATALOG = [
    {"key": "queue", "group": "false_trigger"},
    {"key": "obstacle", "group": "true_trigger"},
    {"key": "waypoint", "group": "ra"},
    {"key": "lead_departed", "group": "no_assist"},
    {"key": "road", "group": "environment"},
]


def make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/cases/cn1/annotations",
            "headers": [],
        }
    )


class ReviewWorkflowTest(unittest.TestCase):
    def test_review_analysis_export_keeps_exclusion_and_detailed_tags(self) -> None:
        result = {
            "items": [
                {
                    "issue_id": "cn-excluded",
                    "title": "示例 Issue",
                    "gt_label": "正确触发",
                    "comparison_status": "mismatch",
                    "prediction": {
                        "label": "误触发",
                        "reason": "test reason",
                        "confidence": 0.8,
                    },
                    "annotation": {
                        "model_run_id": "run-1",
                        "work_split_id": "split-1",
                        "expected_output": "误触发",
                        "review_status": "needs_gt_review",
                        "is_excluded": True,
                        "note": "应排除并保留标签细节",
                        "tags": ["road", "queue", "waypoint", "legacy_tag"],
                        "missing_evidence": ["routing_direction", "custom:missing"],
                        "author": "tester",
                        "created_at": "2026-09-14T00:00:00+00:00",
                    },
                    "review_url": "/review?issue=cn-excluded",
                    "voyager_issue_url": "https://voyager.example/issue/cn-excluded",
                }
            ]
        }
        tag_catalog = [
            {
                "key": "road",
                "label": "一般直行道路",
                "section": "scene",
                "group": "environment",
            },
            {
                "key": "queue",
                "label": "排队",
                "section": "interaction_decision",
                "group": "false_trigger",
            },
            {
                "key": "waypoint",
                "label": "Waypoint",
                "section": "egress",
                "group": "ra",
            },
        ]
        evidence_catalog = [
            {"key": "routing_direction", "label": "Routing 方向"},
        ]
        with patch.object(analysis_router, "_review_tag_catalog", return_value=tag_catalog), patch.object(
            analysis_router, "_missing_evidence_catalog", return_value=evidence_catalog
        ):
            exported = analysis_router._review_analysis_export_rows(result)
            response = analysis_router._review_analysis_export_response(result, "csv")

        row = exported[0]
        self.assertEqual(row["is_excluded"], "是")
        self.assertEqual(row["tags"], "一般直行道路、排队、Waypoint、legacy_tag")
        self.assertEqual(row["scene_tags"], "一般直行道路")
        self.assertEqual(row["trigger_tags"], "排队")
        self.assertEqual(row["egress_tags"], "Waypoint")
        self.assertEqual(row["other_tags"], "legacy_tag")
        self.assertEqual(
            row["tag_details"],
            "场景/环境=一般直行道路；触发判定/误触发=排队；脱困方式/正确触发=Waypoint；其他=legacy_tag",
        )
        self.assertEqual(row["tag_keys"], "road、queue、waypoint、legacy_tag")
        self.assertEqual(row["missing_evidence"], "Routing 方向、custom:missing")
        self.assertEqual(row["missing_evidence_keys"], "routing_direction、custom:missing")
        self.assertEqual(row["review_model_run_id"], "run-1")
        self.assertEqual(row["review_work_split_id"], "split-1")
        csv_text = response.body.decode("utf-8-sig")
        self.assertIn("应该排除", csv_text.splitlines()[0])
        self.assertIn("一般直行道路", csv_text)
        self.assertIn(",是,", csv_text)

    def test_gt_update_export_never_includes_partial_blind_reviews(self) -> None:
        captured: dict[str, object] = {}

        def fake_payload(**kwargs):
            captured.update(kwargs)
            return {"items": []}

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/review-reason-analysis/export",
                "headers": [],
            }
        )
        with patch.object(
            analysis_router,
            "resolve_request_baseline_scopes",
            return_value=["scope"],
        ), patch.object(
            analysis_router,
            "resolve_request_baseline_ids",
            return_value=["test"],
        ), patch.object(
            analysis_router,
            "_review_reason_analysis_payload",
            side_effect=fake_payload,
        ):
            response = asyncio.run(
                analysis_router.export_review_reason_analysis(
                    request,
                    format="trail_xlsx",
                    issue_ids="cn1,cn2",
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(captured["include_multi_reviews"])
        self.assertEqual(captured["issue_ids"], "cn1,cn2")

    def test_gallery_export_resolves_exact_filtered_issue_membership(self) -> None:
        captured: dict[str, object] = {}
        captured_case_filters: dict[str, object] = {}

        def fake_payload(**kwargs):
            captured.update(kwargs)
            return {"items": []}

        def fake_issue_ids(*, filters, review_statuses):
            captured_case_filters.update(filters)
            self.assertEqual(review_statuses, ("needs_gt_review",))
            return ["cn1", "cn2"]

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/review-reason-analysis/export",
                "headers": [],
            }
        )
        parsed_filters = {
            "review_statuses": ("needs_gt_review",),
            "exclusion": "included",
            "comparison_status": "mismatch",
            "issue_ids": [],
            "work_assignee": "alice",
        }
        with patch.object(
            analysis_router, "resolve_request_baseline_scopes", return_value=["scope"]
        ), patch.object(
            analysis_router, "resolve_request_baseline_ids", return_value=["0821"]
        ), patch.object(
            analysis_router, "_case_filter_kwargs", return_value=parsed_filters
        ), patch.object(
            analysis_router,
            "_case_issue_ids_with_status_filter",
            side_effect=fake_issue_ids,
        ), patch.object(
            analysis_router,
            "request_identity",
            return_value=SimpleNamespace(verified=True, username="jasperchen"),
        ), patch.object(
            analysis_router,
            "_review_reason_analysis_payload",
            side_effect=fake_payload,
        ), patch.object(
            analysis_router,
            "_review_analysis_export_response",
            return_value=SimpleNamespace(status_code=200),
        ):
            response = asyncio.run(
                analysis_router.export_review_reason_analysis(
                    request,
                    format="xlsx",
                    gallery_scope=True,
                    work_assignee="alice",
                    review_status="needs_gt_review",
                    comparison="mismatch",
                    model_run_id="run-1",
                    search="gallery keyword",
                    comment_state="with",
                    exclusion="included",
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["issue_ids"], ["cn1", "cn2"])
        self.assertEqual(captured["search"], "")
        self.assertEqual(captured["comment_state"], "all")
        self.assertTrue(captured["unbounded"])
        self.assertEqual(captured_case_filters["preferred_annotation_author"], "jasperchen")

    def test_review_analysis_exposes_blind_projection_to_every_viewer(self) -> None:
        captured: dict[str, object] = {}

        def fake_payload(**kwargs):
            captured.update(kwargs)
            return {"items": []}

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/review-reason-analysis",
                "headers": [],
            }
        )
        with patch.object(
            analysis_router,
            "resolve_request_baseline_scopes",
            return_value=["scope"],
        ), patch.object(
            analysis_router,
            "resolve_request_baseline_ids",
            return_value=["test"],
        ), patch.object(
            analysis_router,
            "_review_reason_analysis_payload",
            side_effect=fake_payload,
        ):
            result = asyncio.run(
                analysis_router.review_reason_analysis(
                    request,
                    model_run_id="run-1",
                    work_agreement="conflict",
                    search="冲突",
                )
            )

        self.assertEqual(result["baselines"], ["test"])
        self.assertTrue(captured["include_multi_reviews"])
        self.assertEqual(captured["work_agreement"], "conflict")
        self.assertEqual(captured["search"], "冲突")

    def test_tags_infer_the_three_canonical_outputs(self) -> None:
        self.assertEqual(
            infer_expected_output_from_tags(["queue", "road"], TAG_CATALOG),
            "误触发",
        )
        self.assertEqual(
            infer_expected_output_from_tags(["obstacle", "waypoint"], TAG_CATALOG),
            "正确触发",
        )
        self.assertEqual(
            infer_expected_output_from_tags(
                ["obstacle", "lead_departed"], TAG_CATALOG
            ),
            "无需协助",
        )

    def test_true_trigger_alone_needs_an_explicit_or_egress_output(self) -> None:
        self.assertEqual(
            infer_expected_output_from_tags(["obstacle"], TAG_CATALOG),
            "",
        )
        self.assertEqual(
            resolve_expected_output("正确触发", ["obstacle"], TAG_CATALOG),
            "正确触发",
        )

    def test_conflicting_or_disagreeing_tags_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "多个期望输出"):
            infer_expected_output_from_tags(["queue", "waypoint"], TAG_CATALOG)
        with self.assertRaisesRegex(ValueError, "不一致"):
            resolve_expected_output("无需协助", ["waypoint"], TAG_CATALOG)

    def test_review_status_is_derived_from_expected_output_and_gt(self) -> None:
        self.assertEqual(derive_review_status("", "误触发"), "pending")
        self.assertEqual(derive_review_status("误触发", "误触发"), "reviewed")
        self.assertEqual(
            derive_review_status("误触发", ""),
            "needs_gt_review",
        )
        self.assertEqual(
            derive_review_status("正确触发", "误触发"),
            "needs_gt_review",
        )

    def test_historical_review_output_is_inferred_fail_closed(self) -> None:
        self.assertEqual(
            effective_expected_output(
                {"expected_output": "", "label": "", "tags": ["queue"]},
                TAG_CATALOG,
            ),
            ("误触发", "tags"),
        )
        self.assertEqual(
            effective_expected_output(
                {"tags": ["queue", "waypoint"]},
                TAG_CATALOG,
            ),
            ("", "conflict"),
        )
        self.assertEqual(
            effective_expected_output(
                {"expected_output": "正确触发", "tags": ["queue"]},
                TAG_CATALOG,
            ),
            ("正确触发", "explicit"),
        )

    def test_gallery_status_uses_the_same_effective_output_as_analysis(self) -> None:
        tag_catalog = tuple(TAG_CATALOG)
        inferred = _with_effective_case_review_status(
            {
                "issue_id": "cn1",
                "gt_label": "误触发",
                "annotation": {
                    "label": "",
                    "review_status": "pending",
                    "tags": ["waypoint"],
                },
            },
            tag_catalog,
        )
        self.assertEqual(inferred["annotation"]["label"], "正确触发")
        self.assertEqual(
            inferred["annotation"]["review_status"],
            "needs_gt_review",
        )
        self.assertEqual(inferred["annotation"]["expected_output_source"], "tags")

        conflict = _with_effective_case_review_status(
            {
                "issue_id": "cn2",
                "gt_label": "误触发",
                "annotation": {
                    "label": "",
                    "review_status": "reviewed",
                    "tags": ["queue", "waypoint"],
                },
            },
            tag_catalog,
        )
        self.assertEqual(conflict["annotation"]["label"], "")
        self.assertEqual(conflict["annotation"]["review_status"], "pending")
        self.assertEqual(conflict["annotation"]["expected_output_source"], "conflict")

    def test_gallery_status_filter_runs_before_pagination(self) -> None:
        raw = {
            "items": [
                {
                    "issue_id": "cn1",
                    "gt_label": "误触发",
                    "annotation": {"tags": ["queue"]},
                },
                {
                    "issue_id": "cn2",
                    "gt_label": "误触发",
                    "annotation": {"tags": ["waypoint"]},
                },
                {
                    "issue_id": "cn3",
                    "gt_label": "无需协助",
                    "annotation": None,
                },
                {
                    "issue_id": "cn4",
                    "gt_label": "误触发",
                    "annotation": {"tags": ["queue", "waypoint"]},
                },
            ]
        }
        with patch(
            "ra_triage_dashboard.app.routers.cases.database.list_case_review_candidates",
            return_value=raw["items"],
        ), patch(
            "ra_triage_dashboard.app.routers.cases.database.list_cases",
            return_value={"items": [raw["items"][3]], "total": 1},
        ), patch(
            "ra_triage_dashboard.app.routers.cases._review_tag_catalog",
            return_value=tuple(TAG_CATALOG),
        ):
            result = _case_result_with_status_filter(
                filters={},
                review_statuses=("pending",),
                page=2,
                page_size=1,
            )

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["page_size"], 1)
        self.assertEqual([item["issue_id"] for item in result["items"]], ["cn4"])

    def test_server_persists_inferred_output_and_ignores_client_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn1", "gt_label": "误触发"}],
                source="test",
                replace_gt=True,
            )
            with patch(
                "ra_triage_dashboard.app.support.annotations.database",
                database,
            ), patch(
                "ra_triage_dashboard.app.support.catalogs.database",
                database,
            ):
                annotation = _create_annotation_record(
                    issue_id="cn1",
                    request=make_request(),
                    body={
                        "expected_output": "",
                        "review_status": "reviewed",
                        "tags": ["egress_waypoint"],
                        "author": "alice",
                    },
                )
        self.assertEqual(annotation["expected_output"], "正确触发")
        self.assertEqual(annotation["label"], "正确触发")
        self.assertEqual(annotation["review_status"], "needs_gt_review")

    def test_server_rejects_conflicting_output_tags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn1", "gt_label": "误触发"}],
                source="test",
                replace_gt=True,
            )
            with patch(
                "ra_triage_dashboard.app.support.annotations.database",
                database,
            ), patch(
                "ra_triage_dashboard.app.support.catalogs.database",
                database,
            ), self.assertRaises(HTTPException) as context:
                _create_annotation_record(
                    issue_id="cn1",
                    request=make_request(),
                    body={
                        "tags": ["queue", "egress_waypoint"],
                        "author": "alice",
                    },
                )
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("多个期望输出", str(context.exception.detail))

    def test_trail_export_contains_only_gt_changes_and_exact_headers(self) -> None:
        result = {
            "items": [
                {
                    "issue_id": "cn1",
                    "gt_label": "误触发",
                    "annotation": {
                        "expected_output": "正确触发",
                        "review_status": "needs_gt_review",
                    },
                },
                {
                    "issue_id": "cn2",
                    "gt_label": "无需协助",
                    "annotation": {
                        "label": "无需协助",
                        "review_status": "reviewed",
                    },
                },
                {
                    "issue_id": "cn3",
                    "gt_label": "正确触发",
                    "annotation": {
                        "expected_output": "",
                        "review_status": "pending",
                    },
                },
                {
                    "issue_id": "cn4",
                    "gt_label": "无需协助",
                    "annotation": {
                        # Legacy rows can carry a stale manually selected
                        # status. Export derives eligibility from the same
                        # expected-output/GT rule and must not omit the change.
                        "expected_output": "误触发",
                        "review_status": "reviewed",
                    },
                },
            ]
        }
        self.assertEqual(
            _trail_expected_output_rows(result),
            [
                {"issue_id": "cn1", "期望输出": "正确触发"},
                {"issue_id": "cn4", "期望输出": "误触发"},
            ],
        )

        response = _review_analysis_export_response(result, "trail_xlsx")
        workbook = openpyxl.load_workbook(io.BytesIO(response.body), read_only=True)
        try:
            worksheet = workbook.active
            self.assertEqual(worksheet.title, "GT 更新")
            self.assertEqual(
                list(worksheet.iter_rows(values_only=True)),
                [
                    ("issue_id", "期望输出"),
                    ("cn1", "正确触发"),
                    ("cn4", "误触发"),
                ],
            )
        finally:
            workbook.close()
        self.assertIn(
            'filename="gt-update-',
            response.headers["content-disposition"],
        )


if __name__ == "__main__":
    unittest.main()
