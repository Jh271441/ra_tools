from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..auth import identity_header_candidates, normalise_username, request_identity
from ..contracts import (
    MAX_REVIEW_ATTACHMENT_BYTES,
    MAX_REVIEW_ATTACHMENTS,
    MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES,
)
from ..http_support import (
    _action_actor,
    _admin_identity,
    _as_text,
    _detail,
    _missing_evidence_catalog,
    _public_batch_job,
    _public_path,
    _review_tag_catalog,
    gt_sync_status,
    reserve_authoritative_gt_sync,
    resolve_gt_sync_baseline_ids,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
    sync_authoritative_gt,
)
from ..model_catalog import MODEL_ID_RE
from ..dchat import dchat_credentials_status
from ..review_mentions import MAX_REVIEW_MENTIONS
from ..runtime import (
    APP_STARTED_AT,
    APP_STARTED_MONOTONIC,
    INDEX_HTML,
    asset_index,
    baseline_registry,
    batch_prediction_runner,
    database,
    logger,
    media_registry,
    model_catalog,
    runtime_state,
    settings,
)
from ..system_status import backup_status, overall_status, volume_status
from ..web_paths import with_base_path

router = APIRouter()


def _filesystem_availability() -> dict[str, bool]:
    """Probe optional filesystem-backed integrations outside the event loop."""

    return {
        "ra_auto_triage_root_available": (
            settings.ra_auto_triage_root / "vlm"
        ).is_dir(),
        "ares_manifest_available": settings.ares_manifest.is_file(),
        "camera_cache_root_available": settings.camera_root.is_dir(),
        "ares_video_root_available": settings.ares_video_root.is_dir(),
    }


def _dashboard_config_payload() -> dict[str, Any]:
    """Build DB/catalog-backed config in one worker-thread hop."""

    default_model_run_id = database.default_model_run_id()
    return {
        "baseline": runtime_state["baseline"],
        "baselines": runtime_state.get("baselines")
        or baseline_registry.public_summaries(),
        "default_baseline_ids": baseline_registry.default_ids(),
        "baseline_conflicts": runtime_state.get("baseline_conflicts") or [],
        "build_commit": settings.build_commit,
        "default_model_run_id": default_model_run_id,
        "trail_sync": runtime_state["trail_sync"],
        "trail_attribute_update": {
            "enabled": settings.trail_attribute_write_enabled,
            "review_write_enabled": getattr(
                settings, "trail_attribute_review_write_enabled", False
            ),
            "view_id": settings.trail_view_id,
            "target_fields": [
                settings.trail_attribute_result_field,
                settings.trail_attribute_info_field,
            ],
        },
        # Local DB only — never queries Trail on page open.
        "gt_sync": gt_sync_status(),
        "missing_evidence_catalog": _missing_evidence_catalog(),
        "review_tag_catalog": _review_tag_catalog(),
        # Free-text keyword themes were an earlier experiment and are not
        # exposed by the current structured Review workflow.
        "review_reason_theme_catalog": (),
        "review_attachment_limits": {
            "max_count": MAX_REVIEW_ATTACHMENTS,
            "max_bytes_each": MAX_REVIEW_ATTACHMENT_BYTES,
            "max_bytes_total": MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES,
            "media_types": ["image/png", "image/jpeg", "image/webp"],
        },
        "review_notifications": {
            "enabled": settings.dchat_notifications_enabled,
            "provider": "DChat",
            "delivery_mode": settings.dchat_delivery_mode,
            "mention_limit": MAX_REVIEW_MENTIONS,
            "requires_verified_sso": True,
        },
        "default_failure_only": bool(default_model_run_id),
        "batch_prediction": {
            "enabled": settings.batch_prediction_enabled,
            "autotriage_push_enabled": settings.autotriage_push_enabled,
            "max_issues": settings.batch_max_issues,
            "input_policy": "server_model_gateway_profile",
            "ares_bev_input": True,
            "trail_write_enabled": False,
            "model_gateway": model_catalog.status(),
        },
    }


