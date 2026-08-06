from __future__ import annotations

from typing import Any, List, Optional, Union

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from ..http_support import *  # noqa: F401,F403
from ..runtime import *  # noqa: F401,F403

# Keep FastAPI symbols after star-imports (runtime/http_support may not define them).
from fastapi import APIRouter, File, Form, Request, UploadFile  # noqa: F401
from fastapi.responses import (  # noqa: F401
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

router = APIRouter()

@router.get("/", include_in_schema=False)
@router.get("/review", include_in_schema=False)
@router.get("/review-analysis", include_in_schema=False)
@router.get("/runs", include_in_schema=False)
@router.get("/inference", include_in_schema=False)
@router.get("/batch-prediction", include_in_schema=False)
@router.get("/system-status", include_in_schema=False)
@router.get("/users", include_in_schema=False)
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
    return {
        "ok": True,
        "build_commit": settings.build_commit,
        "base_path": settings.base_path,
        "deployment_mode": settings.deployment_mode,
        "ra_auto_triage_root_available": (settings.ra_auto_triage_root / "vlm").is_dir(),
        "ares_manifest_available": settings.ares_manifest.is_file(),
        "ares_indexed_issues": asset_index.refresh(),
        "camera_cache_root_available": settings.camera_root.is_dir(),
        "ares_video_root_available": settings.ares_video_root.is_dir(),
        "baseline": runtime_state["baseline"],
        "baselines": runtime_state.get("baselines") or [],
        "baseline_conflicts": runtime_state.get("baseline_conflicts") or [],
        "trail_sync": runtime_state["trail_sync"],
        "trail_write_enabled": False,
        "batch_prediction_enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
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
async def change_revision(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return {
        "revision": await asyncio.to_thread(database.change_revision),
        "poll_after_ms": 1800,
    }



@router.get("/api/baselines")
async def list_baselines() -> dict[str, Any]:
    media = media_registry.media_ready_by_id()
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
    return {
        "baseline": runtime_state["baseline"],
        "baselines": runtime_state.get("baselines") or baseline_registry.public_summaries(),
        "default_baseline_ids": baseline_registry.default_ids(),
        "baseline_conflicts": runtime_state.get("baseline_conflicts") or [],
        "build_commit": settings.build_commit,
        "default_model_run_id": database.default_model_run_id(),
        "trail_sync": runtime_state["trail_sync"],
        "missing_evidence_catalog": await asyncio.to_thread(_missing_evidence_catalog),
        "review_tag_catalog": await asyncio.to_thread(_review_tag_catalog),
        # Free-text keyword themes were an earlier experiment and are not
        # exposed by the current structured Review workflow.
        "review_reason_theme_catalog": (),
        "review_attachment_limits": {
            "max_count": MAX_REVIEW_ATTACHMENTS,
            "max_bytes_each": MAX_REVIEW_ATTACHMENT_BYTES,
            "max_bytes_total": MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES,
            "media_types": ["image/png", "image/jpeg", "image/webp"],
        },
        "default_failure_only": bool(database.default_model_run_id()),
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


def _review_tag_payload(item: dict[str, Any], *, builtin: bool = False) -> dict[str, Any]:
    payload = {
        **item,
        "builtin": bool(item.get("builtin", builtin)),
        "deleted": not bool(item.get("active", 1))
        if "active" in item
        else bool(item.get("deleted", False)),
    }
    payload.pop("active", None)
    payload.setdefault("section", "scene")
    payload.setdefault("group", payload.pop("group_key", "environment"))
    payload.setdefault("hint", "")
    return payload


def _validate_review_tag_input(
    body: dict[str, Any],
    *,
    default_group: str = "environment",
) -> tuple[str, str, str, str]:
    """Return (label, hint, group, section) for managed Issue-tag catalog rows."""

    label = _as_text(body.get("label"))
    hint = _as_text(body.get("hint"))
    group = _as_text(body.get("group") or default_group)
    if not label:
        raise _detail(400, "场景标签标题不能为空。")
    if len(label) > 48 or re.search(r"[\x00-\x1f\x7f]", label):
        raise _detail(400, "场景标签标题长度或字符不合法。")
    if len(hint) > 160 or re.search(r"[\x00-\x1f\x7f]", hint):
        raise _detail(400, "场景标签说明长度或字符不合法。")
    section = REVIEW_TAG_MANAGED_GROUPS.get(group)
    if section is None:
        raise _detail(400, "场景标签分组不合法。")
    return label, hint, group, section



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
    backup_state, volume_state = await asyncio.gather(
        asyncio.to_thread(backup_status, settings.data_dir),
        asyncio.to_thread(volume_status, settings.data_dir),
    )
    baseline_state = runtime_state["baseline"]
    overall = overall_status(
        database=database_state,
        baseline=baseline_state,
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
        "build_commit": settings.build_commit,
        "ra_auto_triage_root_available": (settings.ra_auto_triage_root / "vlm").is_dir(),
        "ares_manifest_available": settings.ares_manifest.is_file(),
        "ares_indexed_issues": asset_index.refresh(),
        "camera_cache_root_available": settings.camera_root.is_dir(),
        "ares_video_root_available": settings.ares_video_root.is_dir(),
        "baseline": baseline_state,
        "baselines": runtime_state.get("baselines") or [],
        "baseline_conflicts": runtime_state.get("baseline_conflicts") or [],
        "trail_sync": runtime_state["trail_sync"],
        "batch_prediction_enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
        "batch_max_issues": settings.batch_max_issues,
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


def _parse_issue_id_filter(raw: str) -> list[str]:
    tokens = re.split(r"[\s,;|]+", _as_text(raw))
    cleaned: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        issue_id = token.strip()
        if not issue_id or issue_id in seen:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", issue_id):
            continue
        seen.add(issue_id)
        cleaned.append(issue_id)
        if len(cleaned) >= 2000:
            break
    return cleaned


def _case_filter_kwargs(
    *,
    search: str = "",
    gt_label: str = "",
    model_label: str = "",
    annotation_label: str = "",
    annotation_author: str = "",
    model_run_id: str = "",
    comparison: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    issue_ids: str = "",
    work_assignee: str = "",
    baselines: str = "",
    request: Request | None = None,
) -> dict[str, Any]:
    comparison_values = [
        value
        for value in _csv_filter_values(comparison)
        if value in COMPARISON_STATUSES and value != "all"
    ]
    if failure_only and comparison_values and comparison_values != ["mismatch"]:
        # Legacy failure_only=true only expands empty comparison to mismatch.
        if comparison and set(comparison_values) != {"mismatch"}:
            raise _detail(400, "failure_only=true 与 comparison 参数冲突。")
    if failure_only and not comparison_values:
        comparison_values = ["mismatch"]
    if comparison_values and set(comparison_values) == {
        "match",
        "mismatch",
        "none",
    }:
        comparison_values = []
    comparison_status = ",".join(comparison_values) if comparison_values else "all"
    if comparison_status != "all" and not model_run_id:
        raise _detail(400, "筛选模型对比关系时必须选择 Model Run。")
    model_labels = _csv_filter_values(model_label)
    for label in model_labels:
        if label not in LABELS:
            raise _detail(400, "model_label 不在三分类范围内。")
    if model_labels and not model_run_id:
        raise _detail(400, "按模型标注筛选时必须选择 Model Run。")
    gt_labels = _csv_filter_values(gt_label)
    for label in gt_labels:
        if label not in LABELS:
            raise _detail(400, "gt_label 不在三分类范围内。")
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return {
        "baseline_scope": scopes[0] if len(scopes) == 1 else "",
        "baseline_scopes": scopes,
        "search": search,
        "gt_label": ",".join(gt_labels),
        "model_label": ",".join(model_labels),
        "annotation_label": annotation_label,
        "annotation_author": annotation_author,
        "model_run_id": model_run_id,
        "comparison_status": comparison_status,
        "failure_only": failure_only,
        "missing_evidence": missing_evidence,
        "issue_ids": _parse_issue_id_filter(issue_ids),
        "work_assignee": _as_text(work_assignee).strip(),
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
    publisher = request_identity(request, settings)
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
    job = database.get_batch_prediction_job(job_id)
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
        database.update_batch_prediction_job(
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
            database.get_batch_prediction_job(job_id) or job
        ),
        "accepted": True,
        "destination": settings.auto_triage_record_base_url,
        "poll_url": _public_path(f"/api/prediction-batches/{job_id}"),
    }
