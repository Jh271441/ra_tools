"""Trail 属性更新：预览、字段能力检查与受控提交。

Review 的“应该排除”只会生成当前 Model Run 的候选项。当前生产写入只更新
``ra_stuck_auto_result_info.ra_triage_dashboard.should_exclude``，保留模型
label 不变。真正写 Trail 之前必须满足目标 view 可完整定位 Issue、请求来自
已验证的 SSO 写入用户、以及客户端提交的 SHA-256 与服务端重新计算结果一致。

默认 writer 仍关闭。这样在现有 2410 view 只有 ``ra_result``/``ra_info`` 时，
页面会明确告知字段缺失，并且绝不会把新契约误写到旧字段。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Mapping

from fastapi import APIRouter, Request

from ..auth import has_same_origin_mutation_marker, identity_can_write, request_identity
from ..contracts import ISSUE_ID_RE
from ..db import REVIEW_STATUSES
from ..http_support import (
    _as_text,
    _detail,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..issue_tag_sources import HISTORICAL_EXCLUSION_SOURCE_KIND
from ..runtime import baseline_registry, database, issue_tag_sources, settings
from ..review_workflow import derive_review_status
from ..trail_sync import _dashboard_should_exclude, read_trail_model_fields
from ..trail_writer import (
    attach_trail_operation_id,
    build_manual_exclusion_changes,
    build_trail_changes,
    deep_merge_dict,
    normalise_model_label,
    verify_trail_readback,
    write_trail_model_results,
)

router = APIRouter()
logger = logging.getLogger("ra_triage_dashboard.trail_update")

TRAIL_RESULT_FIELD = "ra_stuck_auto_result"
TRAIL_INFO_FIELD = "ra_stuck_auto_result_info"
# Backward-compatible aliases used by older imports/tests.
TRAIL_TARGET_FIELD = TRAIL_INFO_FIELD
TRAIL_TARGET_PATH = "ra_triage_dashboard.should_exclude"
TRAIL_COMMENT_PATH = "ra_triage_dashboard.should_exclude_comment"
TRAIL_DRAFT_SCHEMA = "trail-attribute-update-v2"
TRAIL_ISSUE_DRAFT_SCHEMA = "trail-issue-exclusion-v2"
# A direct Issue-ID action must leave an auditable reason even when the
# operator does not type a custom note.  The model label remains untouched;
# both the marker and its explanation are written under the namespaced info
# field, not through Trail's separate Comment API.
TRAIL_ISSUE_EXCLUSION_COMMENT = (
    "问题排除：Issue ID 直接屏蔽（仅写入 should_exclude=true，模型 label 不变）。"
)
_HISTORICAL_EXCLUSION_SOURCE_FIELDS = (
    "kind",
    "source_id",
    "label",
    "baseline_id",
    "filename",
    "sha256",
    "row_number",
    "issue_id",
    "column",
    "value",
)
_commit_lock = threading.Lock()
_preview_capability_cache: dict[
    tuple[int, str, tuple[str, ...]],
    tuple[float, dict[str, Any], dict[str, str]],
] = {}
_preview_capability_cache_lock = threading.Lock()
_PREVIEW_CAPABILITY_CACHE_SECONDS = 90


def _append_historical_source_note(note: str, source_note: str) -> str:
    """Keep an existing Review note while making historical provenance visible."""

    current = _as_text(note).strip()
    source = _as_text(source_note).strip()
    if not source:
        return current[:4000]
    if source in current:
        return current[:4000]
    if not current:
        return source[:4000]
    # Preserve the provenance even for a previously max-length note.  The
    # original human note stays first and is clipped only as much as needed.
    available = max(0, 4000 - len(source) - 2)
    return f"{current[:available].rstrip()}\n\n{source}"[:4000]


def _mark_local_review_exclusions(
    issue_ids: list[str],
    *,
    actor: Any,
    fallback_note: str = "",
    fallback_notes: Mapping[str, str] | None = None,
    source_notes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Persist the direct shielding result into the Review exclusion flag.

    The Trail Issue-ID workflow is an issue-level action, but the Review page
    stores ``应该排除`` in its append-only annotation history.  Once Trail has
    been written and read back successfully, create a new annotation in the
    same Run as the latest Review for each Issue.  Existing expected output,
    Tags, missing evidence and note are copied unchanged; only
    ``is_excluded`` is forced to ``True``.  Repeating the same operation is
    idempotent when the latest annotation is already excluded.
    """

    normalized_ids = list(dict.fromkeys(
        str(issue_id or "").strip()
        for issue_id in issue_ids
        if str(issue_id or "").strip()
    ))
    result: dict[str, Any] = {
        "requested_count": len(normalized_ids),
        "marked_count": 0,
        "already_excluded_count": 0,
        # An Issue can exist in Trail but not belong to any baseline currently
        # loaded by this dashboard.  That is not a Trail write failure: retain
        # it separately so callers can describe the partial local sync without
        # incorrectly reporting the whole operation as failed.
        "not_in_dashboard_count": 0,
        "not_in_dashboard_issue_ids": [],
        "failed_count": 0,
        "failed_issue_ids": [],
        "failure_messages": {},
    }
    actor_name = _as_text(getattr(actor, "username", ""))
    actor_source = _as_text(getattr(actor, "source", "")) or "trail_attribute_update"
    actor_verified = bool(getattr(actor, "verified", False))
    normalized_fallback_note = _as_text(fallback_note).strip()[:4000]
    normalized_fallback_notes = {
        _as_text(issue_id).strip(): _as_text(note).strip()[:4000]
        for issue_id, note in (fallback_notes or {}).items()
        if _as_text(issue_id).strip()
    }
    normalized_source_notes = {
        _as_text(issue_id).strip(): _as_text(note).strip()[:4000]
        for issue_id, note in (source_notes or {}).items()
        if _as_text(issue_id).strip()
    }
    for issue_id in normalized_ids:
        try:
            case = database.get_case(issue_id)
            if case is None:
                result["not_in_dashboard_count"] += 1
                result["not_in_dashboard_issue_ids"].append(issue_id)
                continue
            annotations = [
                item for item in (case.get("annotations") or [])
                if isinstance(item, dict)
            ]
            current = annotations[0] if annotations else {}
            if bool(current.get("is_excluded")):
                result["already_excluded_count"] += 1
                continue
            expected_output = normalise_model_label(
                current.get("expected_output") or current.get("label")
            )
            current_review_status = _as_text(current.get("review_status"))
            review_status = (
                current_review_status
                if current_review_status in REVIEW_STATUSES
                else derive_review_status(expected_output, case.get("gt_label"))
            )
            previous_id = current.get("id")
            if previous_id not in (None, "", 0, "0"):
                previous_id = int(previous_id)
            else:
                previous_id = None
            database.create_annotation(
                issue_id=issue_id,
                model_run_id=_as_text(current.get("model_run_id")),
                label=expected_output,
                review_status=review_status,
                is_excluded=True,
                tags=list(current.get("tags") or []),
                missing_evidence=list(current.get("missing_evidence") or []),
                note=_append_historical_source_note(
                    _as_text(current.get("note"))
                    or normalized_fallback_notes.get(issue_id)
                    or normalized_fallback_note,
                    normalized_source_notes.get(issue_id, ""),
                ),
                author=actor_name,
                author_source=actor_source,
                author_verified=actor_verified,
                expected_previous_annotation_id=previous_id,
            )
            result["marked_count"] += 1
        except Exception as exc:
            result["failed_count"] += 1
            result["failed_issue_ids"].append(issue_id)
            result["failure_messages"][issue_id] = str(exc)[:240]
    result["ok"] = result["failed_count"] == 0
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _field_names() -> tuple[str, str]:
    return (
        _as_text(getattr(settings, "trail_attribute_result_field", "")) or TRAIL_RESULT_FIELD,
        _as_text(getattr(settings, "trail_attribute_info_field", "")) or TRAIL_INFO_FIELD,
    )