@router.get("/", include_in_schema=False)
@router.get("/review", include_in_schema=False)
@router.get("/review-analysis", include_in_schema=False)
@router.get("/runs", include_in_schema=False)
@router.get("/inference", include_in_schema=False)
@router.get("/batch-prediction", include_in_schema=False)
@router.get("/system-status", include_in_schema=False)
@router.get("/users", include_in_schema=False)
@router.get("/trail-attribute-update", include_in_schema=False)
async def index() -> HTMLResponse:
    return HTMLResponse(
        content=INDEX_HTML,
        headers={"Cache-Control": "no-store, max-age=0"},
    )



@router.get("/import", include_in_schema=False)
async def legacy_import(kind: str = "issues") -> RedirectResponse:
    # The legacy Issue / GT upload UI is intentionally retired. Keep old
    # bookmarks navigable, but land them in the safe model-result importer.
    return RedirectResponse(
        # Relative Location resolves to /runs for direct IP and
        # /manual/runs through the browser-visible strip-proxy URL.
        url="runs?import=model",
        status_code=307,
    )



@router.get("/health")
async def health() -> dict[str, Any]:
    filesystem = await asyncio.to_thread(_filesystem_availability)
    return {
        "ok": True,
        "build_commit": settings.build_commit,
        "base_path": settings.base_path,
        "deployment_mode": settings.deployment_mode,
        **filesystem,
        "ares_indexed_issues": asset_index.indexed_count(),
        "baseline": runtime_state["baseline"],
        "baselines": runtime_state.get("baselines") or [],
        "baseline_conflicts": runtime_state.get("baseline_conflicts") or [],
        "trail_sync": runtime_state["trail_sync"],
        "gt_sync": await asyncio.to_thread(gt_sync_status),
        "trail_write_enabled": False,
        "trail_attribute_write_enabled": settings.trail_attribute_write_enabled,
        "trail_attribute_review_write_enabled": getattr(
            settings, "trail_attribute_review_write_enabled", False
        ),
        "trail_attribute_target_fields": [
            settings.trail_attribute_result_field,
            settings.trail_attribute_info_field,
        ],
        "batch_prediction_enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
        "review_notifications": {
            "enabled": settings.dchat_notifications_enabled,
            "delivery_mode": settings.dchat_delivery_mode,
            "credentials": await asyncio.to_thread(
                dchat_credentials_status, settings.dchat_credentials_file
            ) if settings.dchat_notifications_enabled and settings.dchat_delivery_mode == "openapi" else {
                "ready": False,
                "message": "DChat loopback 不使用真实凭据。"
                if settings.dchat_delivery_mode == "loopback"
                else "DChat 评论通知未启用。",
            },
            "outbox": await asyncio.to_thread(
                database.review_notification_status
            ),
        },
        "model_gateway": model_catalog.status(),
        "change_revision": await asyncio.to_thread(database.change_revision),
        "storage": database.storage_label,
    }
