from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

from ..runtime import database, logger, review_notification_dispatcher, settings
from ..support.annotations import _create_annotation_record
from ..support.attachments import (
    _public_review_attachment,
    _store_review_attachments,
)
from ..support.common import _detail

router = APIRouter()


@router.post("/api/cases/{issue_id}/annotations")
async def create_annotation(issue_id: str, request: Request) -> dict[str, Any]:
    if await asyncio.to_thread(database.get_issue, issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "标注请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "标注请求必须是 JSON 对象。")
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
    if await asyncio.to_thread(database.get_issue, issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    try:
        body = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise _detail(400, "payload 必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "payload 必须是 JSON 对象。")
    records, paths = await _store_review_attachments(attachments or [])
    try:
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
async def delete_annotation(issue_id: str, annotation_id: int) -> dict[str, Any]:
    if annotation_id <= 0:
        raise _detail(400, "Review 版本 ID 不合法。")
    deleted = await asyncio.to_thread(
        database.delete_annotation,
        issue_id=issue_id,
        annotation_id=annotation_id,
    )
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
