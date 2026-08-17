"""Trail 属性更新：预览、字段能力检查与受控提交。

Review 的“应该排除”只会生成当前 Model Run 的候选项。真正写 Trail 之前
必须同时满足：目标 view 暴露 ``ra_stuck_auto_result`` 与
``ra_stuck_auto_result_info``、所有模型 label 都是三分类、请求来自已验证的
SSO 写入用户、以及客户端提交的 SHA-256 与服务端重新计算结果一致。

默认 writer 仍关闭。这样在现有 2410 view 只有 ``ra_result``/``ra_info`` 时，
页面会明确告知字段缺失，并且绝不会把新契约误写到旧字段。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from typing import Any

from fastapi import APIRouter, Request

from ..auth import has_same_origin_mutation_marker, identity_can_write, request_identity
from ..contracts import ISSUE_ID_RE
from ..http_support import (
    _as_text,
    _detail,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..runtime import database, settings
from ..trail_sync import read_trail_comment_markers, read_trail_model_fields
from ..trail_writer import (
    attach_trail_operation_id,
    build_manual_exclusion_changes,
    build_trail_changes,
    decorate_trail_comments,
    normalise_model_label,
    trail_operation_comment,
    verify_trail_readback,
    write_trail_model_results,
)

router = APIRouter()

TRAIL_RESULT_FIELD = "ra_stuck_auto_result"
TRAIL_INFO_FIELD = "ra_stuck_auto_result_info"
# Backward-compatible aliases used by older imports/tests.
TRAIL_TARGET_FIELD = TRAIL_INFO_FIELD
TRAIL_TARGET_PATH = "ra_triage_dashboard.should_exclude"
TRAIL_DRAFT_SCHEMA = "trail-attribute-update-v2"
TRAIL_ISSUE_DRAFT_SCHEMA = "trail-issue-exclusion-v1"
_commit_lock = threading.Lock()


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


def build_trail_attribute_update_payload(
    rows: list[dict[str, Any]],
    *,
    run: dict[str, Any],
    baseline_ids: list[str],
    baseline_scopes: list[str],
    result_field: str = TRAIL_RESULT_FIELD,
    info_field: str = TRAIL_INFO_FIELD,
    trail_capability: dict[str, Any] | None = None,
    trail_write_enabled: bool = False,
) -> dict[str, Any]:
    """Build a deterministic, Run-bound candidate payload.

    ``rows`` is already the latest Review projection for one immutable Run or
    the all-Run aggregate; filtering is repeated here so callers cannot
    accidentally include a non-excluded annotation. Invalid labels remain
    visible in preview but make the item and the whole payload non-write-ready.
    """

    run_id = _as_text(run.get("id"))
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
        if not label:
            invalid_labels.append(issue_id)
        patch = {
            "ra_triage_dashboard": {
                "schema_version": 2,
                "should_exclude": True,
                "model_run_id": source_run_id,
                "review_id": review_id,
                "reviewer": _as_text(annotation.get("author")),
                "reviewed_at": _as_text(annotation.get("created_at")),
                "model_label": label or raw_label,
                "model_reason": _as_text(prediction.get("reason")),
                "model_confidence": prediction.get("confidence"),
            }
        }
        items.append(
            {
                "issue_id": issue_id,
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
                "comment": _as_text(annotation.get("note"))[:4000],
                "write_ready": bool(label),
                "target": {
                    "field": info_field,
                    "result_field": result_field,
                    "path": TRAIL_TARGET_PATH,
                    "merge_strategy": "deep_merge",
                    "patch": patch,
                },
                "field_updates": {
                    result_field: label or raw_label,
                    info_field: patch,
                },
            }
        )
    items.sort(key=lambda item: item["issue_id"])
    draft: dict[str, Any] = {
        "schema_version": TRAIL_DRAFT_SCHEMA,
        "mode": "preview",
        "trail_write_enabled": bool(trail_write_enabled),
        "target_fields": [result_field, info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
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
    capability = trail_capability or _capability_not_checked(result_field, info_field)
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
        "target_fields": [result_field, info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
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


def build_trail_issue_exclusion_payload(
    issue_ids: list[str],
    *,
    current_rows: list[dict[str, Any]],
    invalid_issue_ids: list[str] | None = None,
    comment: str = "",
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
    normalized_comment = _as_text(comment).strip()[:4000]
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
        patch = {
            "ra_triage_dashboard": {
                "schema_version": 2,
                "should_exclude": True,
                "source": "manual_issue_ids",
            }
        }
        item: dict[str, Any] = {
            "issue_id": issue_id,
            "current_label": _as_text(current.get(TRAIL_RESULT_FIELD)),
            "current_should_exclude": bool(dashboard_info.get("should_exclude")),
            "target": {
                "field": info_field,
                "path": TRAIL_TARGET_PATH,
                "merge_strategy": "deep_merge",
                "patch": patch,
            },
            "comment": normalized_comment,
            "write_ready": True,
        }
        items.append(item)
    items.sort(key=lambda item: item["issue_id"])
    draft: dict[str, Any] = {
        "schema_version": TRAIL_ISSUE_DRAFT_SCHEMA,
        "mode": "direct_issue_ids",
        "trail_write_enabled": bool(trail_write_enabled),
        "target_fields": [info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
        "merge_strategy": "deep_merge",
        "requested_issue_ids": list(issue_ids),
        "invalid_issue_ids": list(invalid_issue_ids or []),
        "missing_issue_ids": missing,
        "comment": normalized_comment,
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
        "trail_write_enabled": bool(trail_write_enabled),
        "write_status": write_status,
        "write_ready": write_status == "ready",
        "target_fields": [info_field],
        "target_field": info_field,
        "target_path": TRAIL_TARGET_PATH,
        "merge_strategy": "deep_merge",
        "count": len(items),
        "requested_issue_ids": list(issue_ids),
        "invalid_issue_ids": list(invalid_issue_ids or []),
        "missing_issue_ids": missing,
        "comment": normalized_comment,
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
    issue_ids = [_as_text(row.get("issue_id")) for row in rows if _as_text(row.get("issue_id"))]
    if issue_ids:
        sync_result = await asyncio.to_thread(
            read_trail_model_fields,
            ra_root=settings.ra_auto_triage_root,
            issue_ids=issue_ids,
            view_id=settings.trail_view_id,
            chunk_size=settings.trail_sync_chunk_size,
        )
        capability = _capability_payload(sync_result, result_field, info_field)
    else:
        capability = _capability_not_checked(result_field, info_field)
    return await asyncio.to_thread(
        build_trail_attribute_update_payload,
        rows,
        run=run,
        baseline_ids=baseline_ids,
        baseline_scopes=baseline_scopes,
        result_field=result_field,
        info_field=info_field,
        trail_capability=capability,
        trail_write_enabled=settings.trail_attribute_write_enabled,
    )


async def _build_direct_preview(
    *,
    issue_ids: list[str],
    invalid_issue_ids: list[str] | None = None,
    comment: str = "",
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
    capability = _capability_for_required_field(sync_result, info_field)
    payload = await asyncio.to_thread(
        build_trail_issue_exclusion_payload,
        issue_ids,
        current_rows=sync_result.rows,
        invalid_issue_ids=invalid_issue_ids,
        comment=comment,
        info_field=info_field,
        trail_capability=capability,
        trail_write_enabled=settings.trail_attribute_write_enabled,
    )
    # The direct workflow does not update the model label, but the field is
    # retained in the capability response for operators comparing both tabs.
    payload["model_result_field"] = result_field
    return payload, sync_result


async def _comment_marker_preflight(
    *,
    issue_ids: list[str],
    operation_id: str,
) -> set[str]:
    """Return Issues whose exact operation Comment already exists.

    Comment writes are separate from ``multi_update`` and the legacy client
    does not expose an idempotency key.  Read the configured view first and
    fail closed when ``more_comment`` is unavailable, before changing fields.
    """

    if not issue_ids:
        return set()
    marker = trail_operation_comment("", operation_id)
    result = await asyncio.to_thread(
        read_trail_comment_markers,
        ra_root=settings.ra_auto_triage_root,
        issue_ids=issue_ids,
        view_id=settings.trail_view_id,
        chunk_size=settings.trail_sync_chunk_size,
        marker=marker,
    )
    if not result.complete:
        raise _detail(409, _as_text(result.message) or "Trail Comment 幂等检查失败。")
    return set(result.matched_issue_ids)


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


@router.get("/api/trail-attribute-update/preview")
async def trail_attribute_update_preview(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    """Return should-exclude rows for one Run or the all-Run aggregate."""

    return await _build_preview(
        request,
        selected_run_id=_as_text(model_run_id),
        baselines=baselines,
    )


@router.post("/api/trail-attribute-update/issue-preview")
async def trail_issue_exclusion_preview(request: Request) -> dict[str, Any]:
    """Preview direct Issue-ID shielding without contacting a write API."""

    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "预览内容不是合法 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "预览内容必须是 JSON 对象。")
    normalized_ids, invalid = _normalise_issue_ids(body.get("issue_ids", []))
    if not normalized_ids and not invalid:
        raise _detail(400, "请输入至少一个 Issue ID。")
    if len(normalized_ids) + len(invalid) > 200:
        raise _detail(400, "单次按 Issue ID 屏蔽最多支持 200 条。")
    payload, _sync_result = await _build_direct_preview(
        issue_ids=normalized_ids,
        invalid_issue_ids=invalid,
        comment=_as_text(body.get("comment")),
    )
    return payload


@router.post("/api/trail-attribute-update/commit")
async def trail_attribute_update_commit(request: Request) -> dict[str, Any]:
    """Commit an unchanged, field-validated preview to Trail in small chunks."""

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
        if not {result_field, info_field}.issubset(set(sync_result.fields_visible)):
            raise _detail(409, _as_text(sync_result.message) or "Trail 目标字段不可见。")
        changes = await asyncio.to_thread(
            build_trail_changes,
            preview.get("items", []),
            current_rows=sync_result.rows,
            result_field=result_field,
            info_field=info_field,
        )
        changes = attach_trail_operation_id(
            changes,
            operation_id=submitted_digest,
            info_field=info_field,
        )
        changes = decorate_trail_comments(changes, operation_id=submitted_digest)
        comment_issue_ids = [
            str(item.get("issue_id") or "").strip()
            for item in changes
            if str(item.get("comment") or "").strip()
        ]
        comment_skip_issue_ids = await _comment_marker_preflight(
            issue_ids=comment_issue_ids,
            operation_id=submitted_digest,
        )
        stats = await asyncio.to_thread(
            write_trail_model_results,
            changes,
            ra_root=settings.ra_auto_triage_root,
            chunk_size=settings.trail_attribute_write_chunk_size,
            write_comments_separately=True,
            comment_skip_issue_ids=comment_skip_issue_ids,
        )
        readback = await _readback_changes(
            changes,
            stats,
            result_field=result_field,
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
        "target_fields": [result_field, info_field],
        "stats": stats,
        "readback": readback,
    }


@router.post("/api/trail-attribute-update/issue-commit")
async def trail_issue_exclusion_commit(request: Request) -> dict[str, Any]:
    """Commit direct Issue-ID shielding through Trail multi_update + comments."""

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
    issue_ids, invalid = _normalise_issue_ids(body.get("issue_ids", []))
    if invalid:
        raise _detail(400, "提交内容包含无法识别的 Issue ID。")
    if not issue_ids:
        raise _detail(400, "提交内容缺少 Issue ID。")
    if len(issue_ids) > 200:
        raise _detail(400, "单次按 Issue ID 屏蔽最多支持 200 条。")
    comment = _as_text(body.get("comment")).strip()[:4000]
    submitted_digest = _as_text(body.get("payload_sha256"))
    if not submitted_digest:
        raise _detail(400, "提交内容缺少 payload_sha256。")
    with _commit_lock:
        preview, sync_result = await _build_direct_preview(
            issue_ids=issue_ids,
            comment=comment,
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
        _, info_field = _field_names()
        changes = await asyncio.to_thread(
            build_manual_exclusion_changes,
            issue_ids,
            current_rows=sync_result.rows,
            info_field=info_field,
            comment=comment,
        )
        changes = attach_trail_operation_id(
            changes,
            operation_id=submitted_digest,
            info_field=info_field,
        )
        changes = decorate_trail_comments(changes, operation_id=submitted_digest)
        comment_issue_ids = [
            str(item.get("issue_id") or "").strip()
            for item in changes
            if str(item.get("comment") or "").strip()
        ]
        comment_skip_issue_ids = await _comment_marker_preflight(
            issue_ids=comment_issue_ids,
            operation_id=submitted_digest,
        )
        stats = await asyncio.to_thread(
            write_trail_model_results,
            changes,
            ra_root=settings.ra_auto_triage_root,
            chunk_size=settings.trail_attribute_write_chunk_size,
            write_comments_separately=True,
            comment_skip_issue_ids=comment_skip_issue_ids,
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
    }