@router.get("/api/overview")
async def overview(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    selected = model_run_id or await asyncio.to_thread(
        database.default_model_run_id
    )
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    ids = resolve_request_baseline_ids(baselines, request=request)
    payload = await asyncio.to_thread(
        database.overview,
        baseline_scopes=scopes,
        model_run_id=selected,
    )
    payload["baselines"] = ids
    payload["baseline_scopes"] = scopes
    return payload



@router.get("/api/change-revision")
async def change_revision(
    response: Response,
    include_gt_sync: bool = False,
) -> dict[str, Any]:
    """Cheap collaboration poll.

    Keep this endpoint filesystem/DB-light: the browser hits it every few
    seconds. Full GT sync status is optional and loaded less often by the UI.
    """

    response.headers["Cache-Control"] = "no-store, max-age=0"
    payload: dict[str, Any] = {
        "revision": await asyncio.to_thread(database.change_revision),
        # Default 5s keeps multi-user freshness without saturating the event
        # loop / Postgres pool while the gallery is also loading thumbs.
        "poll_after_ms": 5000,
    }
    if include_gt_sync:
        payload["gt_sync"] = await asyncio.to_thread(gt_sync_status)
    return payload


@router.get("/api/gt-sync-status")
async def authoritative_gt_sync_status(
    response: Response,
    baselines: str = "",
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    try:
        baseline_ids = resolve_gt_sync_baseline_ids(
            baselines or None,
            strict=bool(baselines),
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    return await asyncio.to_thread(gt_sync_status, baseline_ids)


@router.post("/api/gt-sync", status_code=202)
async def refresh_authoritative_gt(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if request.headers.get("x-ra-triage-request") != "browser-v1":
        raise _detail(403, "缺少 GT 刷新请求标记。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        body = {}
    submitted = body.get("requested_by", "") if isinstance(body, dict) else ""
    submitted_baselines = body.get("baselines") if isinstance(body, dict) else None
    try:
        baseline_ids = resolve_gt_sync_baseline_ids(
            submitted_baselines,
            strict=submitted_baselines not in (None, "", []),
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor, request, submitted
    )
    requested, accepted = reserve_authoritative_gt_sync(baseline_ids)
    if accepted:
        background_tasks.add_task(
            sync_authoritative_gt,
            baseline_ids=requested,
            requested_by=actor,
            identity_source=actor_source,
            identity_verified=actor_verified,
            trigger="manual",
            _lock_acquired=True,
        )
        state = await asyncio.to_thread(gt_sync_status, requested)
        state["message"] = "GT 后台同步已开始，完成后状态会自动更新。"
    else:
        state = {
            **(await asyncio.to_thread(gt_sync_status, requested)),
            "status": "running",
            "message": "已有权威 GT 同步任务在运行。",
        }
    return {
        **state,
        "accepted": accepted,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.get("/api/baselines")
async def list_baselines() -> dict[str, Any]:
    media = await asyncio.to_thread(media_registry.media_ready_by_id)
    items = []
    for summary in runtime_state.get("baselines") or []:
        baseline_id = str(summary.get("id") or "")
        items.append(
            {
                **summary,
                "media_ready": media.get(baseline_id, {}),
            }
        )
    if not items:
        items = baseline_registry.public_summaries()
    return {
        "items": items,
        "default_ids": baseline_registry.default_ids(),
        "conflicts": runtime_state.get("baseline_conflicts") or [],
    }



@router.get("/api/dashboard-config")
async def dashboard_config() -> dict[str, Any]:
    # One worker hop instead of several sequential first-paint thread switches.
    return await asyncio.to_thread(_dashboard_config_payload)







@router.get("/api/session")
async def session(request: Request, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    identity = await asyncio.to_thread(request_identity, request, settings)
    access_role = (
        await asyncio.to_thread(database.access_role, identity.username)
        if identity.verified and identity.username
        else ""
    )
    is_admin = access_role == "admin"
    can_write = settings.deployment_mode != "production" or access_role in {
        "writer",
        "admin",
    }
    payload = identity.as_dict(
        trust_proxy_headers=settings.trust_proxy_identity_headers
    ) | {
        "browser_lca_fallback": not identity.authenticated,
        "identity_header": (
            settings.identity_header
            if settings.trust_proxy_identity_headers
            else ""
        ),
        "access_role": access_role or "viewer",
        "is_admin": is_admin,
        "can_manage_team_default": is_admin,
        "deployment_mode": settings.deployment_mode,
        "can_write": can_write,
        "read_only": not can_write,
        "login_managed_by": "kylin" if settings.kylin_sso_enabled else "",
        "logout_url": with_base_path(settings.base_path, "/auth/logout")
        if settings.kylin_sso_enabled
        else "",
    }
    if settings.identity_diagnostics:
        payload["identity_header_candidates"] = identity_header_candidates(request)
    return payload



@router.get("/api/access-users")
async def list_access_users(request: Request) -> dict[str, Any]:
    await asyncio.to_thread(_admin_identity, request)
    return {"items": await asyncio.to_thread(database.list_access_users)}



@router.put("/api/access-users/{username}")
async def set_access_user(
    username: str, request: Request
) -> dict[str, Any]:
    identity = await asyncio.to_thread(_admin_identity, request)
    normalized = normalise_username(username)
    if not normalized:
        raise _detail(400, "用户名格式不合法。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "请求 JSON 不合法。")
    role = _as_text(body.get("role") if isinstance(body, dict) else "").lower()
    try:
        user = await asyncio.to_thread(
            database.set_access_user,
            username=normalized,
            role=role,
            actor=identity.username,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    return {
        "user": user,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.delete("/api/access-users/{username}")
async def delete_access_user(username: str, request: Request) -> dict[str, Any]:
    await asyncio.to_thread(_admin_identity, request)
    normalized = normalise_username(username)
    if not normalized:
        raise _detail(400, "用户名格式不合法。")
    try:
        deleted = await asyncio.to_thread(database.delete_access_user, normalized)
    except ValueError as exc:
        raise _detail(409, str(exc))
    if not deleted:
        raise _detail(404, "用户权限记录不存在。")
    return {
        "deleted": True,
        "username": normalized,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.get("/auth/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(settings.kylin_sso_logout_url, status_code=302)
    for cookie_name in ("_kylin_ticket", "_kylin_username"):
        response.delete_cookie(cookie_name, path="/")
    return response



@router.get("/api/status")
async def status(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    try:
        database_state = await asyncio.to_thread(
            database.runtime_status,
            persistent_data=settings.postgres_persistent_data,
        )
    except Exception:
        logger.exception("database status check failed")
        database_state = {
            "ok": False,
            "backend": database.backend,
            "server_version": "",
            "persistent_data": False,
            "revision": 0,
            "migration_count": 0,
            "pool_max_size": database.pool_size,
            "latency_ms": None,
        }
    backup_state, volume_state, indexed_issues, filesystem, media_ready = await asyncio.gather(
        asyncio.to_thread(backup_status, settings.data_dir),
        asyncio.to_thread(volume_status, settings.data_dir),
        asyncio.to_thread(asset_index.refresh),
        asyncio.to_thread(_filesystem_availability),
        asyncio.to_thread(media_registry.media_ready_by_id),
    )
    baseline_state = runtime_state["baseline"]
    baseline_states = [
        {
            **item,
            "media_ready": media_ready.get(str(item.get("id") or ""), {}),
        }
        for item in (runtime_state.get("baselines") or [])
    ]
    overall = overall_status(
        database=database_state,
        baseline=baseline_state,
        baselines=baseline_states,
        backups=backup_state,
        volume=volume_state,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_path": settings.base_path,
        "overall": overall,
        "application": {
            "started_at": APP_STARTED_AT.isoformat(),
            "uptime_seconds": max(0, int(time.monotonic() - APP_STARTED_MONOTONIC)),
            "build_commit": settings.build_commit,
            "base_path": settings.base_path,
            "deployment_mode": settings.deployment_mode,
        },
        "trail_write_enabled": False,
        "trail_attribute_write_enabled": settings.trail_attribute_write_enabled,
        "trail_attribute_review_write_enabled": getattr(
            settings, "trail_attribute_review_write_enabled", False
        ),
        "trail_attribute_target_fields": [
            settings.trail_attribute_result_field,
            settings.trail_attribute_info_field,
        ],
        "build_commit": settings.build_commit,
        **filesystem,
        "ares_indexed_issues": indexed_issues,
        "baseline": baseline_state,
        "baselines": baseline_states,
        "baseline_conflicts": runtime_state.get("baseline_conflicts") or [],
        "trail_sync": runtime_state["trail_sync"],
        "gt_sync": await asyncio.to_thread(gt_sync_status),
        "batch_prediction_enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
        "batch_max_issues": settings.batch_max_issues,
        "review_notifications": {
            "enabled": settings.dchat_notifications_enabled,
            "delivery_mode": settings.dchat_delivery_mode,
            "credentials": await asyncio.to_thread(
                dchat_credentials_status, settings.dchat_credentials_file
            ) if settings.dchat_notifications_enabled and settings.dchat_delivery_mode == "openapi" else {
                "ready": False,
                "message": "DChat loopback 不使用真实凭据。"
                if settings.dchat_delivery_mode == "loopback"
                else "DChat 评论通知未启用。",
            },
            "outbox": await asyncio.to_thread(database.review_notification_status),
        },
        "model_gateway": model_catalog.status(),
        "storage": database.storage_label,
        "database": database_state,
        "backups": backup_state,
        "volume": volume_state,
        "model_endpoint_policy": (
            "固定服务器网关；Profile 模型已验证，其他在线 Qwen3 显式实验；"
            "浏览器不能提交地址或凭证"
        ),
    }







@router.post(
    "/api/prediction-batches/{job_id}/publish-autotriage",
    status_code=202,
)
async def publish_batch_prediction(job_id: str, request: Request) -> dict[str, Any]:
    if request.headers.get("x-ra-triage-request") != "publish-v1":
        raise _detail(403, "缺少 AutoTriage 推送请求标记。")
    if not settings.autotriage_push_enabled:
        raise _detail(503, "当前部署未启用 AutoTriage 推送。")
    publisher = await asyncio.to_thread(request_identity, request, settings)
    if not publisher.verified or not publisher.username:
        raise _detail(
            403,
            "AutoTriage 是生产写操作，仅允许可信 SSO 会话；"
            "直接 IP / 本机 LCA 用户不能触发。",
        )
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "推送请求必须是 JSON。")
    if not isinstance(body, dict) or body.get("confirm") not in {
        True,
        "publish-autotriage",
    }:
        raise _detail(400, "必须显式确认创建生产 AutoTriage Batch。")
    job = await asyncio.to_thread(database.get_batch_prediction_job, job_id)
    if job is None:
        raise _detail(404, "Batch 任务不存在。")
    if job.get("autotriage_batch_id"):
        return {"job": _public_batch_job(job), "idempotent": True}
    if job.get("publish_status") == "running":
        raise _detail(409, "该 Batch 正在推送 AutoTriage。")
    if not MODEL_ID_RE.fullmatch(_as_text(job.get("resolved_model_id"))):
        raise _detail(
            409,
            "该历史 Batch 缺少已解析模型信息，不能安全推送；请重新发起预测。",
        )
    if (
        not _as_text(job.get("prompt_template"))
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            _as_text(job.get("prompt_template_sha256")).lower(),
        )
        or not _as_text(job.get("input_profile"))
        or not isinstance(job.get("input_config"), dict)
    ):
        raise _detail(
            409,
            "该历史 Batch 缺少不可变 Prompt/Input 快照，"
            "不能重建同一配置推送；请重新发起预测。",
        )
    if (
        job.get("status") not in {"succeeded", "partial"}
        or int(job.get("success_count") or 0) <= 0
        or not job.get("model_run_id")
        or not job.get("config_sha256")
    ):
        raise _detail(409, "Batch 尚无可推送的成功预测。")
    job = (
        await asyncio.to_thread(
            database.update_batch_prediction_job,
            job_id,
            summary={
                **dict(job.get("summary") or {}),
                "autotriage_publish_request": {
                    "requested_by": publisher.username,
                    "identity_source": publisher.source,
                    "verified": True,
                },
            },
        )
        or job
    )
    if not batch_prediction_runner.launch_publish(job):
        raise _detail(409, "已有 Batch 预测或 AutoTriage 推送正在执行，请稍后重试。")
    return {
        "job": _public_batch_job(
            await asyncio.to_thread(database.get_batch_prediction_job, job_id)
            or job
        ),
        "accepted": True,
        "destination": settings.auto_triage_record_base_url,
        "poll_url": _public_path(f"/api/prediction-batches/{job_id}"),
    }
