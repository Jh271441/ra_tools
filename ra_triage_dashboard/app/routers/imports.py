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
from ..upload_limits import UploadLimitExceeded, read_upload_limited

router = APIRouter()

@router.post("/api/trail-model-sync")
async def trail_model_sync(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        body = {}
    mode = _as_text(body.get("mode") or "preview")
    if mode not in {"preview", "create"}:
        raise _detail(400, "mode 仅支持 preview 或 create。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor, request, body.get("requested_by")
    )
    return await asyncio.to_thread(
        sync_trail_model_fields,
        create_run=mode == "create",
        requested_by=actor,
        identity_source=actor_source,
        identity_verified=actor_verified,
        trigger="manual",
    )



@router.get("/api/import-contract")
async def import_contract() -> dict[str, Any]:
    return {
        "formats": [".json", ".csv", ".xlsx", ".xlsm"],
        "issues": {
            "enabled_in_ui": False,
            "compatibility_only": True,
            "required": ["issue_id"],
            "optional": [
                "trip_id",
                "gt_label / ra_merge_result / 期望输出",
                "title",
                "scenario",
                "summary",
                "trail_url",
            ],
        },
        "model_results": {
            "required": ["issue_id", "model_label 或 ra_stuck_auto_result"],
            "optional": [
                "trip_id",
                "model_reason / reason",
                "model_confidence / confidence",
                "model_extra",
                "ra_stuck_auto_result_info",
            ],
            "native_json_envelope": {"experiment": {}, "results": []},
        },
        "autotriage_snapshot": {
            "input": "数字 Batch ID 或 records 链接",
            "source": "服务器固定只读 AutoTriage API",
            "kind": "autotriage_snapshot",
            "make_default": False,
        },
        "notes": [
            "每次导入会创建不可变 model run，并按 SHA-256 去重。",
            "页面不提供 Issue / GT 上传；旧 issues 接口仅为兼容客户端保留。Trail 真值不因模型导入而覆盖；仅显式 issues API 调用且 replace_gt=true 才会覆盖已有 GT。",
        ],
    }


async def _read_upload(upload: UploadFile) -> tuple[bytes, str, str]:
    filename = _safe_filename(upload.filename or "upload")
    try:
        content, source_hash = await read_upload_limited(
            upload,
            max_bytes=MAX_UPLOAD_BYTES,
        )
    except UploadLimitExceeded:
        raise _detail(413, "上传文件超过 64 MB 限制。")
    if not content:
        raise _detail(400, "上传文件为空。")
    return content, filename, source_hash



@router.post("/api/import/issues")
async def import_issues(
    file: UploadFile = File(...),
    source: str = Form("manual_upload"),
    replace_gt: str = Form("false"),
) -> dict[str, Any]:
    content, filename, _ = await _read_upload(file)
    try:
        source_rows, metadata = await asyncio.to_thread(
            parse_source_bytes, filename, content
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, f"解析文件失败: {exc}")
    rows = [normalized for row in source_rows if (normalized := normalize_issue_row(row, source))]
    if not rows:
        raise _detail(400, "未找到有效 issue_id；请检查表头或导入契约。")
    outcome = await asyncio.to_thread(
        database.upsert_issues,
        rows,
        source=source,
        replace_gt=replace_gt.lower() in {"1", "true", "yes", "on"},
    )
    return {
        "filename": filename,
        "parsed_rows": len(source_rows),
        "accepted_rows": len(rows),
        "metadata": metadata,
        **outcome,
    }
@router.post("/api/import/model-results")
async def import_model_results(
    request: Request,
    file: UploadFile = File(...),
    run_name: str = Form(""),
    created_by: str = Form(""),
) -> dict[str, Any]:
    content, filename, source_hash = await _read_upload(file)
    try:
        source_rows, metadata = await asyncio.to_thread(
            parse_source_bytes, filename, content
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, f"解析文件失败: {exc}")
    rows = [normalized for row in source_rows if (normalized := normalize_model_row(row))]
    if not rows:
        raise _detail(
            400,
            "未找到有效结果；需要 issue_id 和 model_label（或 ra_stuck_auto_result）。",
        )
    try:
        source_artifact = await asyncio.to_thread(
            _store_model_source,
            content,
            filename,
            source_hash,
        )
    except OSError as exc:
        raise _detail(507, f"无法归档模型结果原文件：{exc}")
    metadata = dict(metadata)
    metadata["source_artifact"] = source_artifact
    experiment = metadata.get("experiment") if isinstance(metadata.get("experiment"), dict) else {}
    default_name = _as_text(experiment.get("model_name")) or Path(filename).stem
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor, request, created_by
    )
    run, duplicate = await asyncio.to_thread(
        database.import_model_run,
        name=_as_text(run_name) or default_name,
        source_name=filename,
        source_sha256=source_hash,
        metadata=metadata,
        rows=rows,
        created_by=actor,
        created_by_source=actor_source,
        created_by_verified=actor_verified,
    )
    run = enrich_model_run_baseline_hint(run)
    return {
        "run": run,
        "duplicate": duplicate,
        "filename": filename,
        "parsed_rows": len(source_rows),
        "accepted_rows": len(rows),
        "rejected_rows": len(source_rows) - len(rows),
        "inferred_baseline_ids": list(run.get("inferred_baseline_ids") or []),
        "baseline_coverage": list(run.get("baseline_coverage") or []),
    }



