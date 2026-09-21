from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

from ..auth import request_identity
from ..runtime import database, logger, review_notification_dispatcher, settings
from ..support.annotations import _create_annotation_record
from ..support.attachments import (
    _public_review_attachment,
    _store_review_attachments,
)
from ..support.common import _as_text, _detail

router = APIRouter()


async def _require_unmigrated_issue(
    issue_id: str, database: Any, *, model_run_id: str = ""
) -> dict[str, Any]:
    """Block only legacy no-Run writes after Case-label activation."""

    issue = await asyncio.to_thread(database.get_issue, issue_id)
    if issue is None:
        raise _detail(404, "Issue 不存在。")
    active = await asyncio.to_thread(database.active_labeling_scopes)
    if (
        str(issue.get("baseline_scope") or "") in active
        and not str(model_run_id or "").strip()
    ):
        raise _detail(
            409,
            "该数据集已启用 Case 标注：无 Run 的标签/GT 写入请到 Case 标注工作台；"
            "带 Model Run 的判错复核可继续在 Review 保存。",
        )
    return issue


@router.post("/api/cases/{issue_id}/annotations")
async def create_annotation(issue_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "标注请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "标注请求必须是 JSON 对象。")
    await _require_unmigrated_issue(
        issue_id, database, model_run_id=_as_text(body.get("model_run_id")).strip()
    )
    annotation = await asyncio.to_thread(
        _create_annotation_record,
        issue_id=issue_id,
        request=request,
        body=body,
    )
    if annotation.get("notification", {}).get("status") == "queued":
        review_notification_dispatcher.wake()
    return {
        "annotation": annotation,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.post("/api/cases/{issue_id}/annotations-with-attachments")
async def create_annotation_with_attachments(
    issue_id: str,
    request: Request,
    payload: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
) -> dict[str, Any]:
    try:
        body = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise _detail(400, "payload 必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "payload 必须是 JSON 对象。")
    model_run_id = _as_text(body.get("model_run_id")).strip()
    await _require_unmigrated_issue(issue_id, database, model_run_id=model_run_id)
    records, paths = await _store_review_attachments(attachments or [])
    try:
        await _require_unmigrated_issue(issue_id, database, model_run_id=model_run_id)
        annotation = await asyncio.to_thread(
            _create_annotation_record,
            issue_id=issue_id,
            request=request,
            body=body,
            attachments=records,
        )
    except Exception:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    annotation["attachments"] = [
        _public_review_attachment(attachment)
        for attachment in annotation.get("attachments", [])
    ]
    if annotation.get("notification", {}).get("status") == "queued":
        review_notification_dispatcher.wake()
    return {
        "annotation": annotation,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.delete("/api/cases/{issue_id}/annotations/{annotation_id}")
async def delete_annotation(
    issue_id: str, annotation_id: int, request: Request
) -> dict[str, Any]:
    if annotation_id <= 0:
        raise _detail(400, "Review 版本 ID 不合法。")
    await _require_unmigrated_issue(issue_id, database)
    case = await asyncio.to_thread(database.get_case, issue_id)
    target = next(
        (
            item for item in (case or {}).get("annotations", [])
            if int(item.get("id") or 0) == annotation_id
        ),
        None,
    )
    if target and target.get("work_split_id"):
        identity = await asyncio.to_thread(request_identity, request, settings)
        role = (
            await asyncio.to_thread(database.access_role, identity.username)
            if identity.verified and identity.username
            else ""
        )
        if role != "admin" and (
            not identity.verified
            or identity.username.lower() != str(target.get("author") or "").lower()
        ):
            raise _detail(403, "只能删除自己的盲标 Review 版本。")
    try:
        deleted = await asyncio.to_thread(
            database.delete_annotation,
            issue_id=issue_id,
            annotation_id=annotation_id,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    if deleted is None:
        raise _detail(404, "Review 版本不存在或已被删除。")
    attachment_root = settings.review_attachments_dir.resolve()
    for attachment in deleted.get("attachments", []):
        path = (attachment_root / str(attachment.get("stored_name") or "")).resolve()
        if attachment_root not in path.parents:
            logger.warning(
                "Skipped unsafe deleted review attachment path annotation_id=%s",
                annotation_id,
            )
            continue
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            logger.exception(
                "Failed to remove deleted review attachment annotation_id=%s attachment_id=%s",
                annotation_id,
                attachment.get("id"),
            )
    deleted["attachments"] = [
        _public_review_attachment(attachment)
        for attachment in deleted.get("attachments", [])
    ]
    return {
        "deleted": deleted,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }
