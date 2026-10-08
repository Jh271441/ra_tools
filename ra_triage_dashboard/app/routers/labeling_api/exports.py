"""Labeling exports HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any
from ...db import LABELS
from fastapi import Request
from fastapi.responses import Response
from ...support.common import _as_text
from ...support.common import _detail
from ...support.catalogs import _parse_issue_id_filter
from ...runtime import _public_path
import asyncio
from ...runtime import database
from datetime import datetime
import hashlib
import io
import openpyxl
from ...support.baselines import resolve_request_baseline_scopes
from .common import _active_labeling_scopes, _labeling_actor, _labeling_filter_values, _require_active_gt_export_batch, _require_labeling_admin

router = APIRouter()


@router.post("/api/labeling/gt-export-previews")
async def create_gt_export_preview(request: Request) -> dict[str, Any]:
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_actor, request
    )
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "导出预览请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "导出预览请求必须是 JSON 对象。")
    filter_body = body.get("filters") if isinstance(body.get("filters"), dict) else {}
    scopes = resolve_request_baseline_scopes(
        _as_text(body.get("baselines") or filter_body.get("baselines")),
        request=request,
    )
    scopes = await _active_labeling_scopes(scopes)
    if not scopes:
        raise _detail(409, "当前选择的数据集尚未激活 Case 标注迁移。")
    issue_ids = body.get("issue_ids") or []
    if not isinstance(issue_ids, list):
        raise _detail(400, "issue_ids 必须是数组。")
    selected_issue_ids = list(
        dict.fromkeys(_as_text(value).strip() for value in issue_ids if _as_text(value).strip())
    )
    if not selected_issue_ids and filter_body:
        normalized_status = _labeling_filter_values(
            filter_body.get("status"),
            allowed={"pending", "resolved", "conflict"},
            error="标注状态不合法。",
            lower=True,
        )
        normalized_exclusion = _labeling_filter_values(
            filter_body.get("exclusion"),
            allowed={"excluded", "active"},
            error="排除筛选不合法。",
            lower=True,
        )
        normalized_label = _labeling_filter_values(
            filter_body.get("label"),
            allowed=set(LABELS),
            error="标注结果类别不合法。",
        )
        normalized_gt = _labeling_filter_values(
            filter_body.get("gt"),
            allowed=set(LABELS),
            error="GT 类别不合法。",
        )
        normalized_comment_state = _labeling_filter_values(
            filter_body.get("comment_state"),
            allowed={"with", "without"},
            error="讨论筛选不合法。",
            lower=True,
        )
        raw_filter_issue_ids = _as_text(filter_body.get("issue_ids"))
        normalized_filter_issue_ids = _parse_issue_id_filter(raw_filter_issue_ids)
        if raw_filter_issue_ids.strip() and not normalized_filter_issue_ids:
            raise _detail(400, "issue_ids 未包含有效的 Issue ID。")
        try:
            selected_issue_ids = await asyncio.to_thread(
                database.labeling_case_issue_ids,
                baseline_scopes=scopes,
                task_id=_as_text(filter_body.get("task_id")),
                search=_as_text(filter_body.get("q")),
                issue_ids=normalized_filter_issue_ids,
                status=normalized_status,
                author=_labeling_filter_values(filter_body.get("author"), lower=True),
                assignee=_labeling_filter_values(filter_body.get("assignee"), lower=True),
                exclusion=normalized_exclusion,
                expected_output=normalized_label,
                gt_label=normalized_gt,
                comment_state=normalized_comment_state,
                cluster=_as_text(filter_body.get("cluster")).strip(),
            )
        except ValueError as exc:
            raise _detail(400, str(exc)) from exc
        if not selected_issue_ids:
            raise _detail(400, "当前筛选范围没有可导出的 Case。")
    try:
        preview = await asyncio.to_thread(
            database.create_label_gt_export_preview,
            baseline_scopes=scopes,
            issue_ids=selected_issue_ids,
            created_by=actor,
            created_by_source=actor_source,
            created_by_verified=actor_verified,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    return {
        "preview": preview,
        "download_url": _public_path(f"/api/labeling/gt-exports/{preview['id']}") if preview["item_count"] else "",
        "change_revision": await asyncio.to_thread(database.change_revision),
    }

@router.get("/api/labeling/gt-export-previews/{batch_id}")
async def get_gt_export_preview(batch_id: str, request: Request) -> dict[str, Any]:
    await _require_labeling_admin(request)
    batch = await _require_active_gt_export_batch(batch_id)
    return {"preview": batch}

@router.post("/api/labeling/gt-export-previews/{batch_id}/reconcile")
async def reconcile_gt_export_preview(batch_id: str, request: Request) -> dict[str, Any]:
    await _require_labeling_admin(request)
    await _require_active_gt_export_batch(batch_id)
    result = await asyncio.to_thread(
        database.reconcile_label_gt_export_batch, batch_id
    )
    return {
        "preview": result,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }

@router.get("/api/labeling/gt-exports/{batch_id}")
async def export_gt_candidates(batch_id: str, request: Request) -> Response:
    await asyncio.to_thread(_labeling_actor, request)
    await _require_active_gt_export_batch(batch_id)
    batch = await asyncio.to_thread(database.validate_label_gt_export_batch, batch_id)
    if batch["stale_issue_ids"]:
        raise _detail(
            409,
            "以下 Issue 的标签或 GT 已变化，请重新生成导出预览："
            + "、".join(batch["stale_issue_ids"][:20]),
        )
    if batch["status"] == "exported":
        raise _detail(409, "该导出批次已下载；请从当前候选重新生成预览。")
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "GT 更新"
    worksheet.append(["issue_id", "期望输出"])
    for item in batch["items"]:
        worksheet.append([item["issue_id"], item["expected_output"]])
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.column_dimensions["A"].width = 24
    worksheet.column_dimensions["B"].width = 16
    output = io.BytesIO()
    workbook.save(output)
    content = output.getvalue()
    await asyncio.to_thread(
        database.mark_label_gt_exported,
        batch_id=batch_id,
        file_sha256=hashlib.sha256(content).hexdigest(),
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="label-gt-update-{timestamp}.xlsx"'
        },
    )
