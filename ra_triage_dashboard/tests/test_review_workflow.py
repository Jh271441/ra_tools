from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
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
            "ra_triage_dashboard.app.routers.cases.database.list_cases",
            return_value=raw,
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
