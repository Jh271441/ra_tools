from __future__ import annotations

import asyncio
import json
import math
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..contracts import MAX_SOURCE_PREVIEW_ROWS, MAX_UPLOAD_BYTES
from ..http_support import (
    _can_manage_team_default,
    _detail,
    _model_source_file,
    _model_source_filename,
    _public_path,
    _reconstructed_model_source,
    _source_preview_value,
    enrich_model_run_baseline_hint,
    resolve_review_exclusion_filter,
    resolve_request_baseline_scopes,
)
from ..import_parsing import parse_source_bytes
from ..runtime import database, settings

router = APIRouter()

@router.get("/api/model-runs")
async def model_runs(request: Request, baselines: str = "") -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    items = await asyncio.to_thread(
        database.list_model_runs, baseline_scopes=scopes
    )
    coverage_map = await asyncio.to_thread(
        database.model_run_scope_coverage_map,
        [str(item.get("id") or "") for item in items],
    )
    items = [
        enrich_model_run_baseline_hint(
            item,
            coverage=coverage_map.get(str(item.get("id") or ""), []),
        )
        for item in items
    ]
    for item in items:
        if item.get("kind") != "upload":
            continue
        source_file = _model_source_file(item)
        filename = _model_source_filename(item)
        suffix = Path(filename).suffix.lower()
        preview_supported = suffix in {".json", ".csv", ".xlsx", ".xlsm"}
        reconstructed = (
            source_file is None
            and preview_supported
            and bool(item.get("prediction_count"))
        )
        item["source_file"] = {
            "filename": filename,
            "available": bool(source_file) or reconstructed,
            "reconstructed": reconstructed,
            "preview_supported": preview_supported,
            "preview_url": _public_path(
                f"/api/model-runs/{quote(str(item['id']), safe='')}/source-preview"
                if preview_supported
                else f"/api/model-runs/{quote(str(item['id']), safe='')}/source"
            ),
            "download_url": _public_path(
                f"/api/model-runs/{quote(str(item['id']), safe='')}/source?download=1"
            ),
        }
    return {
        "items": items,
        "default_model_run_id": await asyncio.to_thread(
            database.default_model_run_id
        ),
    }

@router.get("/api/model-runs/{run_id}/source-preview")
async def preview_model_run_source(
    run_id: str,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    run = await asyncio.to_thread(database.get_model_run, run_id)
    if run is None:
        raise _detail(404, "模型 Run 不存在。")
    source_file = _model_source_file(run)
    reconstructed = False
    if source_file is None:
        filename = _model_source_filename(run)
        suffix = Path(filename).suffix.lower()
        reconstructed = True
    else:
        path, filename = source_file
        suffix = path.suffix.lower()
    if suffix not in {".json", ".csv", ".xlsx", ".xlsm"}:
        raise _detail(415, "当前仅支持在页面内预览 CSV / JSON / XLSX。")
    if reconstructed:
        source_rows = await asyncio.to_thread(database.model_run_source_rows, run_id)
        metadata = {
            "source": "dashboard_reconstructed",
            "notice": "原始文件未归档；以下内容由该 Run 已保存的脱敏预测行重建。",
        }
    else:
        try:
            source_size = await asyncio.to_thread(lambda: path.stat().st_size)
            if source_size > MAX_UPLOAD_BYTES:
                raise _detail(413, "来源文件过大，暂不生成页面预览；请使用下载。")
            content = await asyncio.to_thread(path.read_bytes)
            source_rows, metadata = await asyncio.to_thread(
                parse_source_bytes, filename, content
            )
        except HTTPException:
            raise
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise _detail(422, f"来源文件无法生成预览：{exc}")

    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), MAX_SOURCE_PREVIEW_ROWS)
    total_rows = len(source_rows)
    page_count = max(1, math.ceil(total_rows / page_size))
    page = min(page, page_count)
    page_start = (page - 1) * page_size
    page_rows = source_rows[page_start : page_start + page_size]
    preview_rows = [
        {
            str(key): _source_preview_value(value)
            for key, value in row.items()
        }
        for row in page_rows
    ]
    columns: list[str] = []
    seen_columns: set[str] = set()
    for row in preview_rows:
        for key in row:
            if key not in seen_columns:
                seen_columns.add(key)
                columns.append(key)
    metadata_preview = {
        str(key): _source_preview_value(value)
        for key, value in (metadata.items() if isinstance(metadata, dict) else [])
    }
    return {
        "filename": filename,
        "format": suffix[1:],
        "columns": columns,
        "rows": preview_rows,
        "total_rows": total_rows,
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "offset": page_start,
        "has_previous": page > 1,
        "has_next": page < page_count,
        "truncated": total_rows > len(preview_rows),
        "metadata": metadata_preview,
        "reconstructed": reconstructed,
    }