def _capability_not_checked(result_field: str, info_field: str) -> dict[str, Any]:
    return {
        "view_id": int(settings.trail_view_id),
        "target_fields": [result_field, info_field],
        "fields_visible": [],
        "ready": False,
        "status": "not_checked",
        "message": "生成候选项后检查 Trail view 字段。",
    }

def _capability_payload(sync_result: Any, result_field: str, info_field: str) -> dict[str, Any]:
    visible = sorted(str(item) for item in (sync_result.fields_visible or ()))
    required = {result_field, info_field}
    complete = bool(sync_result.complete)
    coverage_complete = int(sync_result.returned_issues) == int(sync_result.queried_issues)
    ready = required.issubset(set(visible)) and complete and coverage_complete
    if ready:
        status = "ready"
    elif not complete:
        status = "unavailable"
    elif not coverage_complete:
        status = "missing_issues"
    else:
        status = "missing_fields"
    message = _as_text(sync_result.message)
    if complete and not coverage_complete:
        message = (
            f"{message} Trail 仅返回 {sync_result.returned_issues}/"
            f"{sync_result.queried_issues} 条 Issue；为避免写入错误对象，本次不可提交。"
        )
    return {
        "view_id": int(sync_result.view_id),
        "target_fields": [result_field, info_field],
        "fields_visible": visible,
        "queried_issues": int(sync_result.queried_issues),
        "returned_issues": int(sync_result.returned_issues),
        "ready": ready,
        "status": status,
        "message": message,
    }


def _capability_for_required_field(
    sync_result: Any,
    required_field: str,
) -> dict[str, Any]:
    """Return a capability view for a workflow that only needs one field."""

    visible = sorted(str(item) for item in (sync_result.fields_visible or ()))
    ready = required_field in set(visible) and bool(sync_result.complete)
    if ready:
        status = "ready"
    elif not sync_result.complete:
        status = "unavailable"
    else:
        status = "missing_fields"
    return {
        "view_id": int(sync_result.view_id),
        "target_fields": [required_field],
        "required_fields": [required_field],
        "fields_visible": visible,
        "queried_issues": int(sync_result.queried_issues),
        "returned_issues": int(sync_result.returned_issues),
        "ready": ready,
        "status": status,
        "message": _as_text(sync_result.message),
    }


def _capability_for_info_write(sync_result: Any, info_field: str) -> dict[str, Any]:
    """Validate an info-only write without requiring a model-label column.

    Trail's view response omits empty custom columns for older Issues even
    when the update API accepts those fields.  For the Review aggregate we
    therefore require a complete, one-to-one Issue snapshot, but do not make
    the model label a prerequisite: the commit path only writes the info
    field and the response explicitly records that the label is untouched.
    """

    visible = sorted(str(item) for item in (sync_result.fields_visible or ()))
    complete = bool(sync_result.complete)
    coverage_complete = int(sync_result.returned_issues) == int(sync_result.queried_issues)
    if not complete:
        status = "unavailable"
        ready = False
        message = _as_text(sync_result.message)
    elif not coverage_complete:
        status = "missing_issues"
        ready = False
        message = (
            f"{_as_text(sync_result.message)} Trail 仅返回 "
            f"{sync_result.returned_issues}/{sync_result.queried_issues} 条 Issue；"
            "为避免写入错误对象，本次不可提交。"
        )
    else:
        status = "ready"
        ready = True
        if info_field in visible:
            message = _as_text(sync_result.message)
        else:
            message = (
                f"Trail view {sync_result.view_id} 未为当前旧 Issue 返回 {info_field}；"
                "本次仅通过 info-only 接口新增/合并该字段，不改模型 label，提交后会回读确认。"
            )
    return {
        "view_id": int(sync_result.view_id),
        "target_fields": [info_field],
        "required_fields": [info_field],
        "fields_visible": visible,
        "queried_issues": int(sync_result.queried_issues),
        "returned_issues": int(sync_result.returned_issues),
        "ready": ready,
        "status": status,
        "message": message,
    }


def _trail_update_statuses(
    sync_result: Any,
    issue_ids: list[str],
    *,
    info_field: str,
) -> dict[str, str]:
    """Project one batched Trail read into per-Issue update states.

    The status is intentionally derived from the same single batched read used
    for capability validation.  It never performs a follow-up request per
    Issue: a missing marker means the candidate is waiting to be synchronized,
    an explicit ``true`` marker means it is already synchronized, and a missing
    returned row is surfaced as ``not_found`` rather than being treated as a
    successful write.
    """

    normalized_ids = [str(issue_id or "").strip() for issue_id in issue_ids if str(issue_id or "").strip()]
    rows_by_issue = {
        _as_text(row.get("issue_id")): row
        for row in (getattr(sync_result, "rows", None) or [])
        if _as_text(row.get("issue_id"))
    }
    if not bool(getattr(sync_result, "complete", False)):
        return {issue_id: "query_failed" for issue_id in normalized_ids}
    statuses: dict[str, str] = {}
    for issue_id in normalized_ids:
        row = rows_by_issue.get(issue_id)
        if row is None:
            statuses[issue_id] = "not_found"
            continue
        statuses[issue_id] = (
            "synced"
            if _dashboard_should_exclude(row.get(info_field)) is True
            else "pending"
        )
    return statuses


def build_trail_attribute_update_payload(
    rows: list[dict[str, Any]],
    *,
    run: dict[str, Any],
    baseline_ids: list[str],
    baseline_scopes: list[str],
    result_field: str = TRAIL_RESULT_FIELD,
    info_field: str = TRAIL_INFO_FIELD,
    trail_capability: dict[str, Any] | None = None,
    trail_statuses: dict[str, str] | None = None,
    trail_write_enabled: bool = False,
    write_mode: str = "model_and_info",
) -> dict[str, Any]:
    """Build a deterministic, Run-bound candidate payload.

    ``rows`` is already the latest Review projection for one immutable Run or
    the all-Run aggregate; filtering is repeated here so callers cannot
    accidentally include a non-excluded annotation. Invalid labels remain
    visible in preview but make the item and the whole payload non-write-ready.
    """

    run_id = _as_text(run.get("id"))
    info_only = write_mode == "info_only"
    baseline_by_scope = {
        _as_text(scope): _as_text(baseline_ids[index])
        for index, scope in enumerate(baseline_scopes)
        if index < len(baseline_ids) and _as_text(scope) and _as_text(baseline_ids[index])
    }
    items: list[dict[str, Any]] = []
    invalid_labels: list[str] = []
    for row in rows:
        annotation = row.get("annotation") or {}
        prediction = row.get("prediction") or {}
        issue_id = _as_text(row.get("issue_id"))
        if not issue_id or not bool(annotation.get("is_excluded")):
            continue
        review_id = annotation.get("id")
        raw_label = _as_text(prediction.get("label"))
        label = normalise_model_label(raw_label)
        source_run_id = (
            _as_text(prediction.get("model_run_id"))
            or _as_text(annotation.get("model_run_id"))
            or run_id
        )
        if not label and not info_only:
            invalid_labels.append(issue_id)
        # Trail only needs Dashboard-owned fields.  Keep the operator's
        # explanation beside the exclusion marker in the same info JSON so
        # the update is atomic and does not create a separate Trail Comment.
        comment_text = _as_text(annotation.get("note"))[:4000]
        dashboard_patch: dict[str, Any] = {"should_exclude": True}
        if comment_text:
            dashboard_patch["should_exclude_comment"] = comment_text
        patch = {"ra_triage_dashboard": dashboard_patch}
        items.append(
            {
                "issue_id": issue_id,
                "baseline_id": baseline_by_scope.get(_as_text(row.get("baseline_scope")), ""),
                "baseline_scope": _as_text(row.get("baseline_scope")),
                "title": _as_text(row.get("title")),
                "scenario": _as_text(row.get("scenario")),
                "gt_label": _as_text(row.get("gt_label")),
                "model": {
                    "run_id": source_run_id,
                    "label": label or raw_label,
                    "reason": _as_text(prediction.get("reason")),
                    "confidence": prediction.get("confidence"),
                },
                "review": {
                    "id": review_id,
                    "model_run_id": source_run_id,
                    "status": _as_text(annotation.get("review_status")),
                    "reviewer": _as_text(annotation.get("author")),
                    "reviewed_at": _as_text(annotation.get("created_at")),
                    "note": _as_text(annotation.get("note")),
                    "tags": list(annotation.get("tags") or []),
                    "missing_evidence": list(annotation.get("missing_evidence") or []),
                    "is_excluded": True,
                },
                "comment": comment_text,
                # The current workflow is info-only, so a missing model label
                # does not make the marker write invalid.  Keep the strict
                # label gate for the legacy model+info mode.
                "write_ready": bool(label) or info_only,
                "trail_update_status": _as_text((trail_statuses or {}).get(issue_id))
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
                    else {
                        result_field: label or raw_label,
                        info_field: patch,
                    }
                ),
            }
        )
    items.sort(key=lambda item: item["issue_id"])
    status_summary: dict[str, int] = {}
    for item in items:
        status = _as_text(item.get("trail_update_status")) or "not_checked"
        status_summary[status] = status_summary.get(status, 0) + 1
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
                _as_text(item.get("model", {}).get("run_id"))
                for item in items
                if _as_text(item.get("model", {}).get("run_id"))
            }
        ),
        "model_run_name": _as_text(run.get("name")),
        "baseline_ids": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "items": items,
    }
    digest = hashlib.sha256(_canonical_json(draft).encode("utf-8")).hexdigest()
    draft["payload_sha256"] = digest
    draft["operation_id"] = digest
    capability = trail_capability or (
        {
            **_capability_not_checked(result_field, info_field),
            "target_fields": [info_field],
            "required_fields": [info_field],
        }
        if info_only
        else _capability_not_checked(result_field, info_field)
    )
    if not trail_write_enabled:
        write_status = "disabled"
    elif not capability.get("ready"):
        write_status = "fields_unavailable"
    elif invalid_labels:
        write_status = "invalid_labels"
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
            "name": _as_text(run.get("name")) or ("全部 Model Runs" if not run_id else ""),
            "source_name": _as_text(run.get("source_name")),
            "created_at": _as_text(run.get("created_at")),
            "all_runs": not bool(run_id),
        },
        "baselines": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "count": len(items),
        "invalid_label_issue_ids": invalid_labels,
        "payload_sha256": digest,
        "operation_id": digest,
        "trail_update_status_summary": status_summary,
        "items": items,
        "draft": draft,
    }


def _normalise_issue_ids(raw: Any) -> tuple[list[str], list[str]]:
    """Normalize a bounded direct Issue-ID request without accepting URLs."""

    values: list[Any]
    if isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = re.split(r"[\s,，、;；|]+", _as_text(raw))
    ids: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _as_text(value).strip()
        if not text:
            continue
        # Keep the endpoint deliberately strict: direct shielding should not
        # silently extract an ID from a pasted URL or arbitrary prose.
        if not ISSUE_ID_RE.fullmatch(text):
            invalid.append(text[:128])
            continue
        if text not in seen:
            seen.add(text)
            ids.append(text)
    return sorted(ids), invalid


