from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request

from ra_triage_dashboard.app.routers import trail_update
from ra_triage_dashboard.app.routers.trail_update import (
    TRAIL_INFO_FIELD,
    TRAIL_ISSUE_EXCLUSION_COMMENT,
    TRAIL_RESULT_FIELD,
    TRAIL_TARGET_PATH,
    build_trail_attribute_update_payload,
    build_trail_issue_exclusion_payload,
)


class TrailAttributeUpdateTest(unittest.TestCase):
    def test_read_only_preview_skips_remote_trail_capability_probe(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/trail-attribute-update/preview",
                "query_string": b"baselines=0508",
                "headers": [],
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1),
            }
        )
        row = {
            "issue_id": "cn00000001",
            "gt_label": "误触发",
            "annotation": {
                "id": 1,
                "model_run_id": "run-1",
                "is_excluded": True,
                "author": "alice",
            },
            "prediction": {
                "model_run_id": "run-1",
                "label": "误触发",
            },
        }
        with patch.object(trail_update.database, "review_reason_rows", return_value=[row]), patch.object(
            trail_update, "read_trail_model_fields", side_effect=AssertionError("remote probe")
        ) as probe:
            payload = asyncio.run(
                trail_update._build_preview(
                    request,
                    selected_run_id="",
                    baselines="0508",
                )
            )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["trail_capability"]["status"], "not_checked")
        probe.assert_not_called()

    def test_info_only_preview_enables_review_write_when_snapshot_is_complete(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/trail-attribute-update/preview",
                "query_string": b"baselines=0508",
                "headers": [],
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1),
            }
        )
        row = {
            "issue_id": "cn00000001",
            "annotation": {"id": 1, "is_excluded": True},
            "prediction": {"model_run_id": "run-1", "label": "误触发"},
        }
        sync = SimpleNamespace(
            fields_visible=(),
            complete=True,
            queried_issues=1,
            returned_issues=1,
            view_id=2410,
            message="Trail 未返回旧 Issue 的空字段",
        )
        test_settings = replace(
            trail_update.settings,
            trail_attribute_write_enabled=True,
            trail_attribute_review_write_enabled=True,
        )
        with patch.object(trail_update, "settings", test_settings), patch.object(
            trail_update.database, "review_reason_rows", return_value=[row]
        ), patch.object(
            trail_update, "read_trail_model_fields", return_value=sync
        ):
            payload = asyncio.run(
                trail_update._build_preview(request, selected_run_id="", baselines="0508")
            )
        self.assertEqual(payload["write_mode"], "info_only")
        self.assertEqual(payload["target_fields"], [TRAIL_INFO_FIELD])
        self.assertEqual(payload["write_status"], "ready")
        self.assertTrue(payload["write_ready"])

    def test_review_preview_can_skip_remote_probe_for_fast_first_paint(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/trail-attribute-update/preview",
                "query_string": b"baselines=0508&probe_trail=false",
                "headers": [],
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1),
            }
        )
        row = {
            "issue_id": "cn00000001",
            "annotation": {"id": 1, "is_excluded": True},
            "prediction": {"model_run_id": "run-1", "label": "误触发"},
        }
        test_settings = replace(
            trail_update.settings,
            trail_attribute_write_enabled=True,
            trail_attribute_review_write_enabled=True,
        )
        with patch.object(trail_update, "settings", test_settings), patch.object(
            trail_update.database, "review_reason_rows", return_value=[row]
        ), patch.object(
            trail_update, "read_trail_model_fields", side_effect=AssertionError("remote probe")
        ) as probe:
            payload = asyncio.run(
                trail_update._build_preview(
                    request,
                    selected_run_id="",
                    baselines="0508",
                    probe_trail=False,
                )
            )
        self.assertTrue(payload["capability_pending"])
        self.assertEqual(payload["trail_capability"]["status"], "not_checked")
        self.assertFalse(payload["write_ready"])
        probe.assert_not_called()

    def test_payload_is_run_bound_sorted_and_write_disabled(self) -> None:
        rows = [
            {
                "issue_id": "cn00000002",
                "baseline_scope": "release0508_1071",
                "title": "second",
                "gt_label": "误触发",
                "annotation": {
                    "id": 22,
                    "model_run_id": "run-1",
                    "review_status": "已 Review",
                    "author": "jasperchen",
                    "created_at": "2026-08-15T10:02:00Z",
                    "note": "exclude",
                    "tags": ["排队"],
                    "missing_evidence": [],
                    "is_excluded": True,
                },
                "prediction": {
                    "model_run_id": "run-1",
                    "label": "误触发",
                    "reason": "queue",
                    "confidence": 0.9,
                },
            },
            {
                "issue_id": "cn00000001",
                "gt_label": "无需协助",
                "annotation": {"id": 11, "is_excluded": False},
                "prediction": {},
            },
        ]
        payload = build_trail_attribute_update_payload(
            rows,
            run={"id": "run-1", "name": "run name", "source_name": "source"},
            baseline_ids=["0508"],
            baseline_scopes=["release0508_1071"],
        )

        self.assertFalse(payload["trail_write_enabled"])
        self.assertEqual(payload["write_status"], "disabled")
        self.assertEqual(payload["target_fields"], [TRAIL_RESULT_FIELD, TRAIL_INFO_FIELD])
        self.assertFalse(payload["write_ready"])
        self.assertEqual(payload["target_field"], TRAIL_INFO_FIELD)
        self.assertEqual(payload["target_path"], TRAIL_TARGET_PATH)
        self.assertEqual(payload["comment_target_path"], "ra_triage_dashboard.should_exclude_comment")
        self.assertEqual(payload["count"], 1)
        item = payload["items"][0]
        self.assertEqual(item["issue_id"], "cn00000002")
        self.assertEqual(item["baseline_id"], "0508")
        self.assertEqual(item["baseline_scope"], "release0508_1071")
        self.assertEqual(item["target"]["merge_strategy"], "deep_merge")
        self.assertEqual(
            item["target"]["patch"],
            {"ra_triage_dashboard": {"should_exclude": True, "should_exclude_comment": "exclude"}},
        )
        self.assertEqual(item["field_updates"][TRAIL_RESULT_FIELD], "误触发")
        self.assertEqual(item["field_updates"][TRAIL_INFO_FIELD], item["target"]["patch"])
        self.assertEqual(payload["draft"]["payload_sha256"], payload["payload_sha256"])
        self.assertEqual(payload["operation_id"], payload["payload_sha256"])

    def test_payload_digest_changes_when_review_evidence_changes(self) -> None:
        row = {
            "issue_id": "cn00000001",
            "annotation": {"id": 1, "is_excluded": True, "note": "a"},
            "prediction": {},
        }
        first = build_trail_attribute_update_payload(
            [row], run={"id": "run-1"}, baseline_ids=["0508"], baseline_scopes=["scope"]
        )
        changed = dict(row, annotation=dict(row["annotation"], note="b"))
        second = build_trail_attribute_update_payload(
            [changed], run={"id": "run-1"}, baseline_ids=["0508"], baseline_scopes=["scope"]
        )
        self.assertNotEqual(first["payload_sha256"], second["payload_sha256"])

    def test_info_only_review_preview_does_not_require_model_label_field(self) -> None:
        row = {
            "issue_id": "cn00000001",
            "gt_label": "误触发",
            "annotation": {"id": 1, "is_excluded": True, "note": "保留 info"},
            "prediction": {"model_run_id": "run-1", "label": "误触发", "reason": "queue"},
        }
        capability = trail_update._capability_for_info_write(
            SimpleNamespace(
                fields_visible=(),
                complete=True,
                queried_issues=1,
                returned_issues=1,
                view_id=2410,
                message="Trail 未返回空字段",
            ),
            TRAIL_INFO_FIELD,
        )
        self.assertTrue(capability["ready"])
        self.assertEqual(capability["status"], "ready")
        payload = build_trail_attribute_update_payload(
            [row],
            run={"id": "run-1"},
            baseline_ids=["0508"],
            baseline_scopes=["scope"],
            trail_capability=capability,
            trail_write_enabled=True,
            write_mode="info_only",
        )
        self.assertEqual(payload["write_mode"], "info_only")
        self.assertEqual(payload["target_fields"], [TRAIL_INFO_FIELD])
        self.assertEqual(payload["comment_target_path"], "ra_triage_dashboard.should_exclude_comment")
        self.assertTrue(payload["write_ready"])
        self.assertEqual(payload["items"][0]["field_updates"], {TRAIL_INFO_FIELD: payload["items"][0]["target"]["patch"]})

    def test_info_only_review_preview_allows_missing_model_label(self) -> None:
        payload = build_trail_attribute_update_payload(
            [
                {
                    "issue_id": "cn00000003",
                    "annotation": {"id": 3, "is_excluded": True},
                    "prediction": {"model_run_id": "run-1"},
                }
            ],
            run={"id": "run-1"},
            baseline_ids=["0508"],
            baseline_scopes=["scope"],
            trail_capability={"ready": True, "status": "ready", "fields_visible": [TRAIL_INFO_FIELD]},
            trail_write_enabled=True,
            write_mode="info_only",
        )
        self.assertTrue(payload["write_ready"])
        self.assertEqual(payload["invalid_label_issue_ids"], [])

    def test_trail_update_statuses_are_projected_from_one_batched_snapshot(self) -> None:
        sync = SimpleNamespace(
            rows=[
                {
                    "issue_id": "cn00000001",
                    TRAIL_INFO_FIELD: {"ra_triage_dashboard": {"should_exclude": True}},
                },
                {
                    "issue_id": "cn00000002",
                    TRAIL_INFO_FIELD: {"ra_triage_dashboard": {"should_exclude": False}},
                },
            ],
            complete=True,
        )
        self.assertEqual(
            trail_update._trail_update_statuses(
                sync,
                ["cn00000001", "cn00000002", "cn00000003"],
                info_field=TRAIL_INFO_FIELD,
            ),
            {
                "cn00000001": "synced",
                "cn00000002": "pending",
                "cn00000003": "not_found",
            },
        )

    def test_first_paint_marks_status_querying_without_remote_read(self) -> None:
        payload = build_trail_attribute_update_payload(
            [
                {
                    "issue_id": "cn00000004",
                    "annotation": {"id": 4, "is_excluded": True},
                    "prediction": {"model_run_id": "run-1", "label": "误触发"},
                }
            ],
            run={"id": "run-1"},
            baseline_ids=["0508"],
            baseline_scopes=["scope"],
            trail_capability={"ready": False, "status": "not_checked"},
            trail_write_enabled=True,
            write_mode="info_only",
        )
        self.assertEqual(payload["items"][0]["trail_update_status"], "querying")
        self.assertEqual(payload["trail_update_status_summary"], {"querying": 1})

    def test_direct_issue_preview_only_targets_info_field_and_reports_missing(self) -> None:
        payload = build_trail_issue_exclusion_payload(
            ["cn00000001", "cn00000002"],
            current_rows=[
                {
                    "issue_id": "cn00000001",
                    "ra_stuck_auto_result": "正确触发",
                    "ra_stuck_auto_result_info": {
                        "keep": True,
                        "ra_triage_dashboard": {"should_exclude": False},
                    },
                }
            ],
            comment="人工屏蔽",
            baseline_by_issue={
                "cn00000001": {
                    "baseline_id": "0206",
                    "baseline_scope": "release0206_1326",
                }
            },
            trail_capability={
                "view_id": 2410,
                "fields_visible": [TRAIL_INFO_FIELD],
                "ready": True,
                "status": "ready",
                "message": "ready",
            },
            trail_write_enabled=True,
        )
        self.assertEqual(payload["write_status"], "missing_issues")
        self.assertEqual(payload["missing_issue_ids"], ["cn00000002"])
        self.assertEqual(payload["target_fields"], [TRAIL_INFO_FIELD])
        self.assertEqual(payload["write_mode"], "info_only")
        self.assertEqual(payload["items"][0]["current_label"], "正确触发")
        self.assertTrue(payload["items"][0]["target"]["patch"]["ra_triage_dashboard"]["should_exclude"])
        self.assertEqual(
            payload["items"][0]["target"]["patch"],
            {"ra_triage_dashboard": {"should_exclude": True, "should_exclude_comment": "人工屏蔽"}},
        )
        field_update = payload["items"][0]["field_update"]
        self.assertEqual(field_update["field"], TRAIL_INFO_FIELD)
        self.assertEqual(field_update["before"]["keep"], True)
        self.assertEqual(field_update["after"]["keep"], True)
        self.assertTrue(field_update["after"]["ra_triage_dashboard"]["should_exclude"])
        self.assertEqual(
            field_update["after"]["ra_triage_dashboard"]["should_exclude_comment"],
            "人工屏蔽",
        )
        self.assertTrue(field_update["model_label_unchanged"])
        self.assertEqual(payload["items"][0]["comment"], "人工屏蔽")
        self.assertEqual(payload["items"][0]["baseline_id"], "0206")
        self.assertEqual(payload["items"][0]["baseline_scope"], "release0206_1326")
        self.assertFalse(payload["items"][0]["comment_defaulted"])
        self.assertEqual(payload["draft"]["payload_sha256"], payload["payload_sha256"])
        self.assertEqual(payload["operation_id"], payload["payload_sha256"])

    def test_direct_issue_preview_adds_auditable_default_comment(self) -> None:
        payload = build_trail_issue_exclusion_payload(
            ["cn00000001"],
            current_rows=[{"issue_id": "cn00000001"}],
            trail_capability={"ready": True, "status": "ready"},
            trail_write_enabled=True,
        )
        self.assertEqual(payload["write_status"], "ready")
        self.assertEqual(payload["comment"], TRAIL_ISSUE_EXCLUSION_COMMENT)
        self.assertEqual(payload["items"][0]["comment"], TRAIL_ISSUE_EXCLUSION_COMMENT)
        self.assertEqual(
            payload["items"][0]["target"]["patch"]["ra_triage_dashboard"]["should_exclude_comment"],
            TRAIL_ISSUE_EXCLUSION_COMMENT,
        )
        self.assertTrue(payload["items"][0]["comment_defaulted"])

    def test_direct_issue_commit_marks_latest_review_as_excluded(self) -> None:
        actor = SimpleNamespace(
            username="jasperchen",
            source="kylin_ticket",
            verified=True,
        )
        cases = {
            "cn00000001": {
                "issue_id": "cn00000001",
                "gt_label": "误触发",
                "annotations": [
                    {
                        "id": 9,
                        "model_run_id": "run-1",
                        "label": "无需协助",
                        "expected_output": "无需协助",
                        "review_status": "pending",
                        "is_excluded": False,
                        "tags": ["排队"],
                        "missing_evidence": [],
                        "note": "原有 Review",
                    }
                ],
            },
            "cn00000002": {
                "issue_id": "cn00000002",
                "gt_label": "无需协助",
                "annotations": [
                    {
                        "id": 10,
                        "model_run_id": "",
                        "label": "无需协助",
                        "expected_output": "无需协助",
                        "is_excluded": True,
                    }
                ],
            },
        }
        with patch.object(
            trail_update.database,
            "get_case",
            side_effect=lambda issue_id: cases.get(issue_id),
        ), patch.object(trail_update.database, "create_annotation") as create:
            result = trail_update._mark_local_review_exclusions(
                ["cn00000001", "cn00000002"],
                actor=actor,
                fallback_note="人工屏蔽",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["marked_count"], 1)
        self.assertEqual(result["already_excluded_count"], 1)
        create.assert_called_once_with(
            issue_id="cn00000001",
            model_run_id="run-1",
            label="无需协助",
            review_status="pending",
            is_excluded=True,
            tags=["排队"],
            missing_evidence=[],
            note="原有 Review",
            author="jasperchen",
            author_source="kylin_ticket",
            author_verified=True,
            expected_previous_annotation_id=9,
        )


if __name__ == "__main__":
    unittest.main()
