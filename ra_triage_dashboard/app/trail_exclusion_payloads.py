"""Deterministic Trail exclusion draft builders.

The HTTP router supplies runtime configuration and remote snapshots.  This
module turns already-materialized Reviews or Trail rows into signed, pure data
objects.  It intentionally cannot write Trail, query the database, or inspect
request identity.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from .trail_exclusion_contracts import (
    TRAIL_COMMENT_PATH,
    TRAIL_DRAFT_SCHEMA,
    TRAIL_INFO_FIELD,
    TRAIL_ISSUE_DRAFT_SCHEMA,
    TRAIL_ISSUE_EXCLUSION_COMMENT,
    TRAIL_RESULT_FIELD,
    TRAIL_TARGET_PATH,
    as_text,
    canonical_json,
    dashboard_exclusion_values,
    normalise_exclusion_comment,
    trail_update_status_summary,
)
from .trail_writer import deep_merge_dict, normalise_model_label


def build_review_exclusion_payload(
    rows: list[dict[str, Any]],
    *,
    run: Mapping[str, Any],
    baseline_ids: list[str],
    baseline_scopes: list[str],
    result_field: str = TRAIL_RESULT_FIELD,
    info_field: str = TRAIL_INFO_FIELD,
    trail_capability: Mapping[str, Any] | None = None,
    trail_statuses: Mapping[str, str] | None = None,
    trail_write_enabled: bool = False,
    write_mode: str = "model_and_info",
    not_checked_capability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, Run-bound Review exclusion draft."""

    run_id = as_text(run.get("id"))
    info_only = write_mode == "info_only"
    baseline_by_scope = {
        as_text(scope): as_text(baseline_ids[index])
        for index, scope in enumerate(baseline_scopes)
        if index < len(baseline_ids) and as_text(scope) and as_text(baseline_ids[index])
    }
    items: list[dict[str, Any]] = []
    invalid_labels: list[str] = []
    for row in rows:
        annotation = row.get("annotation") or {}
        prediction = row.get("prediction") or {}
        issue_id = as_text(row.get("issue_id"))
        if not issue_id or not bool(annotation.get("is_excluded")):
            continue
        review_id = annotation.get("id")
        raw_label = as_text(prediction.get("label"))
        label = normalise_model_label(raw_label)
        source_run_id = (
            as_text(prediction.get("model_run_id"))
            or as_text(annotation.get("model_run_id"))
            or run_id
        )
        if not label and not info_only:
            invalid_labels.append(issue_id)
        comment_text = normalise_exclusion_comment(annotation.get("note"))
        patch = {
            "ra_triage_dashboard": {
                "should_exclude": True,
                "should_exclude_comment": comment_text,
            }
        }
        items.append(
            {
                "issue_id": issue_id,
                "baseline_id": baseline_by_scope.get(as_text(row.get("baseline_scope")), ""),
                "baseline_scope": as_text(row.get("baseline_scope")),
                "title": as_text(row.get("title")),
                "scenario": as_text(row.get("scenario")),
                "gt_label": as_text(row.get("gt_label")),
                "model": {
                    "run_id": source_run_id,
                    "label": label or raw_label,
                    "reason": as_text(prediction.get("reason")),
                    "confidence": prediction.get("confidence"),
                },
                "review": {
                    "id": review_id,
                    "model_run_id": source_run_id,
                    "status": as_text(annotation.get("review_status")),
                    "reviewer": as_text(annotation.get("author")),
                    "reviewed_at": as_text(annotation.get("created_at")),
                    "note": as_text(annotation.get("note")),
                    "tags": list(annotation.get("tags") or []),
                    "missing_evidence": list(annotation.get("missing_evidence") or []),
                    "is_excluded": True,
                },
                "comment": comment_text,
                "write_ready": bool(label) or info_only,
                "trail_update_status": as_text((trail_statuses or {}).get(issue_id))
                or ("querying" if trail_statuses is None else "not_checked"),
                "target": {
                    "field": info_field,
                    "result_field": result_field,
                    "path": TRAIL_TARGET_PATH,
                    "comment_path": TRAIL_COMMENT_PATH,
                    "merge_strategy": "deep_merge",
                    "patch": patch,
                },
                "field_updates": (
                    {info_field: patch}
                    if info_only
                    else {result_field: label or raw_label, info_field: patch}
                ),
            }
        )
    items.sort(key=lambda item: item["issue_id"])
    status_summary = trail_update_status_summary(
        {as_text(item.get("issue_id")): as_text(item.get("trail_update_status")) for item in items}
    )
    pending_issue_ids = [
        as_text(item.get("issue_id"))
        for item in items
        if as_text(item.get("trail_update_status")) == "pending"
    ]
    incomplete_statuses = {"querying", "query_failed", "not_found", "not_checked"}
    status_check_complete = not any(
        as_text(item.get("trail_update_status")) in incomplete_statuses for item in items
    )
    draft: dict[str, Any] = {
        "schema_version": TRAIL_DRAFT_SCHEMA,
        "mode": "preview",
        "trail_write_enabled": bool(trail_write_enabled),
        "write_mode": "info_only" if info_only else "model_and_info",
        "target_fields": [info_field] if info_only else [result_field, info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
        "comment_target_path": TRAIL_COMMENT_PATH,
        "merge_strategy": "deep_merge",
        "model_run_id": run_id,
        "model_run_ids": sorted(
            {
                as_text(item.get("model", {}).get("run_id"))
                for item in items
                if as_text(item.get("model", {}).get("run_id"))
            }
        ),
        "model_run_name": as_text(run.get("name")),
        "baseline_ids": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "items": items,
    }
    digest_draft = {
        **draft,
        "items": [
            {key: value for key, value in item.items() if key != "trail_update_status"}
            for item in items
        ],
    }
    digest = hashlib.sha256(canonical_json(digest_draft).encode("utf-8")).hexdigest()
    draft["payload_sha256"] = digest
    draft["operation_id"] = digest
    capability = dict(trail_capability or not_checked_capability or {})
    if not capability:
        capability = {
            "target_fields": [info_field] if info_only else [result_field, info_field],
            "required_fields": [info_field] if info_only else [],
            "fields_visible": [],
            "ready": False,
            "status": "not_checked",
            "message": "生成候选项后检查 Trail view 字段。",
        }
    if not trail_write_enabled:
        write_status = "disabled"
    elif not capability.get("ready"):
        write_status = "fields_unavailable"
    elif invalid_labels:
        write_status = "invalid_labels"
    elif not status_check_complete:
        write_status = "status_check_incomplete"
    elif not pending_issue_ids:
        write_status = "already_synced"
    else:
        write_status = "ready"
    return {
        "schema_version": TRAIL_DRAFT_SCHEMA,
        "mode": "preview",
        "trail_write_enabled": bool(trail_write_enabled),
        "write_status": write_status,
        "write_ready": write_status == "ready",
        "write_mode": "info_only" if info_only else "model_and_info",
        "model_result_field": result_field,
        "target_fields": [info_field] if info_only else [result_field, info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
        "comment_target_path": TRAIL_COMMENT_PATH,
        "merge_strategy": "deep_merge",
        "trail_capability": capability,
        "selected_run": {
            "id": run_id,
            "name": as_text(run.get("name")) or ("全部 Model Runs" if not run_id else ""),
            "source_name": as_text(run.get("source_name")),
            "created_at": as_text(run.get("created_at")),
            "all_runs": not bool(run_id),
        },
        "baselines": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "count": len(items),
        "pending_count": len(pending_issue_ids),
        "pending_issue_ids": pending_issue_ids,
        "invalid_label_issue_ids": invalid_labels,
        "payload_sha256": digest,
        "operation_id": digest,
        "trail_update_status_summary": status_summary,
        "items": items,
        "draft": draft,
    }


def build_direct_issue_exclusion_payload(
    issue_ids: list[str],
    *,
    current_rows: list[dict[str, Any]],
    invalid_issue_ids: list[str] | None = None,
    comment: str = "",
    comment_by_issue: Mapping[str, str] | None = None,
    requested_entries: list[dict[str, Any]] | None = None,
    baseline_by_issue: Mapping[str, Mapping[str, Any]] | None = None,
    info_field: str = TRAIL_INFO_FIELD,
    trail_capability: Mapping[str, Any] | None = None,
    trail_write_enabled: bool = False,
    view_id: int = 0,
    normalise_source: Callable[[Any], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Build a signed, info-only direct Issue-ID shielding preview."""

    current_by_issue = {
        as_text(row.get("issue_id")): row
        for row in current_rows
        if as_text(row.get("issue_id"))
    }
    supplied_comment = as_text(comment).strip()[:4000]
    supplied_comments = {
        as_text(issue_id).strip(): as_text(note).strip()[:4000]
        for issue_id, note in (comment_by_issue or {}).items()
        if as_text(issue_id).strip()
    }
    if not supplied_comments and supplied_comment:
        supplied_comments = {issue_id: supplied_comment for issue_id in issue_ids}
    normalized_comment = supplied_comment or (
        next(iter(supplied_comments.values())) if len(set(supplied_comments.values())) == 1 else ""
    )
    if not normalized_comment and all(not note for note in supplied_comments.values()):
        normalized_comment = TRAIL_ISSUE_EXCLUSION_COMMENT
    normalized_entries: list[dict[str, Any]] = []
    for item in requested_entries or []:
        issue_id = as_text(item.get("issue_id")).strip()
        if not issue_id:
            continue
        entry: dict[str, Any] = {
            "issue_id": issue_id,
            "comment": as_text(item.get("comment")).strip()[:4000],
        }
        source = normalise_source(item.get("source")) if normalise_source else None
        if source is not None:
            entry["source"] = source
        normalized_entries.append(entry)
    for entry in normalized_entries:
        supplied_comments.setdefault(entry["issue_id"], entry["comment"])
    if not normalized_entries:
        normalized_entries = [
            {"issue_id": issue_id, "comment": supplied_comments.get(issue_id, supplied_comment)}
            for issue_id in issue_ids
        ]
    normalized_entries.sort(key=lambda item: item["issue_id"])
    source_by_issue = {
        entry["issue_id"]: entry["source"]
        for entry in normalized_entries
        if isinstance(entry.get("source"), Mapping)
    }
    release_by_issue = baseline_by_issue or {}
    missing = sorted(issue_id for issue_id in issue_ids if issue_id not in current_by_issue)
    items: list[dict[str, Any]] = []
    for issue_id in issue_ids:
        current = current_by_issue.get(issue_id)
        if current is None:
            continue
        current_info = current.get(info_field)
        if isinstance(current_info, str):
            try:
                current_info = json.loads(current_info)
            except (TypeError, ValueError, json.JSONDecodeError):
                current_info = {}
        if not isinstance(current_info, dict):
            current_info = {}
        supplied_item_comment = supplied_comments.get(issue_id, supplied_comment)
        comment_defaulted = not bool(supplied_item_comment)
        normalized_item_comment = normalise_exclusion_comment(
            supplied_item_comment or TRAIL_ISSUE_EXCLUSION_COMMENT
        )
        current_marker, current_comment = dashboard_exclusion_values(current_info)
        patch = {
            "ra_triage_dashboard": {
                "should_exclude": True,
                "should_exclude_comment": normalized_item_comment,
            }
        }
        merged_info = deep_merge_dict(current_info, patch)
        item: dict[str, Any] = {
            "issue_id": issue_id,
            "baseline_id": as_text((release_by_issue.get(issue_id) or {}).get("baseline_id")),
            "baseline_scope": as_text((release_by_issue.get(issue_id) or {}).get("baseline_scope")),
            "current_label": as_text(current.get(TRAIL_RESULT_FIELD)),
            "current_should_exclude": current_marker is True,
            "trail_update_status": (
                "synced"
                if current_marker is True and current_comment == normalized_item_comment
                else "pending"
            ),
            "field_update": {
                "field": info_field,
                "operation": "deep_merge",
                "before": current_info,
                "after": merged_info,
                "patch": patch,
                "model_label_unchanged": True,
            },
            "target": {
                "field": info_field,
                "path": TRAIL_TARGET_PATH,
                "comment_path": TRAIL_COMMENT_PATH,
                "merge_strategy": "deep_merge",
                "patch": patch,
            },
            "comment": normalized_item_comment,
            "comment_defaulted": comment_defaulted,
            "write_ready": True,
        }
        source = source_by_issue.get(issue_id)
        if source is not None:
            item["source"] = source
        items.append(item)
    items.sort(key=lambda item: item["issue_id"])
    status_summary = trail_update_status_summary(
        {as_text(item.get("issue_id")): as_text(item.get("trail_update_status")) for item in items}
    )
    pending_issue_ids = [
        as_text(item.get("issue_id"))
        for item in items
        if as_text(item.get("trail_update_status")) == "pending"
    ]
    draft: dict[str, Any] = {
        "schema_version": TRAIL_ISSUE_DRAFT_SCHEMA,
        "mode": "direct_issue_ids",
        "write_mode": "info_only",
        "trail_write_enabled": bool(trail_write_enabled),
        "target_fields": [info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
        "comment_target_path": TRAIL_COMMENT_PATH,
        "merge_strategy": "deep_merge",
        "requested_issue_ids": list(issue_ids),
        "requested_entries": normalized_entries,
        "invalid_issue_ids": list(invalid_issue_ids or []),
        "missing_issue_ids": missing,
        "comment": normalized_comment,
        "comment_by_issue": {
            issue_id: supplied_comments.get(issue_id, supplied_comment) for issue_id in issue_ids
        },
        "items": items,
    }
    digest_draft = {
        **draft,
        "items": [
            {key: value for key, value in item.items() if key != "trail_update_status"}
            for item in items
        ],
    }
    digest = hashlib.sha256(canonical_json(digest_draft).encode("utf-8")).hexdigest()
    draft["payload_sha256"] = digest
    draft["operation_id"] = digest
    capability = dict(trail_capability or {
        "view_id": int(view_id),
        "target_fields": [info_field],
        "required_fields": [info_field],
        "fields_visible": [],
        "ready": False,
        "status": "not_checked",
        "message": "提交前检查 Trail view 字段。",
    })
    if not trail_write_enabled:
        write_status = "disabled"
    elif not capability.get("ready"):
        write_status = "fields_unavailable"
    elif invalid_issue_ids:
        write_status = "invalid_issue_ids"
    elif missing:
        write_status = "missing_issues"
    elif not items:
        write_status = "empty"
    elif not pending_issue_ids:
        write_status = "already_synced"
    else:
        write_status = "ready"
    return {
        "schema_version": TRAIL_ISSUE_DRAFT_SCHEMA,
        "mode": "direct_issue_ids",
        "write_mode": "info_only",
        "trail_write_enabled": bool(trail_write_enabled),
        "write_status": write_status,
        "write_ready": write_status == "ready",
        "target_fields": [info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
        "comment_target_path": TRAIL_COMMENT_PATH,
        "merge_strategy": "deep_merge",
        "count": len(items),
        "pending_count": len(pending_issue_ids),
        "pending_issue_ids": pending_issue_ids,
        "requested_issue_ids": list(issue_ids),
        "requested_entries": normalized_entries,
        "invalid_issue_ids": list(invalid_issue_ids or []),
        "missing_issue_ids": missing,
        "comment": normalized_comment,
        "comment_by_issue": {
            issue_id: supplied_comments.get(issue_id, supplied_comment) for issue_id in issue_ids
        },
        "payload_sha256": digest,
        "operation_id": digest,
        "items": items,
        "trail_update_status_summary": status_summary,
        "trail_capability": capability,
        "draft": draft,
    }