def _normalise_issue_entries(
    raw: Any,
    *,
    fallback_comment: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize one Issue-ID/comment pair per editable row.

    The original API accepted ``issue_ids`` plus one shared ``comment``.  Keep
    that shape working for old clients, while allowing the UI to send
    ``entries=[{"issue_id": ..., "comment": ...}, ...]`` so every Issue can
    carry a different explanation in the namespaced Trail info JSON.
    """

    default_comment = _as_text(fallback_comment).strip()[:4000]
    if isinstance(raw, (list, tuple)):
        values: list[Any] = list(raw)
    elif isinstance(raw, dict):
        values = [raw]
    else:
        # A legacy string may contain comma/newline-separated IDs.  It has no
        # per-row note, so the optional shared comment applies to each one.
        values = re.split(r"[\s,，、;；|]+", _as_text(raw))

    entries: list[dict[str, Any]] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for value in values:
        source: dict[str, Any] | None = None
        if isinstance(value, Mapping):
            raw_issue_id = value.get("issue_id", value.get("id", ""))
            comment = _as_text(value.get("comment", value.get("note", default_comment))).strip()[:4000]
            raw_source = value.get("source")
            if raw_source is not None:
                if not isinstance(raw_source, Mapping):
                    issue_text = _as_text(raw_issue_id).strip() or "未填写 Issue ID"
                    invalid.append(f"{issue_text}（标注来源格式无效）")
                    continue
                source = dict(raw_source)
        else:
            raw_issue_id = value
            comment = default_comment
        issue_id = _as_text(raw_issue_id).strip()
        if not issue_id:
            continue
        if not ISSUE_ID_RE.fullmatch(issue_id):
            invalid.append(issue_id[:128])
            continue
        if issue_id in seen:
            invalid.append(f"{issue_id}（重复）")
            continue
        seen.add(issue_id)
        entry: dict[str, Any] = {"issue_id": issue_id, "comment": comment}
        if source is not None:
            entry["source"] = source
        entries.append(entry)
    entries.sort(key=lambda item: item["issue_id"])
    return entries, invalid


def _historical_source_payload(value: Any) -> dict[str, Any] | None:
    """Copy the bounded, server-verified provenance shape into public drafts."""

    if not isinstance(value, Mapping):
        return None
    if _as_text(value.get("kind")) != HISTORICAL_EXCLUSION_SOURCE_KIND:
        return None
    source: dict[str, Any] = {}
    for key in _HISTORICAL_EXCLUSION_SOURCE_FIELDS:
        raw = value.get(key)
        if key == "row_number":
            try:
                number = int(raw)
            except (TypeError, ValueError):
                return None
            if number < 1:
                return None
            source[key] = number
            continue
        text = _as_text(raw).strip()
        if not text:
            return None
        source[key] = text[:512]
    return source


def _resolve_historical_exclusion_entries(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Replace browser hints with the exact loaded-XLSX source and comment."""

    resolved: list[dict[str, Any]] = []
    invalid: list[str] = []
    for entry in entries:
        issue_id = _as_text(entry.get("issue_id")).strip()
        source = entry.get("source")
        if source is None:
            resolved.append(
                {"issue_id": issue_id, "comment": _as_text(entry.get("comment")).strip()[:4000]}
            )
            continue
        if not isinstance(source, Mapping):
            invalid.append(f"{issue_id}（历史抽检来源格式无效）")
            continue
        candidate = issue_tag_sources.resolve_exclusion_candidate(
            issue_id=issue_id,
            source=source,
        )
        if candidate is None:
            invalid.append(f"{issue_id}（历史抽检来源无效或已变化）")
            continue
        resolved_source = _historical_source_payload(candidate.get("source"))
        if resolved_source is None:
            # This is an internal contract failure.  Do not accept a source
            # record that cannot be represented in the signed preview.
            invalid.append(f"{issue_id}（历史抽检来源不可用）")
            continue
        resolved.append(
            {
                "issue_id": issue_id,
                "comment": _as_text(candidate.get("comment")).strip()[:4000],
                "source": resolved_source,
            }
        )
    resolved.sort(key=lambda item: item["issue_id"])
    return resolved, invalid


def build_trail_issue_exclusion_payload(
    issue_ids: list[str],
    *,
    current_rows: list[dict[str, Any]],
    invalid_issue_ids: list[str] | None = None,
    comment: str = "",
    comment_by_issue: Mapping[str, str] | None = None,
    requested_entries: list[dict[str, Any]] | None = None,
    baseline_by_issue: Mapping[str, Mapping[str, Any]] | None = None,
    info_field: str = TRAIL_INFO_FIELD,
    trail_capability: dict[str, Any] | None = None,
    trail_write_enabled: bool = False,
) -> dict[str, Any]:
    """Build a deterministic direct-Issue shielding preview.

    This workflow only writes ``ra_stuck_auto_result_info`` and preserves the
    existing model label.  Missing IDs are surfaced and make the draft
    non-write-ready; an operator must never infer that an unknown Issue was
    successfully shielded.
    """

    current_by_issue = {
        _as_text(row.get("issue_id")): row
        for row in current_rows
        if _as_text(row.get("issue_id"))
    }
    supplied_comment = _as_text(comment).strip()[:4000]
    supplied_comments = {
        _as_text(issue_id).strip(): _as_text(note).strip()[:4000]
        for issue_id, note in (comment_by_issue or {}).items()
        if _as_text(issue_id).strip()
    }
    if not supplied_comments and supplied_comment:
        supplied_comments = {issue_id: supplied_comment for issue_id in issue_ids}
    normalized_comment = supplied_comment or (
        next(iter(supplied_comments.values())) if len(set(supplied_comments.values())) == 1 else ""
    )
    if not normalized_comment and all(not note for note in supplied_comments.values()):
        # Preserve the legacy top-level summary for old clients/tests; each
        # item still carries its own effective default in the patch.
        normalized_comment = TRAIL_ISSUE_EXCLUSION_COMMENT
    normalized_entries: list[dict[str, Any]] = []
    for item in requested_entries or []:
        issue_id = _as_text(item.get("issue_id")).strip()
        if not issue_id:
            continue
        entry: dict[str, Any] = {
            "issue_id": issue_id,
            "comment": _as_text(item.get("comment")).strip()[:4000],
        }
        source = _historical_source_payload(item.get("source"))
        if source is not None:
            entry["source"] = source
        normalized_entries.append(entry)
    # Keep the structured request self-contained when this helper is called
    # directly (rather than through the HTTP route, which supplies both
    # ``requested_entries`` and ``comment_by_issue``).  The row value is the
    # most specific source of truth; the legacy shared comment remains the
    # fallback for old callers.
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
        dashboard_info = current_info.get("ra_triage_dashboard")
        if not isinstance(dashboard_info, dict):
            dashboard_info = {}
        supplied_item_comment = supplied_comments.get(issue_id, supplied_comment)
        comment_defaulted = not bool(supplied_item_comment)
        normalized_item_comment = supplied_item_comment or TRAIL_ISSUE_EXCLUSION_COMMENT
        patch = {
            "ra_triage_dashboard": {
                "should_exclude": True,
                "should_exclude_comment": normalized_item_comment,
            }
        }
        merged_info = deep_merge_dict(current_info, patch)
        item: dict[str, Any] = {
            "issue_id": issue_id,
            "baseline_id": _as_text((release_by_issue.get(issue_id) or {}).get("baseline_id")),
            "baseline_scope": _as_text((release_by_issue.get(issue_id) or {}).get("baseline_scope")),
            "current_label": _as_text(current.get(TRAIL_RESULT_FIELD)),
            "current_should_exclude": bool(dashboard_info.get("should_exclude")),
            # Keep the exact before/after object in the preview contract so
            # the operator can see what the production write will preserve
            # and what it will add.  The direct workflow never includes the
            # model label in its field update.
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
            issue_id: supplied_comments.get(issue_id, supplied_comment)
            for issue_id in issue_ids
        },
        "items": items,
    }
    digest = hashlib.sha256(_canonical_json(draft).encode("utf-8")).hexdigest()
    draft["payload_sha256"] = digest
    draft["operation_id"] = digest
    capability = trail_capability or {
        "view_id": int(settings.trail_view_id),
        "target_fields": [info_field],
        "required_fields": [info_field],
        "fields_visible": [],
        "ready": False,
        "status": "not_checked",
        "message": "提交前检查 Trail view 字段。",
    }
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
        "requested_issue_ids": list(issue_ids),
        "requested_entries": normalized_entries,
        "invalid_issue_ids": list(invalid_issue_ids or []),
        "missing_issue_ids": missing,
        "comment": normalized_comment,
        "comment_by_issue": {
            issue_id: supplied_comments.get(issue_id, supplied_comment)
            for issue_id in issue_ids
        },
        "payload_sha256": digest,
        "operation_id": digest,
        "items": items,
        "trail_capability": capability,
        "draft": draft,
    }


