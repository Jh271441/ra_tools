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
import threading
from typing import Any

from fastapi import APIRouter, Request

from ..auth import identity_can_write, request_identity
from ..http_support import (
    _as_text,
    _detail,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..runtime import database, settings
from ..trail_sync import read_trail_model_fields
from ..trail_writer import build_trail_changes, normalise_model_label, write_trail_model_results

router = APIRouter()

TRAIL_RESULT_FIELD = "ra_stuck_auto_result"
TRAIL_INFO_FIELD = "ra_stuck_auto_result_info"
# Backward-compatible aliases used by older imports/tests.
TRAIL_TARGET_FIELD = TRAIL_INFO_FIELD
TRAIL_TARGET_PATH = "ra_triage_dashboard.should_exclude"
TRAIL_DRAFT_SCHEMA = "trail-attribute-update-v2"
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
    ready = required.issubset(set(visible)) and bool(sync_result.complete)
    if ready:
        status = "ready"
    elif not sync_result.complete:
        status = "unavailable"
    else:
        status = "missing_fields"
    return {
        "view_id": int(sync_result.view_id),
        "target_fields": [result_field, info_field],
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

    ``rows`` is already the latest Review projection for one immutable Run;
    filtering is repeated here so callers cannot accidentally include a
    non-excluded annotation.  Invalid labels remain visible in preview but
    make the item and the whole payload non-write-ready.
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
        if not label:
            invalid_labels.append(issue_id)
        patch = {
            "ra_triage_dashboard": {
                "schema_version": 2,
                "should_exclude": True,
                "model_run_id": run_id,
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
                    "run_id": _as_text(prediction.get("model_run_id") or run_id),
                    "label": label or raw_label,
                    "reason": _as_text(prediction.get("reason")),
                    "confidence": prediction.get("confidence"),
                },
                "review": {
                    "id": review_id,
                    "model_run_id": _as_text(annotation.get("model_run_id") or run_id),
                    "status": _as_text(annotation.get("review_status")),
                    "reviewer": _as_text(annotation.get("author")),
                    "reviewed_at": _as_text(annotation.get("created_at")),
                    "note": _as_text(annotation.get("note")),
                    "tags": list(annotation.get("tags") or []),
                    "missing_evidence": list(annotation.get("missing_evidence") or []),
                    "is_excluded": True,
                },
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
        "model_run_name": _as_text(run.get("name")),
        "baseline_ids": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "items": items,
    }
    digest = hashlib.sha256(_canonical_json(draft).encode("utf-8")).hexdigest()
    draft["payload_sha256"] = digest
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
            "name": _as_text(run.get("name")),
            "source_name": _as_text(run.get("source_name")),
            "created_at": _as_text(run.get("created_at")),
        },
        "baselines": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "count": len(items),
        "invalid_label_issue_ids": invalid_labels,
        "payload_sha256": digest,
        "items": items,
        "draft": draft,
    }


async def _build_preview(
    request: Request,
    *,
    selected_run_id: str,
    baselines: str = "",
) -> dict[str, Any]:
    if not selected_run_id:
        raise _detail(400, "请选择一个模型 Run 后再生成 Trail 属性更新预览。")
    baseline_ids = resolve_request_baseline_ids(baselines, request=request)
    baseline_scopes = resolve_request_baseline_scopes(baselines, request=request)
    run = await asyncio.to_thread(database.get_model_run, selected_run_id)
    if run is None:
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


@router.get("/api/trail-attribute-update/preview")
async def trail_attribute_update_preview(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    """Return should-exclude rows for exactly one Run plus field capability."""

    return await _build_preview(
        request,
        selected_run_id=_as_text(model_run_id),
        baselines=baselines,
    )


@router.post("/api/trail-attribute-update/commit")
async def trail_attribute_update_commit(request: Request) -> dict[str, Any]:
    """Commit an unchanged, field-validated preview to Trail in small chunks."""

    if not settings.trail_attribute_write_enabled:
        raise _detail(409, "Trail 属性写入开关尚未开启；当前仅允许预览和下载草稿。")
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
    if not run_id or not submitted_digest:
        raise _detail(400, "提交内容缺少 model_run_id 或 payload_sha256。")
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
        stats = await asyncio.to_thread(
            write_trail_model_results,
            changes,
            ra_root=settings.ra_auto_triage_root,
            chunk_size=settings.trail_attribute_write_chunk_size,
        )
    return {
        "ok": not stats.get("failed_count"),
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
    }
