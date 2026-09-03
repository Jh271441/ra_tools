"""Trail attribute update routes domain."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile

from ...auth import (
    has_same_origin_mutation_marker,
    identity_can_write,
    request_identity,
)
from ...contracts import MAX_UPLOAD_BYTES
from ...support.baselines import resolve_request_baseline_ids
from ...support.common import _as_text, _detail
from ...import_parsing import parse_source_bytes
from ...runtime import database, issue_tag_sources, review_notification_dispatcher, settings
from ...review_mentions import extract_review_mentions, notification_recipients
from ...trail_exclusion_contracts import (
    TRAIL_TARGET_PATH,
    expected_exclusion_comments as _expected_exclusion_comments,
    normalise_issue_entries as _normalise_issue_entries,
    normalise_issue_ids as _normalise_issue_ids,
    trail_update_status_summary as _trail_update_status_summary,
    trail_update_statuses as _trail_update_statuses,
)
from ...trail_sync import read_trail_model_fields
from ...trail_writer import (
    attach_trail_operation_id,
    build_manual_exclusion_changes,
    build_trail_changes,
    write_trail_model_results,
)
from ...upload_limits import UploadLimitExceeded, read_upload_limited
from .commit import (
    _commit_lock,
    _mark_local_review_exclusions,
    _readback_changes,
    _save_issue_exclusion_history,
)
from .imports import (
    _historical_source_payload,
    _issue_import_display_filename,
    _issue_import_json_rows,
    _resolve_historical_exclusion_entries,
    build_trail_issue_import_preview,
)
from .preview import (
    _build_direct_preview,
    _build_preview,
    _capability_not_checked,
    _field_names,
    _preview_capability_cache,
    _preview_status_expectations,
    _read_preview_trail_status,
)


router = APIRouter()

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

@router.get("/api/trail-attribute-update/status")
async def trail_attribute_update_status(
    issue_ids: str = "",
    payload_sha256: str = "",
    refresh: bool = False,
) -> dict[str, Any]:
    """Return only the batched Trail state for an existing Review preview.

    The browser uses this after the local candidate table has painted.  Keeping
    the remote state response compact avoids a second DB aggregation and, more
    importantly, avoids replacing the table/controls when Trail is slow.
    """

    normalized_ids, invalid_ids = _normalise_issue_ids(issue_ids)
    if invalid_ids:
        raise _detail(422, f"Issue ID 格式不合法：{', '.join(invalid_ids[:5])}")
    if len(normalized_ids) > 500:
        raise _detail(422, "一次最多查询 500 个 Issue。")
    result_field, info_field = _field_names()
    if not normalized_ids:
        capability = _capability_not_checked(result_field, info_field)
        capability["target_fields"] = [info_field]
        capability["required_fields"] = [info_field]
        return {
            "issue_ids": [],
            "trail_capability": capability,
            "trail_update_statuses": {},
            "trail_update_status_summary": {},
            "write_status": "disabled",
            "write_ready": False,
        }
    expected_comments = _preview_status_expectations(payload_sha256)
    # A digest is supplied by current clients.  If its short-lived local
    # expectation has expired, do not downgrade to marker-only matching: that
    # could incorrectly hide a changed exclusion note.  Ask the client to
    # reload the local preview instead.  Keep the no-digest fallback for one
    # rolling-deploy window with older cached static assets.
    if payload_sha256 and expected_comments is None:
        capability = _capability_not_checked(result_field, info_field)
        capability.update({
            "target_fields": [info_field],
            "required_fields": [info_field],
            "message": "本地排除预览已过期，请重新打开问题排除页面后再检查 Trail 状态。",
        })
        statuses = {issue_id: "query_failed" for issue_id in normalized_ids}
        return {
            "issue_ids": normalized_ids,
            "trail_capability": capability,
            "trail_update_statuses": statuses,
            "trail_update_status_summary": _trail_update_status_summary(statuses),
            "pending_count": 0,
            "write_status": "status_check_incomplete",
            "write_ready": False,
        }
    projection = await _read_preview_trail_status(
        normalized_ids,
        info_field=info_field,
        expected_comments=expected_comments,
        refresh=refresh,
    )
    capability = dict(projection["trail_capability"])
    review_write_enabled = bool(
        settings.trail_attribute_write_enabled
        and getattr(settings, "trail_attribute_review_write_enabled", False)
    )
    statuses = dict(projection["trail_update_statuses"])
    pending_count = sum(1 for status in statuses.values() if status == "pending")
    status_check_complete = all(
        status in {"pending", "synced"} for status in statuses.values()
    )
    write_status = "disabled"
    if review_write_enabled:
        if not capability.get("ready"):
            write_status = "fields_unavailable"
        elif not status_check_complete:
            write_status = "status_check_incomplete"
        elif not pending_count:
            write_status = "already_synced"
        else:
            write_status = "ready"
    return {
        "issue_ids": normalized_ids,
        "trail_capability": capability,
        "trail_update_statuses": statuses,
        "trail_update_status_summary": dict(
            projection["trail_update_status_summary"]
        ),
        "pending_count": pending_count,
        "write_status": write_status,
        "write_ready": write_status == "ready",
    }

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

@router.post("/api/trail-attribute-update/issue-import/json-preview")
async def trail_issue_json_import_preview(request: Request) -> dict[str, Any]:
    """Parse an Issue-shielding JSON draft without changing the editor or Trail."""

    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "预览内容不是合法 JSON。") from exc
    try:
        rows, context = await asyncio.to_thread(_issue_import_json_rows, body)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return await asyncio.to_thread(
        build_trail_issue_import_preview,
        rows,
        import_format="json",
        fallback_comment=_as_text(context.get("fallback_comment")),
        comment_by_issue=context.get("comment_by_issue"),
    )

@router.post("/api/trail-attribute-update/issue-import/excel-preview")
async def trail_issue_excel_import_preview(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Parse an XLSX/XLSM Issue-shielding sheet as a read-only preview."""

    filename = _issue_import_display_filename(file.filename or "issue-exclusions.xlsx")
    if Path(filename).suffix.lower() not in {".xlsx", ".xlsm"}:
        raise _detail(400, "请上传 .xlsx 或 .xlsm 文件。")
    try:
        content, source_sha256 = await read_upload_limited(
            file,
            max_bytes=MAX_UPLOAD_BYTES,
        )
    except UploadLimitExceeded as exc:
        raise _detail(413, "上传文件超过 64 MB 限制。") from exc
    if not content:
        raise _detail(400, "上传文件为空。")
    try:
        rows, metadata = await asyncio.to_thread(parse_source_bytes, filename, content)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, f"解析 Excel 失败: {exc}") from exc
    return await asyncio.to_thread(
        build_trail_issue_import_preview,
        rows,
        import_format="excel",
        filename=filename,
        source_sha256=source_sha256,
        metadata=metadata,
        require_exclusion_column=True,
        row_number_offset=2,
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
        expected_comments = _expected_exclusion_comments(
            [item for item in (preview.get("items") or []) if isinstance(item, dict)]
        )
        statuses = _trail_update_statuses(
            sync_result,
            [_as_text(item.get("issue_id")) for item in preview.get("items", [])],
            info_field=info_field,
            expected_comments=expected_comments,
        )
        incomplete_ids = [
            issue_id for issue_id, status in statuses.items()
            if status not in {"synced", "pending"}
        ]
        if incomplete_ids:
            raise _detail(
                409,
                f"Trail 状态检查不完整，未写入任何 Issue：{', '.join(incomplete_ids[:8])}",
            )
        pending_items = [
            item for item in (preview.get("items") or [])
            if _as_text(statuses.get(_as_text(item.get("issue_id")))) == "pending"
        ]
        skipped_synced_issue_ids = sorted(
            issue_id for issue_id, status in statuses.items() if status == "synced"
        )
        if not pending_items:
            _preview_capability_cache.clear()
            return {
                "ok": True,
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
                "submitted_count": 0,
                "skipped_synced_issue_ids": skipped_synced_issue_ids,
                "trail_update_status_summary": _trail_update_status_summary(statuses),
                "stats": write_trail_model_results([], ra_root=settings.ra_auto_triage_root),
                "readback": {
                    "complete": True,
                    "ok": True,
                    "checked_count": 0,
                    "verified_count": 0,
                    "missing_issue_ids": [],
                    "mismatched_issue_ids": [],
                    "message": "所有候选项的排除标记和排除说明均已同步；未发送 Trail 写入。",
                },
            }
        changes = await asyncio.to_thread(
            build_trail_changes,
            pending_items,
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
        _preview_capability_cache.clear()
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
        "submitted_count": len(changes),
        "skipped_synced_issue_ids": skipped_synced_issue_ids,
        "trail_update_status_summary": _trail_update_status_summary(statuses),
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
        # ``already_synced`` is a successful, idempotent terminal state for
        # Trail itself.  Still allow this request to refresh the local Review
        # exclusion flag below; do not send a duplicate field update.
        if (
            not preview.get("write_ready")
            and _as_text(preview.get("write_status")) != "already_synced"
        ):
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
        mentions_by_issue: dict[str, list[str]] = {}
        notification_recipients_by_issue: dict[str, list[str]] = {}
        for issue_id, comment in effective_comments.items():
            try:
                mentions = extract_review_mentions(comment)
            except ValueError as exc:
                raise _detail(400, f"{issue_id}: {exc}") from exc
            enabled_mentions = await asyncio.to_thread(
                database.enabled_mention_recipients, mentions
            )
            unsupported = [
                username
                for username in mentions
                if username not in enabled_mentions
            ]
            if unsupported:
                raise _detail(
                    400,
                    f"{issue_id}: 以下用户不在可 @ / DChat 通知人员目录中："
                    + "、".join(f"@{item}" for item in unsupported),
                )
            mentions_by_issue[issue_id] = mentions
            recipients = notification_recipients(
                enabled_mentions, author=identity.username
            )
            notification_recipients_by_issue[issue_id] = (
                recipients
                if settings.dchat_notifications_enabled and identity.verified
                else []
            )
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
        statuses = {
            _as_text(item.get("issue_id")).strip(): _as_text(
                item.get("trail_update_status")
            )
            for item in (preview.get("items") or [])
            if _as_text(item.get("issue_id")).strip()
        }
        unchecked_issue_ids = sorted(
            issue_id
            for issue_id, status in statuses.items()
            if status not in {"pending", "synced"}
        )
        if unchecked_issue_ids:
            raise _detail(
                409,
                "Trail 状态检查不完整，未写入任何 Issue："
                f"{', '.join(unchecked_issue_ids[:8])}",
            )
        pending_issue_ids = sorted(
            issue_id for issue_id, status in statuses.items() if status == "pending"
        )
        skipped_synced_issue_ids = sorted(
            issue_id for issue_id, status in statuses.items() if status == "synced"
        )
        await _save_issue_exclusion_history(
            operation_id=submitted_digest,
            identity=identity,
            status="pending",
            requested_entries=history_entries,
            message=(
                f"已生成待提交记录：待写 {len(pending_issue_ids)} 条，"
                f"已同步跳过 {len(skipped_synced_issue_ids)} 条。"
            ),
        )
        _, info_field = _field_names()
        try:
            if pending_issue_ids:
                changes = await asyncio.to_thread(
                    build_manual_exclusion_changes,
                    pending_issue_ids,
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
            else:
                # Keep the response contract identical for an idempotent
                # retry, without instantiating a Trail client or sending any
                # write request.
                changes = []
                stats = write_trail_model_results(
                    [], ra_root=settings.ra_auto_triage_root
                )
                readback = {
                    "complete": True,
                    "ok": True,
                    "checked_count": 0,
                    "verified_count": 0,
                    "missing_issue_ids": [],
                    "mismatched_issue_ids": [],
                    "message": "所有候选项的排除标记和排除说明均已同步；未发送 Trail 写入。",
                }
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
            newly_verified_issue_ids = [
                str(item.get("issue_id") or "").strip()
                for item in changes
                if str(item.get("issue_id") or "").strip()
                and str(item.get("issue_id") or "").strip() not in field_failed
                and str(item.get("issue_id") or "").strip() not in readback_failed
            ]
            verified_issue_ids = sorted(
                set(skipped_synced_issue_ids) | set(newly_verified_issue_ids)
            )
            local_review = (
                await asyncio.to_thread(
                    _mark_local_review_exclusions,
                    verified_issue_ids,
                    actor=identity,
                    fallback_notes=effective_comments,
                    source_notes=source_notes,
                    mentions_by_issue=mentions_by_issue,
                    notification_recipients_by_issue=notification_recipients_by_issue,
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
            f"Trail 新写并回读 {len(newly_verified_issue_ids)}/{len(changes)} 条成功；"
            f"已同步跳过 {len(skipped_synced_issue_ids)} 条。"
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
        if local_review.get("notification_queued_count"):
            review_notification_dispatcher.wake()
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
        "submitted_count": len(changes),
        "skipped_synced_issue_ids": skipped_synced_issue_ids,
        "trail_update_status_summary": _trail_update_status_summary(statuses),
        "stats": stats,
        "readback": readback,
        "local_review": local_review,
    }