async def _build_preview(
    request: Request,
    *,
    selected_run_id: str,
    baselines: str = "",
    probe_trail: bool = True,
    refresh_trail: bool = False,
) -> dict[str, Any]:
    baseline_ids = resolve_request_baseline_ids(baselines, request=request)
    baseline_scopes = resolve_request_baseline_scopes(baselines, request=request)
    if selected_run_id:
        run = await asyncio.to_thread(database.get_model_run, selected_run_id)
    else:
        run = {"id": "", "name": "全部 Model Runs", "source_name": ""}
    if selected_run_id and run is None:
        raise _detail(404, "模型 Run 不存在，无法生成 Trail 属性更新预览。")
    rows = await asyncio.to_thread(
        database.review_reason_rows,
        baseline_scopes=baseline_scopes,
        model_run_id=selected_run_id,
        comparison_status="all",
        is_excluded=True,
    )
    result_field, info_field = _field_names()
    review_write_enabled = bool(
        settings.trail_attribute_write_enabled
        and getattr(settings, "trail_attribute_review_write_enabled", False)
    )
    issue_ids = [_as_text(row.get("issue_id")) for row in rows if _as_text(row.get("issue_id"))]
    # Trail status is a read-only projection and is useful even when the
    # controlled writer is disabled. Keep the first local paint cheap, then
    # perform one batched read when the caller explicitly asks for it.
    trail_statuses: dict[str, str] | None = None
    if issue_ids and probe_trail:
        # Capability probing is a remote read and is the slowest part of the
        # page preview.  Cache only this short-lived, Issue-set-specific
        # summary; the actual commit path always bypasses the cache and does a
        # fresh read immediately before writing.
        cache_key = (int(settings.trail_view_id), info_field, tuple(issue_ids))
        cached_capability = None
        if request.method.upper() == "GET" and not refresh_trail:
            now = time.monotonic()
            with _preview_capability_cache_lock:
                cached = _preview_capability_cache.get(cache_key)
                if cached and now - cached[0] < _PREVIEW_CAPABILITY_CACHE_SECONDS:
                    cached_capability = dict(cached[1])
                    trail_statuses = dict(cached[2])
        if cached_capability is not None:
            capability = cached_capability
            capability["cached"] = True
        else:
            sync_result = await asyncio.to_thread(
                read_trail_model_fields,
                ra_root=settings.ra_auto_triage_root,
                issue_ids=issue_ids,
                view_id=settings.trail_view_id,
                chunk_size=settings.trail_sync_chunk_size,
            )
            capability = _capability_for_info_write(sync_result, info_field)
            trail_statuses = _trail_update_statuses(
                sync_result,
                issue_ids,
                info_field=info_field,
            )
            if request.method.upper() == "GET" and not refresh_trail:
                with _preview_capability_cache_lock:
                    _preview_capability_cache[cache_key] = (
                        time.monotonic(),
                        dict(capability),
                        dict(trail_statuses),
                    )
    else:
        capability = _capability_not_checked(result_field, info_field)
        capability["target_fields"] = [info_field]
        capability["required_fields"] = [info_field]
        # The first-paint request is intentionally still waiting for the
        # background probe. Keep rows in “查询中” until that single batched
        # read returns, regardless of whether writing is enabled.
        if not (issue_ids and not probe_trail):
            trail_statuses = {}
    payload = await asyncio.to_thread(
        build_trail_attribute_update_payload,
        rows,
        run=run,
        baseline_ids=baseline_ids,
        baseline_scopes=baseline_scopes,
        result_field=result_field,
        info_field=info_field,
        trail_capability=capability,
        trail_statuses=trail_statuses,
        trail_write_enabled=review_write_enabled,
        write_mode="info_only",
    )
    # The first page request deliberately skips the remote Trail capability
    # read so the local Review aggregate can paint immediately.  The browser
    # follows it with the checked request in the background and replaces the
    # payload before enabling a possible commit.
    payload["capability_pending"] = bool(issue_ids and not probe_trail)
    return payload


async def _build_direct_preview(
    *,
    issue_ids: list[str],
    invalid_issue_ids: list[str] | None = None,
    comment: str = "",
    comment_by_issue: Mapping[str, str] | None = None,
    requested_entries: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], Any]:
    """Read target fields and build the direct Issue-ID draft."""

    result_field, info_field = _field_names()
    sync_result = await asyncio.to_thread(
        read_trail_model_fields,
        ra_root=settings.ra_auto_triage_root,
        issue_ids=issue_ids,
        view_id=settings.trail_view_id,
        chunk_size=settings.trail_sync_chunk_size,
    )
    capability = _capability_for_info_write(sync_result, info_field)
    baseline_scopes = await asyncio.to_thread(
        database.issue_baseline_scopes,
        issue_ids,
    )
    baseline_by_issue = {
        issue_id: {
            "baseline_scope": scope,
            "baseline_id": baseline_registry.scope_to_id(scope) or "",
        }
        for issue_id, scope in baseline_scopes.items()
    }
    payload = await asyncio.to_thread(
        build_trail_issue_exclusion_payload,
        issue_ids,
        current_rows=sync_result.rows,
        invalid_issue_ids=invalid_issue_ids,
        comment=comment,
        comment_by_issue=comment_by_issue,
        requested_entries=requested_entries,
        baseline_by_issue=baseline_by_issue,
        info_field=info_field,
        trail_capability=capability,
        trail_write_enabled=settings.trail_attribute_write_enabled,
    )
    # The direct workflow does not update the model label, but the field is
    # retained in the capability response for operators comparing both tabs.
    payload["model_result_field"] = result_field
    return payload, sync_result


