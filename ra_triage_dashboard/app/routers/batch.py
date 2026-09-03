from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from ..contracts import ISSUE_ID_RE
from ..runtime import _public_path
from ..support.common import _as_text, _detail
from ..support.external_links import _public_batch_job
from ..support.identity import _action_actor
from ..model_catalog import ModelCatalogError
from ..prompt_catalog import (
    INPUT_PRESETS,
    MAX_FRAME_COUNT,
    MAX_FRAME_OFFSET_MS,
    MAX_PROMPT_BYTES,
    MIN_FRAME_OFFSET_MS,
    PromptCatalogError,
    normalise_input_config,
)
from ..runtime import (
    batch_prediction_runner,
    database,
    model_catalog,
    prompt_catalog,
    settings,
)

router = APIRouter()

@router.get("/api/prediction-batches/models")
async def batch_prediction_models(
    refresh: bool = False,
    provider_id: str = "kylin",
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            model_catalog.list_models,
            refresh=refresh,
            allow_stale=True,
            provider_id=provider_id,
        )
    except ModelCatalogError as exc:
        raise _detail(exc.status_code, exc.public_message)



@router.get("/api/prediction-batches/providers")
async def batch_prediction_providers() -> dict[str, Any]:
    return model_catalog.provider_catalog()



@router.get("/api/prediction-batches/prompts")
async def batch_prediction_prompts() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            prompt_catalog.list_prompts,
            include_template=True,
        )
    except PromptCatalogError as exc:
        raise _detail(503, str(exc))



@router.get("/api/prediction-batches/config")
async def batch_prediction_config() -> dict[str, Any]:
    latest = (
        await asyncio.to_thread(database.list_batch_prediction_jobs, page_size=1)
    ).get("items", [])
    latest_job = latest[0] if latest else {}
    return {
        "enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
        "max_issues": settings.batch_max_issues,
        "model": {
            "source": "服务器模型网关 + 用户选择的 Prompt/Camera 输入快照",
            "name": _as_text(latest_job.get("model_name"))
            or settings.ra_model_default_id,
            "prompt_version": _as_text(latest_job.get("prompt_version"))
            or "任务创建时固化服务器 Prompt",
        },
        "model_gateway": model_catalog.status(),
        "providers": model_catalog.provider_catalog(),
        "prompt_policy": {
            "source": "cloud_server ra_auto_triage/vlm/prompts/versions",
            "editable": True,
            "immutable_per_job": True,
            "max_bytes": MAX_PROMPT_BYTES,
        },
        "input_policy": {
            "issue_source": "Voyager Issue + dashboard isolated bag cache",
            "profiles": list(INPUT_PRESETS),
            "editable_fields": [
                "frame_offsets_ms",
                "use_ra_event",
                "use_ra_options",
                "use_bev_animation",
            ],
            "frame_count_max": MAX_FRAME_COUNT,
            "frame_offset_min_ms": MIN_FRAME_OFFSET_MS,
            "frame_offset_max_ms": MAX_FRAME_OFFSET_MS,
            "ares_animation_input": True,
            "ares_animation_policy": "server_default_stuck_triage_auto_opt_api",
            "ares_capture_input": False,
            "browser_model_credentials": False,
            "bag_cache_read_only": False,
            "bag_cache_scope": "dashboard_isolated",
            "trail_write_enabled": False,
        },
        "publish_policy": {
            "explicit_confirmation": True,
            "destination": settings.auto_triage_record_base_url,
            "writer": "cloud_server 固定服务身份",
            "requester_is_writer": False,
        },
    }