@router.get("/api/import/autotriage/{batch_id}")
async def preview_autotriage_import(batch_id: str) -> dict[str, Any]:
    try:
        normalized_batch_id = normalise_batch_id(batch_id)
    except AutoTriageSourceError as exc:
        raise _detail(400, str(exc))
    try:
        snapshot = await asyncio.to_thread(
            _fetch_autotriage_snapshot,
            normalized_batch_id,
        )
    except AutoTriageSourceError as exc:
        raise _detail(502, str(exc))
    return {
        "batch_id": snapshot["batch_id"],
        "batch": snapshot["batch"],
        "coverage": snapshot["coverage"],
        "record_url": _autotriage_record_url(snapshot["batch_id"]),
        "default_changed": False,
        "read_only": True,
    }
@router.post("/api/import/autotriage")
async def import_autotriage_results(
    request: Request,
) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "AutoTriage 导入请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "AutoTriage 导入请求必须是 JSON 对象。")
    unknown = sorted(set(body) - {"batch_id", "run_name", "created_by"})
    if unknown:
        raise _detail(400, f"AutoTriage 导入包含未知字段：{', '.join(unknown)}。")
    try:
        normalized_batch_id = normalise_batch_id(body.get("batch_id"))
    except AutoTriageSourceError as exc:
        raise _detail(400, str(exc))
    try:
        snapshot = await asyncio.to_thread(
            _fetch_autotriage_snapshot,
            normalized_batch_id,
        )
    except AutoTriageSourceError as exc:
        raise _detail(502, str(exc))
    run_name = _as_text(body.get("run_name"))
    if len(run_name) > 120:
        raise _detail(400, "Run 名称不能超过 120 个字符。")
    batch = snapshot["batch"]
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor,
        request,
        body.get("created_by"),
    )
    metadata = {
        "schema_version": "autotriage-snapshot-v1",
        "origin": "autotriage_readonly_snapshot",
        "source_ref": f"autotriage_batch:{snapshot['batch_id']}",
        "record_url": _autotriage_record_url(snapshot["batch_id"]),
        "platform_batch": batch,
        "coverage": snapshot["coverage"],
        "external_username": _as_text(batch.get("username")),
        "model_name": _as_text(batch.get("model_name")),
        "prompt_version": _as_text(batch.get("prompt_version")),
        "prompt_sha256": _as_text(batch.get("prompt_sha256")),
        "default_changed": False,
    }
    run, duplicate = await asyncio.to_thread(
        database.import_model_run,
        name=run_name
        or _as_text(batch.get("batch_name"))
        or f"AutoTriage Batch {snapshot['batch_id']}",
        source_name=f"AutoTriage Batch {snapshot['batch_id']}",
        source_sha256=snapshot["source_sha256"],
        metadata=metadata,
        rows=snapshot["rows"],
        kind="autotriage_snapshot",
        make_default=False,
        created_by=actor,
        created_by_source=actor_source,
        created_by_verified=actor_verified,
    )
    return {
        "run": run,
        "duplicate": duplicate,
        "batch_id": snapshot["batch_id"],
        "coverage": snapshot["coverage"],
        "record_url": _autotriage_record_url(snapshot["batch_id"]),
        "default_changed": False,
        "read_only": True,
    }