async def _readback_changes(
    changes: list[dict[str, Any]],
    stats: dict[str, Any],
    *,
    result_field: str,
    info_field: str,
) -> dict[str, Any]:
    """Read back every field-successful Issue and verify the owned markers."""

    failed = {str(item).strip() for item in stats.get("failed_issue_ids", []) if str(item).strip()}
    successful = [item for item in changes if str(item.get("issue_id") or "").strip() not in failed]
    issue_ids = [str(item.get("issue_id") or "").strip() for item in successful if str(item.get("issue_id") or "").strip()]
    if not issue_ids:
        return {
            "complete": True,
            "ok": True,
            "checked_count": 0,
            "verified_count": 0,
            "missing_issue_ids": [],
            "mismatched_issue_ids": [],
            "message": "没有字段成功项需要回读。",
        }
    result = await asyncio.to_thread(
        read_trail_model_fields,
        ra_root=settings.ra_auto_triage_root,
        issue_ids=issue_ids,
        view_id=settings.trail_view_id,
        chunk_size=settings.trail_sync_chunk_size,
    )
    verification = verify_trail_readback(
        successful,
        result.rows,
        result_field=result_field,
        info_field=info_field,
    )
    verification.update(
        {
            "complete": bool(result.complete),
            "ok": bool(result.complete and verification.get("ok")),
            "message": _as_text(result.message),
            "fields_visible": list(result.fields_visible),
        }
    )
    return verification


async def _save_issue_exclusion_history(
    *,
    operation_id: str,
    identity: Any,
    status: str,
    requested_entries: list[dict[str, Any]],
    synced_issue_ids: set[str] | None = None,
    failed_issue_ids: set[str] | None = None,
    external_only_issue_ids: set[str] | None = None,
    failure_messages: Mapping[str, str] | None = None,
    message: str = "",
) -> None:
    """Best-effort audit persistence for the direct Issue-ID workflow."""

    failures = failure_messages or {}
    synced = {
        str(item).strip()
        for item in (synced_issue_ids or set())
        if str(item).strip()
    }
    failed = {
        str(item).strip()
        for item in (failed_issue_ids or set())
        if str(item).strip()
    }
    external_only = {
        str(item).strip()
        for item in (external_only_issue_ids or set())
        if str(item).strip()
    }
    entries: list[dict[str, Any]] = []
    for item in requested_entries:
        issue_id = _as_text(item.get("issue_id")).strip()
        if not issue_id:
            continue
        if issue_id in failed:
            item_status = "failed"
            detail = _as_text(failures.get(issue_id)) or "Trail 写入、回读或本地看板同步失败。"
        elif issue_id in external_only:
            item_status = "trail_synced_not_in_dashboard"
            detail = "Trail 回读确认成功；该 Issue 不在当前看板数据集，未创建本地 Review 排除标记。"
        elif issue_id in synced:
            item_status = "synced"
            detail = "Trail 回读确认成功。"
        else:
            item_status = "pending" if status == "pending" else "unknown"
            detail = "等待提交结果。" if status == "pending" else "未返回明确结果。"
        entry = {
            "issue_id": issue_id,
            "comment": _as_text(item.get("comment")).strip()[:4000],
            "status": item_status,
            "detail": detail[:1000],
        }
        source = _historical_source_payload(item.get("source"))
        if source is not None:
            entry["source"] = source
        entries.append(entry)
    actor = {
        "username": _as_text(getattr(identity, "username", "")),
        "source": _as_text(getattr(identity, "source", "")),
        "verified": bool(getattr(identity, "verified", False)),
    }
    try:
        await asyncio.to_thread(
            database.upsert_trail_issue_exclusion_history,
            operation_id=operation_id,
            actor=actor["username"],
            actor_source=actor["source"],
            actor_verified=actor["verified"],
            status=status,
            requested_count=len(entries),
            synced_count=len(synced),
            failed_count=len(failed),
            entries=entries,
            message=message,
        )
    except Exception:  # pragma: no cover - audit must not block a Trail write
        logger.exception("Unable to persist Issue-ID shielding history")