@router.post("/api/prediction-batches", status_code=202)
async def create_batch_prediction(request: Request) -> dict[str, Any]:
    if not settings.batch_prediction_enabled:
        raise _detail(503, "当前部署未启用 Batch 预测。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "Batch 请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "Batch 请求必须是 JSON 对象。")
    forbidden_model_fields = sorted(
        {
            "api_key",
            "base_url",
            "provider",
            "model_name",
            "model_override",
            "use_ares_capture",
            "use_bev_animation",
            "bev_mode",
            "bag_path",
            "camera_topic",
            "camera_topics",
            "experiment",
            "experiment_id",
            "experiment_revision_id",
        }.intersection(body)
    )
    if forbidden_model_fields:
        raise _detail(
            400,
            "禁止提交模型地址、凭证、provider、路径、实验 ID 或 Ares/BEV 配置。",
        )
    allowed_fields = {
        "name",
        "issue_ids",
        "requested_by",
        "provider_id",
        "model_id",
        "prompt_id",
        "prompt_template",
        "input_config",
        "allow_experimental_model",
    }
    unknown_fields = sorted(set(body) - allowed_fields)
    if unknown_fields:
        raise _detail(
            400,
            f"Batch 请求包含未知字段：{', '.join(unknown_fields)}。",
        )
    raw_issue_ids = body.get("issue_ids")
    if not isinstance(raw_issue_ids, list):
        raise _detail(400, "issue_ids 必须是数组。")
    issue_ids: list[str] = []
    seen: set[str] = set()
    for value in raw_issue_ids:
        issue_id = _as_text(value)
        if not ISSUE_ID_RE.fullmatch(issue_id):
            raise _detail(400, f"Issue ID 格式非法: {issue_id or '<空>'}")
        if issue_id not in seen:
            seen.add(issue_id)
            issue_ids.append(issue_id)
    if not issue_ids:
        raise _detail(400, "至少需要一个 Issue ID。")
    if len(issue_ids) > settings.batch_max_issues:
        raise _detail(
            400,
            f"单批最多 {settings.batch_max_issues} 个 Issue；当前 {len(issue_ids)} 个。",
        )
    provider_id = _as_text(body.get("provider_id") or "kylin").lower()
    provider_catalog = model_catalog.provider_catalog()
    provider = next(
        (
            item
            for item in provider_catalog.get("providers", [])
            if str(item.get("id") or "") == provider_id
        ),
        None,
    )
    if not provider or not provider.get("enabled"):
        raise _detail(400, "所选 Provider 未在 cloud_server 登记可用的服务端凭证。")
    existing_issue_ids = set(
        await asyncio.to_thread(
            database.list_case_issue_ids,
            issue_ids=issue_ids,
            limit=len(issue_ids),
        )
    )
    missing = [issue_id for issue_id in issue_ids if issue_id not in existing_issue_ids]
    if missing:
        preview = "、".join(missing[:8])
        suffix = "…" if len(missing) > 8 else ""
        raise _detail(
            404,
            f"以下 Issue 不在当前 Workbench 数据集中: {preview}{suffix}",
        )
    name = _as_text(body.get("name"))
    if len(name) > 120:
        raise _detail(400, "Batch 名称不能超过 120 个字符。")
    try:
        model_selection = await asyncio.to_thread(
            model_catalog.resolve,
            _as_text(body.get("model_id")),
            provider_id,
        )
    except ModelCatalogError as exc:
        raise _detail(exc.status_code, exc.public_message)
    validation_status = _as_text(
        model_selection.get("validation_status")
    ) or "validated"
    if (
        validation_status != "validated"
        and body.get("allow_experimental_model") is not True
    ):
        raise _detail(
            400,
            "该 Qwen3 模型在线但尚未完成 RA 基线验证；"
            "如需试跑，请显式确认 allow_experimental_model=true。",
        )
    try:
        prompt_selection = await asyncio.to_thread(
            prompt_catalog.resolve,
            body.get("prompt_id"),
            body.get("prompt_template"),
        )
        input_config = normalise_input_config(body.get("input_config"))
    except PromptCatalogError as exc:
        raise _detail(400, str(exc))
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor, request, body.get("requested_by")
    )
    if not name:
        actor_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", actor).strip("-")[:48] or "triage"
        name = f"{actor_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    job = await asyncio.to_thread(
        database.create_batch_prediction_job,
        name=name,
        issue_ids=issue_ids,
        requested_by=actor,
        requested_by_source=actor_source,
        requested_by_verified=actor_verified,
        provider_id=provider_id,
        requested_model_id=model_selection["requested_model_id"],
        resolved_model_id=model_selection["resolved_model_id"],
        model_source="ra_model_gateway",
        catalog_sha256=model_selection["catalog_sha256"],
        model_validation_status=validation_status,
        prompt_version=prompt_selection["prompt_version"],
        prompt_template=prompt_selection["prompt_template"],
        prompt_template_sha256=prompt_selection[
            "prompt_template_sha256"
        ],
        prompt_mode=prompt_selection["prompt_mode"],
        input_profile=input_config["profile_id"],
        input_config=input_config,
    )
    if not batch_prediction_runner.launch_prediction(job):
        error = "Batch worker 正在停止，任务无法入队；请稍后重试。"
        await asyncio.to_thread(
            database.update_batch_prediction_items,
            job["id"],
            [
                {"issue_id": issue_id, "success": False, "error": error}
                for issue_id in issue_ids
            ],
        )
        await asyncio.to_thread(
            database.update_batch_prediction_job,
            job["id"],
            status="failed",
            completed_count=len(issue_ids),
            failed_count=len(issue_ids),
            error_text=error,
        )
        raise _detail(409, error)
    return {
        "job": _public_batch_job(
            await asyncio.to_thread(database.get_batch_prediction_job, job["id"])
            or job
        ),
        "safety": {
            "server_default_model": False,
            "server_model_gateway": True,
            "provider_id": provider_id,
            "requested_model_id": model_selection["requested_model_id"],
            "resolved_model_id": model_selection["resolved_model_id"],
            "model_validation_status": validation_status,
            "prompt_version": prompt_selection["prompt_version"],
            "prompt_sha256": prompt_selection["prompt_template_sha256"],
            "prompt_mode": prompt_selection["prompt_mode"],
            "input_profile": input_config["profile_id"],
            "browser_model_credentials": False,
            "ares_bev_input": bool(input_config["use_bev_animation"]),
            "bag_cache_read_only": False,
            "bag_cache_scope": "dashboard_isolated",
            "trail_write_enabled": False,
            "autotriage_publish_automatic": False,
        },
        "poll_url": _public_path(f"/api/prediction-batches/{job['id']}"),
    }



@router.get("/api/prediction-batches")
async def list_batch_predictions(
    requested_by: str = "",
    status: str = "",
    model_id: str = "",
    prompt_version: str = "",
    prompt_mode: str = "",
    prompt_sha256: str = "",
    input_profile: str = "",
    page_size: int = 100,
) -> dict[str, Any]:
    result = await asyncio.to_thread(
        database.list_batch_prediction_jobs,
        requested_by=requested_by,
        status=status,
        model_id=model_id,
        prompt_version=prompt_version,
        prompt_mode=prompt_mode,
        prompt_sha256=prompt_sha256,
        input_profile=input_profile,
        page_size=page_size,
    )
    result["items"] = [
        _public_batch_job(job) for job in result.get("items", [])
    ]
    return result



@router.get("/api/prediction-batches/{job_id}")
async def get_batch_prediction(job_id: str) -> dict[str, Any]:
    job = await asyncio.to_thread(database.get_batch_prediction_job, job_id)
    if job is None:
        raise _detail(404, "Batch 任务不存在。")
    return {"job": _public_batch_job(job, include_prompt=True)}