@router.get("/api/model-runs/{run_id}/source")
async def get_model_run_source(run_id: str, download: bool = False) -> Response:
    run = await asyncio.to_thread(database.get_model_run, run_id)
    if run is None:
        raise _detail(404, "模型 Run 不存在。")
    source_file = _model_source_file(run)
    if source_file is None:
        reconstructed = await asyncio.to_thread(
            _reconstructed_model_source, run_id, run
        )
        if reconstructed is None:
            raise _detail(404, "该 Run 的原始文件未归档且无法从已保存结果重建。")
        content, filename, media_type = reconstructed
        disposition = "attachment" if download else "inline"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "Cache-Control": "private, max-age=300, must-revalidate",
                "X-Content-Type-Options": "nosniff",
                "X-RA-Source-Reconstructed": "1",
            },
        )
    path, filename = source_file
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=300, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )



@router.delete("/api/model-runs/{run_id}")
async def delete_model_run(run_id: str) -> dict[str, Any]:
    run = await asyncio.to_thread(database.get_model_run, run_id)
    if run is None:
        raise _detail(404, "模型 Run 不存在。")
    source_file = _model_source_file(run)
    try:
        deleted = await asyncio.to_thread(database.delete_model_run, run_id)
    except ValueError as exc:
        raise _detail(409, str(exc))
    if deleted is None:
        raise _detail(404, "模型 Run 不存在。")

    source_deleted = False
    if source_file is not None:
        path, _ = source_file
        upload_root = settings.uploads_dir.resolve()
        resolved = path.resolve()
        if upload_root == resolved or upload_root in resolved.parents:
            try:
                await asyncio.to_thread(resolved.unlink, missing_ok=True)
                source_deleted = True
            except OSError:
                # The Run is already deleted; report the artifact separately so
                # an operator can recover a permissions/disk cleanup issue.
                source_deleted = False
    return {
        "deleted": deleted,
        "source_deleted": source_deleted,
    }



@router.post("/api/model-runs/{run_id}/default")
async def set_default_model_run(run_id: str, request: Request) -> dict[str, Any]:
    if not await asyncio.to_thread(_can_manage_team_default, request):
        raise _detail(
            403,
            "设置团队默认 Run 需要可信 SSO 且用户名位于 "
            "DASHBOARD_TEAM_DEFAULT_MANAGERS；当前仍可在 Review 中选择任意 Run。",
        )
    run = await asyncio.to_thread(database.set_default_model_run, run_id)
    if run is None:
        raise _detail(404, "模型 run 不存在。")
    return {"run": run, "default_model_run_id": run_id}



@router.get("/api/review-clusters")
async def review_clusters(
    request: Request,
    model_run_id: str = "",
    failure_only: bool = True,
    annotation_author: str = "",
    exclusion: str = "all",
    baselines: str = "",
) -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    exclusion, is_excluded = resolve_review_exclusion_filter(exclusion)
    return {
        "items": await asyncio.to_thread(
            database.review_clusters,
            baseline_scopes=scopes,
            model_run_id=model_run_id,
            failure_only=failure_only,
            annotation_author=annotation_author,
            is_excluded=is_excluded,
        ),
        "exclusion": exclusion,
    }