@router.get("/api/trail-attribute-update/preview")
async def trail_attribute_update_preview(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
    probe_trail: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return should-exclude rows for one Run or the all-Run aggregate."""

    return await _build_preview(
        request,
        selected_run_id=_as_text(model_run_id),
        baselines=baselines,
        probe_trail=probe_trail,
        refresh_trail=refresh,
    )


@router.get("/api/trail-attribute-update/issue-history")
async def trail_issue_exclusion_history(
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List recent Issue-ID shielding submissions without contacting Trail."""

    return await asyncio.to_thread(
        database.list_trail_issue_exclusion_history,
        limit=max(1, min(int(limit), 100)),
        offset=max(0, int(offset)),
    )


@router.get("/api/trail-attribute-update/historical-exclusions")
async def trail_historical_exclusions(
    request: Request,
    baselines: str = "",
) -> dict[str, Any]:
    """Return read-only XLSX exclusion candidates for the selected baselines.

    Loading this list does not create a Review and does not contact Trail.  A
    user still has to build a preview and explicitly confirm a write.
    """

    baseline_ids = resolve_request_baseline_ids(baselines, request=request)
    items = await asyncio.to_thread(
        issue_tag_sources.exclusion_candidates,
        baseline_ids=baseline_ids,
    )
    return {
        "schema_version": "historical-exclusion-source-v1",
        "mode": "historical_spotcheck_xlsx",
        "baselines": baseline_ids,
        "count": len(items),
        "items": items,
    }


@router.post("/api/trail-attribute-update/issue-preview")
async def trail_issue_exclusion_preview(request: Request) -> dict[str, Any]:
    """Preview direct Issue-ID shielding without contacting a write API."""

    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "预览内容不是合法 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "预览内容必须是 JSON 对象。")
    fallback_comment = _as_text(body.get("comment"))
    raw_entries = body.get("entries") if "entries" in body else body.get("issue_ids", [])
    normalized_entries, invalid = _normalise_issue_entries(
        raw_entries,
        fallback_comment=fallback_comment,
    )
    normalized_entries, source_invalid = _resolve_historical_exclusion_entries(
        normalized_entries
    )
    invalid.extend(source_invalid)
    normalized_ids = [item["issue_id"] for item in normalized_entries]
    if not normalized_ids and not invalid:
        raise _detail(400, "请输入至少一个 Issue ID。")
    if len(normalized_entries) + len(invalid) > 200:
        raise _detail(400, "单次按 Issue ID 屏蔽最多支持 200 条。")
    comment_by_issue = {item["issue_id"]: item["comment"] for item in normalized_entries}
    payload, _sync_result = await _build_direct_preview(
        issue_ids=normalized_ids,
        invalid_issue_ids=invalid,
        comment=fallback_comment,
        comment_by_issue=comment_by_issue,
        requested_entries=normalized_entries,
    )
    return payload


@router.post("/api/trail-attribute-update/commit")
async def trail_attribute_update_commit(request: Request) -> dict[str, Any]:
    """Commit an unchanged, field-validated preview to Trail in small chunks."""

    if not settings.trail_attribute_write_enabled:
        raise _detail(409, "Trail 属性写入开关尚未开启；当前仅允许预览和下载草稿。")
    if not getattr(settings, "trail_attribute_review_write_enabled", False):
        raise _detail(409, "Review 汇总写入已关闭；当前仅允许 Issue ID info-only 写入。")
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, "缺少同源写请求标记。")
    identity = await asyncio.to_thread(request_identity, request, settings)
    if not identity_can_write(identity, settings):
        raise _detail(403, "Trail 属性更新需要已验证的 SSO 写入权限。")
    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "提交内容不是合法 JSON。") from exc
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise _detail(400, "提交 Trail 更新前必须明确 confirm=true。")
    run_id = _as_text(body.get("model_run_id"))
    submitted_digest = _as_text(body.get("payload_sha256"))
    if not submitted_digest:
        raise _detail(400, "提交内容缺少 payload_sha256。")
    raw_baselines = body.get("baselines", "")
    if isinstance(raw_baselines, list):
        baseline_query = ",".join(_as_text(item) for item in raw_baselines if _as_text(item))
    else:
        baseline_query = _as_text(raw_baselines)
    # Serialize commits in this process.  The digest check below still makes
    # a stale browser preview fail closed across workers/processes.
    with _commit_lock:
        preview = await _build_preview(
            request,
            selected_run_id=run_id,
            baselines=baseline_query,
        )
        if submitted_digest != _as_text(preview.get("payload_sha256")):
            raise _detail(409, "预览已过期或内容发生变化，请重新生成后再提交。")
        if not preview.get("write_ready"):
            capability = preview.get("trail_capability") or {}
            message = _as_text(capability.get("message")) or "目标字段不可写。"
            raise _detail(409, f"Trail 属性更新未就绪：{message}")
        result_field, info_field = _field_names()
        sync_result = await asyncio.to_thread(
            read_trail_model_fields,
            ra_root=settings.ra_auto_triage_root,
            issue_ids=[_as_text(item.get("issue_id")) for item in preview.get("items", [])],
            view_id=settings.trail_view_id,
            chunk_size=settings.trail_sync_chunk_size,
        )
        if (
            not sync_result.complete
            or int(sync_result.returned_issues) != int(sync_result.queried_issues)
        ):
            raise _detail(409, _as_text(sync_result.message) or "Trail Issue 回读不完整。")
        changes = await asyncio.to_thread(
            build_trail_changes,
            preview.get("items", []),
            current_rows=sync_result.rows,
            result_field=result_field,
            info_field=info_field,
            write_result_field=False,
        )
        # Keep retries idempotent inside the same JSON info namespace.  No
        # separate Trail Comment request is made.
        changes = attach_trail_operation_id(changes, operation_id=submitted_digest)
        stats = await asyncio.to_thread(
            write_trail_model_results,
            changes,
            ra_root=settings.ra_auto_triage_root,
            chunk_size=settings.trail_attribute_write_chunk_size,
        )
        readback = await _readback_changes(
            changes,
            stats,
            result_field="",
            info_field=info_field,
        )
    return {
        "ok": (
            not stats.get("failed_count")
            and not stats.get("comment_failed_count")
            and bool(readback.get("ok"))
        ),
        "mode": "commit",
        "payload_sha256": submitted_digest,
        "model_run_id": run_id,
        "actor": {
            "username": identity.username,
            "source": identity.source,
            "verified": identity.verified,
        },
        "write_mode": "info_only",
        "model_result_field": result_field,
        "target_fields": [info_field],
        "stats": stats,
        "readback": readback,
    }


