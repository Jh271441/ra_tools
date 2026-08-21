from __future__ import annotations

import asyncio
import io
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl
from starlette.datastructures import UploadFile
from starlette.requests import Request

from ra_triage_dashboard.app.routers import trail_update
from ra_triage_dashboard.app.routers.trail_update import (
    TRAIL_INFO_FIELD,
    TRAIL_ISSUE_EXCLUSION_COMMENT,
    TRAIL_RESULT_FIELD,
    TRAIL_TARGET_PATH,
    _issue_import_json_rows,
    _normalise_issue_entries,
    build_trail_attribute_update_payload,
    build_trail_issue_import_preview,
    build_trail_issue_exclusion_payload,
)


class TrailAttributeUpdateTest(unittest.TestCase):
    def test_excel_import_endpoint_is_read_only_preview(self) -> None:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "抽检"
        sheet.append(["Issue ID", "是否排除", "comment"])
        sheet.append(["cn00000001", "是", "人工确认"])
        sheet.append(["cn00000002", "否", "保留"])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        upload = UploadFile(
            filename="release0206抽检.xlsx",
            file=io.BytesIO(output.getvalue()),
        )
        payload = asyncio.run(
            trail_update.trail_issue_excel_import_preview(upload)
        )
        self.assertEqual(payload["mode"], "excel")
        self.assertTrue(payload["can_apply"])
        self.assertEqual(payload["summary"]["ready_count"], 1)
        self.assertEqual(payload["summary"]["skipped_count"], 1)
        self.assertEqual([entry["issue_id"] for entry in payload["entries"]], ["cn00000001"])
        self.assertIn("Excel 上传来源：release0206抽检.xlsx", payload["entries"][0]["comment"])

    def test_json_issue_import_preview_keeps_historical_source_and_legacy_drafts(self) -> None:
        source = {
            "kind": "historical_spotcheck_xlsx",
            "source_id": "spotcheck-0206",
            "label": "0206 抽检",
            "baseline_id": "0206",
            "filename": "release0206版本 RA问题review.xlsx",
            "sha256": "a" * 64,
            "row_number": 269,
            "issue_id": "cn00000001",
            "column": "是否排除",
            "value": "是",
        }
        rows, context = _issue_import_json_rows(
            {
                "draft": {
                    "requested_entries": [
                        {
                            "issue_id": "cn00000001",
                            "comment": "历史抽检说明",
                            "source": source,
                        },
                        {"issue_id": "cn00000002", "should_exclude": False},
                    ]
                }
            }
        )
        preview = build_trail_issue_import_preview(
            rows,
            import_format="json",
            fallback_comment=context["fallback_comment"],
            comment_by_issue=context["comment_by_issue"],
        )
        self.assertTrue(preview["can_apply"])
        self.assertEqual(preview["summary"]["ready_count"], 1)
        self.assertEqual(preview["summary"]["skipped_count"], 1)
        self.assertEqual(preview["entries"][0]["issue_id"], "cn00000001")
        self.assertEqual(preview["entries"][0]["source"], source)
        self.assertIn("未提供「是否排除」", preview["warnings"][0])

    def test_excel_issue_import_preview_filters_false_rows_and_marks_invalid_rows(self) -> None:
        preview = build_trail_issue_import_preview(
            [
                {
                    "Issue ID": "cn00000001",
                    "是否排除": "是",
                    "comment": "人工确认无需处理",
                },
                {
                    "Issue ID": "cn00000002",
                    "是否排除": "否",
                    "comment": "保留",
                },
                {
                    "Issue ID": "cn00000003",
                    "是否排除": "不确定",
                },
                {
                    "Issue ID": "cn00000004",
                    "是否排除": "",
                },
            ],
            import_format="excel",
            filename="/Users/didi/utils/release0206抽检.xlsx",
            source_sha256="b" * 64,
            metadata={"sheet": "抽检"},
            require_exclusion_column=True,
            row_number_offset=2,
        )
        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["summary"]["ready_count"], 1)
        self.assertEqual(preview["summary"]["skipped_count"], 2)
        self.assertEqual(preview["summary"]["invalid_count"], 1)
        self.assertEqual(preview["items"][1]["status"], "skipped")
        self.assertEqual(preview["items"][3]["status"], "skipped")
        self.assertIn("未填写是否排除", preview["items"][3]["message"])
        self.assertIn("Excel 上传来源：release0206抽检.xlsx", preview["entries"][0]["comment"])
        self.assertIn("人工确认无需处理", preview["entries"][0]["comment"])

    def test_excel_issue_import_preview_requires_explicit_exclusion_column_and_no_duplicates(self) -> None:
        missing_column = build_trail_issue_import_preview(
            [{"issue_id": "cn00000001", "comment": "x"}],
            import_format="excel",
            filename="input.xlsx",
            require_exclusion_column=True,
            row_number_offset=2,
        )
        self.assertFalse(missing_column["can_apply"])
        self.assertIn("缺少必填列「是否排除」", missing_column["global_errors"][0])

        duplicate = build_trail_issue_import_preview(
            [
                {"issue_id": "cn00000001", "是否排除": True},
                {"issue_id": "cn00000001", "是否排除": "1"},
            ],
            import_format="excel",
            filename="input.xlsx",
            source_sha256="c" * 64,
            require_exclusion_column=True,
            row_number_offset=2,
        )
        self.assertFalse(duplicate["can_apply"])
        self.assertEqual(duplicate["summary"]["ready_count"], 1)
        self.assertEqual(duplicate["summary"]["invalid_count"], 1)
        self.assertIn("重复", duplicate["items"][1]["message"])

    def test_issue_entries_keep_row_comments_and_reject_duplicates(self) -> None:
        entries, invalid = _normalise_issue_entries(
            [
                {"issue_id": "cn00000002", "comment": "泊入二次寻点"},
                {"issue_id": "cn00000001", "comment": "红绿灯场景"},
                {"issue_id": "cn00000001", "comment": "重复"},
                {"issue_id": "not an issue", "comment": "非法"},
            ]
        )
        self.assertEqual(
            entries,
            [
                {"issue_id": "cn00000001", "comment": "红绿灯场景"},
                {"issue_id": "cn00000002", "comment": "泊入二次寻点"},
            ],
        )
        self.assertEqual(invalid, ["cn00000001（重复）", "not an issue"])

    def test_historical_exclusion_source_is_server_resolved_and_signed_into_preview(self) -> None:
        source = {
            "kind": "historical_spotcheck_xlsx",
            "source_id": "spotcheck-0206",
            "label": "0206 抽检",
            "baseline_id": "0206",
            "filename": "release0206版本 RA问题review.xlsx",
            "sha256": "a" * 64,
            "row_number": 269,
            "issue_id": "cn00000001",
            "column": "是否排除",
            "value": "是",
        }
        candidate = {
            "issue_id": "cn00000001",
            "comment": "历史抽检排除来源：0206 抽检（第 269 行）。",
            "source": source,
        }
        index = SimpleNamespace(
            resolve_exclusion_candidate=lambda **kwargs: candidate
            if kwargs == {"issue_id": "cn00000001", "source": source}
            else None
        )
        entries, invalid = _normalise_issue_entries(
            [{"issue_id": "cn00000001", "comment": "浏览器说明", "source": source}]
        )
        self.assertFalse(invalid)
        with patch.object(trail_update, "issue_tag_sources", index):
            resolved, source_invalid = trail_update._resolve_historical_exclusion_entries(entries)
        self.assertFalse(source_invalid)
        self.assertEqual(resolved[0]["comment"], candidate["comment"])
        self.assertEqual(resolved[0]["source"], source)
        payload = build_trail_issue_exclusion_payload(
            ["cn00000001"],
            current_rows=[{"issue_id": "cn00000001", TRAIL_INFO_FIELD: {}}],
            comment_by_issue={"cn00000001": resolved[0]["comment"]},
            requested_entries=resolved,
            trail_capability={"ready": True, "status": "ready"},
            trail_write_enabled=True,
        )
        self.assertEqual(payload["requested_entries"][0]["source"], source)
        self.assertEqual(payload["items"][0]["source"], source)
        self.assertEqual(payload["draft"]["requested_entries"][0]["source"], source)
        self.assertIn("历史抽检", payload["items"][0]["comment"])

    def test_historical_exclusion_endpoint_is_read_only_and_baseline_scoped(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/trail-attribute-update/historical-exclusions",
                "query_string": b"baselines=0206",
                "headers": [],
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1),
            }
        )
        expected = [{"issue_id": "cn00000001", "source": {"source_id": "spotcheck-0206"}}]
        source_index = SimpleNamespace(exclusion_candidates=lambda **kwargs: expected)
        with patch.object(
            trail_update, "resolve_request_baseline_ids", return_value=["0206"]
        ), patch.object(trail_update, "issue_tag_sources", source_index):
            payload = asyncio.run(
                trail_update.trail_historical_exclusions(request, baselines="0206")
            )
        self.assertEqual(payload["mode"], "historical_spotcheck_xlsx")
        self.assertEqual(payload["baselines"], ["0206"])
        self.assertEqual(payload["items"], expected)

    def test_read_only_preview_probes_remote_trail_statuses(self) -> None:
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
        sync = SimpleNamespace(
            rows=[
                {
                    "issue_id": "cn00000001",
                    TRAIL_INFO_FIELD: {"ra_triage_dashboard": {"should_exclude": True}},
                }
            ],
            fields_visible=(TRAIL_INFO_FIELD,),
            complete=True,
            queried_issues=1,
            returned_issues=1,
            view_id=2410,
            message="Trail status read",
        )
        trail_update._preview_capability_cache.clear()
        with patch.object(
            trail_update.database, "review_reason_rows", return_value=[row]
        ) as review_rows, patch.object(
            trail_update, "read_trail_model_fields", return_value=sync
        ) as probe:
            payload = asyncio.run(
                trail_update._build_preview(
                    request,
                    selected_run_id="",
                    baselines="0508",
                )
            )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["trail_capability"]["status"], "ready")
        self.assertEqual(payload["items"][0]["trail_update_status"], "synced")
        # Trail candidates stay strictly bound to the requested Run.  The
        # read-only Gallery/analysis legacy fallback is intentionally opt-in
        # and must never leak into the signed writer preview.
        self.assertNotIn(
            "include_unbound_fallback", review_rows.call_args.kwargs
        )
        probe.assert_called_once()

    def test_manual_refresh_bypasses_trail_status_cache(self) -> None:
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
            "issue_id": "cn00000009",
            "annotation": {"id": 9, "is_excluded": True},
            "prediction": {"model_run_id": "run-9", "label": "误触发"},
        }
        synced = SimpleNamespace(
            rows=[{"issue_id": "cn00000009", TRAIL_INFO_FIELD: {"ra_triage_dashboard": {"should_exclude": True}}}],
            fields_visible=(TRAIL_INFO_FIELD,), complete=True, queried_issues=1, returned_issues=1,
            view_id=2410, message="Trail status read",
        )
        pending = SimpleNamespace(
            rows=[{"issue_id": "cn00000009", TRAIL_INFO_FIELD: {"ra_triage_dashboard": {"should_exclude": False}}}],
            fields_visible=(TRAIL_INFO_FIELD,), complete=True, queried_issues=1, returned_issues=1,
            view_id=2410, message="Trail status read",
        )
        trail_update._preview_capability_cache.clear()
        with patch.object(trail_update.database, "review_reason_rows", return_value=[row]), patch.object(
            trail_update, "read_trail_model_fields", side_effect=[synced, pending]
        ) as probe:
            first = asyncio.run(trail_update._build_preview(request, selected_run_id="", baselines="0508"))
            cached = asyncio.run(trail_update._build_preview(request, selected_run_id="", baselines="0508"))
            refreshed = asyncio.run(
                trail_update._build_preview(
                    request, selected_run_id="", baselines="0508", refresh_trail=True
                )
            )
        self.assertEqual(first["items"][0]["trail_update_status"], "synced")
        self.assertEqual(cached["items"][0]["trail_update_status"], "synced")
        self.assertEqual(refreshed["items"][0]["trail_update_status"], "pending")
        self.assertEqual(probe.call_count, 2)

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

    def test_compact_status_endpoint_skips_review_aggregation(self) -> None:
        sync = SimpleNamespace(
            rows=[
                {
                    "issue_id": "cn00000001",
                    TRAIL_INFO_FIELD: {
                        "ra_triage_dashboard": {"should_exclude": True}
                    },
                }
            ],
            fields_visible=(TRAIL_INFO_FIELD,),
            complete=True,
            queried_issues=1,
            returned_issues=1,
            view_id=2410,
            message="Trail status read",
        )
        trail_update._preview_capability_cache.clear()
        with patch.object(
            trail_update, "read_trail_model_fields", return_value=sync
        ) as probe, patch.object(
            trail_update.database,
            "review_reason_rows",
            side_effect=AssertionError("status endpoint must not rebuild candidates"),
        ):
            payload = asyncio.run(
                trail_update.trail_attribute_update_status(
                    issue_ids="cn00000001"
                )
            )
        self.assertEqual(payload["trail_update_statuses"], {"cn00000001": "synced"})
        self.assertEqual(payload["trail_update_status_summary"], {"synced": 1})
        self.assertNotIn("items", payload)
        self.assertNotIn("draft", payload)
        probe.assert_called_once()

    def test_display_only_trail_status_does_not_expire_preview_digest(self) -> None:
        rows = [
            {
                "issue_id": "cn00000001",
                "gt_label": "误触发",
                "annotation": {"id": 1, "is_excluded": True},
                "prediction": {"model_run_id": "run-1", "label": "误触发"},
            }
        ]
        common = {
            "run": {"id": "run-1", "name": "test", "source_name": ""},
            "baseline_ids": ["0508"],
            "baseline_scopes": ["release0508_1071"],
            "write_mode": "info_only",
        }
        pending = build_trail_attribute_update_payload(
            rows,
            trail_statuses={"cn00000001": "pending"},
            **common,
        )
        synced = build_trail_attribute_update_payload(
            rows,
            trail_statuses={"cn00000001": "synced"},
            **common,
        )
        self.assertEqual(pending["payload_sha256"], synced["payload_sha256"])
        self.assertNotEqual(
            pending["items"][0]["trail_update_status"],
            synced["items"][0]["trail_update_status"],
        )

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

    def test_direct_issue_preview_keeps_row_specific_comments(self) -> None:
        payload = build_trail_issue_exclusion_payload(
            ["cn00000001", "cn00000002"],
            current_rows=[
                {"issue_id": "cn00000001", TRAIL_INFO_FIELD: {}},
                {"issue_id": "cn00000002", TRAIL_INFO_FIELD: {}},
            ],
            comment_by_issue={
                "cn00000001": "红绿灯场景",
                "cn00000002": "泊入二次寻点",
            },
            requested_entries=[
                {"issue_id": "cn00000001", "comment": "红绿灯场景"},
                {"issue_id": "cn00000002", "comment": "泊入二次寻点"},
            ],
            trail_capability={"ready": True, "status": "ready"},
            trail_write_enabled=True,
        )
        by_issue = {item["issue_id"]: item for item in payload["items"]}
        self.assertEqual(
            by_issue["cn00000001"]["target"]["patch"]["ra_triage_dashboard"]["should_exclude_comment"],
            "红绿灯场景",
        )
        self.assertEqual(
            by_issue["cn00000002"]["target"]["patch"]["ra_triage_dashboard"]["should_exclude_comment"],
            "泊入二次寻点",
        )
        self.assertEqual(
            payload["requested_entries"],
            [
                {"issue_id": "cn00000001", "comment": "红绿灯场景"},
                {"issue_id": "cn00000002", "comment": "泊入二次寻点"},
            ],
        )

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

    def test_historical_source_is_appended_to_existing_local_review_note(self) -> None:
        actor = SimpleNamespace(username="jasperchen", source="sso", verified=True)
        case = {
            "issue_id": "cn00000001",
            "gt_label": "误触发",
            "annotations": [
                {
                    "id": 9,
                    "model_run_id": "run-1",
                    "label": "误触发",
                    "expected_output": "误触发",
                    "review_status": "pending",
                    "is_excluded": False,
                    "tags": [],
                    "missing_evidence": [],
                    "note": "原有 Review",
                }
            ],
        }
        source_note = "历史抽检排除来源：0206 抽检（第 269 行，SHA-256: abc）。"
        with patch.object(trail_update.database, "get_case", return_value=case), patch.object(
            trail_update.database, "create_annotation"
        ) as create:
            result = trail_update._mark_local_review_exclusions(
                ["cn00000001"],
                actor=actor,
                source_notes={"cn00000001": source_note},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(create.call_args.kwargs["note"], f"原有 Review\n\n{source_note}")

    def test_direct_issue_commit_keeps_trail_only_cases_out_of_local_failure(self) -> None:
        actor = SimpleNamespace(
            username="jasperchen",
            source="kylin_ticket",
            verified=True,
        )
        cases = {
            "cn00000001": {
                "issue_id": "cn00000001",
                "gt_label": "误触发",
                "annotations": [],
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
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["marked_count"], 1)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(result["not_in_dashboard_count"], 1)
        self.assertEqual(result["not_in_dashboard_issue_ids"], ["cn00000002"])
        create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