@router.post("/api/trail-attribute-update/issue-commit")
async def trail_issue_exclusion_commit(request: Request) -> dict[str, Any]:
    """Commit direct Issue-ID shielding through the info JSON field."""

    if not settings.trail_attribute_write_enabled:
        raise _detail(409, "Trail 属性写入开关尚未开启；当前仅允许预览和下载草稿。")
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, "缺少同源写请求标记。")
    identity = await asyncio.to_thread(request_identity, request, settings)
    if not identity_can_write(identity, settings):
        raise _detail(403, "Trail 属性更新需要已验证的 SSO 写入权限。")
    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "提交内容不是合法 JSON。") from exc
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise _detail(400, "提交 Trail 更新前必须明确 confirm=true。")
    fallback_comment = _as_text(body.get("comment"))
    raw_entries = body.get("entries") if "entries" in body else body.get("issue_ids", [])
    requested_entries, invalid = _normalise_issue_entries(
        raw_entries,
        fallback_comment=fallback_comment,
    )
    requested_entries, source_invalid = _resolve_historical_exclusion_entries(
        requested_entries
    )
    invalid.extend(source_invalid)
    issue_ids = [item["issue_id"] for item in requested_entries]
    if invalid:
        raise _detail(400, "提交内容包含无法识别的 Issue ID。")
    if not issue_ids:
        raise _detail(400, "提交内容缺少 Issue ID。")
    if len(issue_ids) > 200:
        raise _detail(400, "单次按 Issue ID 屏蔽最多支持 200 条。")
    comment_by_issue = {item["issue_id"]: item["comment"] for item in requested_entries}
    submitted_digest = _as_text(body.get("payload_sha256"))
    if not submitted_digest:
        raise _detail(400, "提交内容缺少 payload_sha256。")
    with _commit_lock:
        preview, sync_result = await _build_direct_preview(
            issue_ids=issue_ids,
            comment=fallback_comment,
            comment_by_issue=comment_by_issue,
            requested_entries=requested_entries,
        )
        if submitted_digest != _as_text(preview.get("payload_sha256")):
            raise _detail(409, "预览已过期或内容发生变化，请重新生成后再提交。")
        if not preview.get("write_ready"):
            capability = preview.get("trail_capability") or {}
            detail = _as_text(capability.get("message")) or "目标字段不可写。"
            missing = preview.get("missing_issue_ids") or []
            if missing:
                detail = f"{detail} 未找到 Issue: {', '.join(str(item) for item in missing[:8])}"
            raise _detail(409, f"Issue ID 屏蔽未就绪：{detail}")
        # The preview contract normalizes an empty row note to an auditable
        # default.  Reuse each item's exact value for the info JSON field and
        # local Review annotation; no separate Trail Comment is written.
        effective_comments = {
            _as_text(item.get("issue_id")).strip(): _as_text(item.get("comment")).strip()[:4000]
            for item in (preview.get("items") or [])
            if _as_text(item.get("issue_id")).strip()
        }
        source_by_issue = {
            _as_text(item.get("issue_id")).strip(): _historical_source_payload(
                item.get("source")
            )
            for item in (preview.get("requested_entries") or [])
            if _as_text(item.get("issue_id")).strip()
            and _historical_source_payload(item.get("source")) is not None
        }
        source_notes = {
            issue_id: effective_comments.get(issue_id, "")
            for issue_id in source_by_issue
        }
        history_entries = [
            {
                "issue_id": issue_id,
                "comment": effective_comments.get(issue_id, ""),
                **(
                    {"source": source_by_issue[issue_id]}
                    if issue_id in source_by_issue
                    else {}
                ),
            }
            for issue_id in issue_ids
        ]
        await _save_issue_exclusion_history(
            operation_id=submitted_digest,
            identity=identity,
            status="pending",
            requested_entries=history_entries,
            message="已生成待提交记录，等待 Trail 写入和回读。",
        )
        _, info_field = _field_names()
        try:
            changes = await asyncio.to_thread(
                build_manual_exclusion_changes,
                issue_ids,
                current_rows=sync_result.rows,
                info_field=info_field,
                comment_by_issue=effective_comments,
            )
            changes = attach_trail_operation_id(changes, operation_id=submitted_digest)
            stats = await asyncio.to_thread(
                write_trail_model_results,
                changes,
                ra_root=settings.ra_auto_triage_root,
                chunk_size=settings.trail_attribute_write_chunk_size,
            )
            readback = await _readback_changes(
                changes,
                stats,
                result_field="",
                info_field=info_field,
            )
            field_failed = {
                str(item).strip()
                for item in stats.get("failed_issue_ids", [])
                if str(item).strip()
            }
            readback_failed = {
                str(item).strip()
                for item in (
                    list(readback.get("missing_issue_ids", []))
                    + list(readback.get("mismatched_issue_ids", []))
                )
                if str(item).strip()
            }
            verified_issue_ids = [
                str(item.get("issue_id") or "").strip()
                for item in changes
                if str(item.get("issue_id") or "").strip()
                and str(item.get("issue_id") or "").strip() not in field_failed
                and str(item.get("issue_id") or "").strip() not in readback_failed
            ]
            local_review = (
                await asyncio.to_thread(
                    _mark_local_review_exclusions,
                    verified_issue_ids,
                    actor=identity,
                    fallback_notes=effective_comments,
                    source_notes=source_notes,
                )
                if readback.get("complete")
                else {
                    "requested_count": 0,
                    "marked_count": 0,
                    "already_excluded_count": 0,
                    "not_in_dashboard_count": 0,
                    "not_in_dashboard_issue_ids": [],
                    "failed_count": 0,
                    "failed_issue_ids": [],
                    "failure_messages": {},
                    "ok": False,
                    "status": "readback_incomplete",
                }
            )
        except Exception as exc:
            await _save_issue_exclusion_history(
                operation_id=submitted_digest,
                identity=identity,
                status="failed",
                requested_entries=history_entries,
                failed_issue_ids=set(issue_ids),
                message=f"提交异常：{str(exc)[:1000]}",
            )
            raise
        failed_issue_ids = field_failed | readback_failed
        local_failed_issue_ids = {
            str(item).strip()
            for item in local_review.get("failed_issue_ids", [])
            if str(item).strip()
        }
        not_in_dashboard_issue_ids = {
            str(item).strip()
            for item in local_review.get("not_in_dashboard_issue_ids", [])
            if str(item).strip()
        }
        trail_ok = (
            not stats.get("failed_count")
            and not stats.get("comment_failed_count")
            and bool(readback.get("ok"))
        )
        history_status = (
            "completed"
            if not failed_issue_ids and not local_failed_issue_ids
            else "partial" if verified_issue_ids else "failed"
        )
        history_message = (
            f"Trail 回读 {len(verified_issue_ids)}/{len(changes)} 条成功。"
            if readback.get("complete")
            else "Trail 回读不完整，未同步本地 Review 排除状态。"
        )
        if not_in_dashboard_issue_ids:
            history_message += (
                f" 其中 {len(not_in_dashboard_issue_ids)} 条不在当前看板数据集，"
                "未创建本地 Review 排除标记。"
            )
        if local_failed_issue_ids:
            history_message += (
                f" 本地 Review 排除标记失败 {len(local_failed_issue_ids)} 条。"
            )
        await _save_issue_exclusion_history(
            operation_id=submitted_digest,
            identity=identity,
            status=history_status,
            requested_entries=history_entries,
            synced_issue_ids=set(verified_issue_ids),
            failed_issue_ids=failed_issue_ids | local_failed_issue_ids,
            external_only_issue_ids=not_in_dashboard_issue_ids,
            failure_messages={
                **{
                    issue_id: "Trail 字段写入失败。"
                    for issue_id in field_failed
                },
                **{
                    issue_id: "Trail 回读校验失败。"
                    for issue_id in readback_failed
                },
                **{
                    issue_id: _as_text(
                        (local_review.get("failure_messages") or {}).get(issue_id)
                    ) or "本地 Review 排除标记失败。"
                    for issue_id in local_failed_issue_ids
                },
            },
            message=history_message,
        )
    return {
        # ``ok`` is the Trail write contract.  A Trail-only Issue is already
        # correctly updated and should not make the operator retry it simply
        # because the dashboard has no local case to annotate.
        "ok": trail_ok,
        "trail_ok": trail_ok,
        "local_review_ok": bool(local_review.get("ok")),
        "local_dashboard_sync_partial": bool(
            not_in_dashboard_issue_ids or local_failed_issue_ids
        ),
        "mode": "direct_issue_ids",
        "payload_sha256": submitted_digest,
        "actor": {
            "username": identity.username,
            "source": identity.source,
            "verified": identity.verified,
        },
        "target_fields": [info_field],
        "target_path": TRAIL_TARGET_PATH,
        "stats": stats,
        "readback": readback,
        "local_review": local_review,
    }
