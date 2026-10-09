"""Labeling revisions HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any
from fastapi import File
from fastapi.responses import FileResponse
from fastapi import Form
from ...db import LabelAnnotationConflictError
from typing import List
from typing import Optional
from pathlib import Path
from fastapi import Request
from fastapi import UploadFile
from ...support.common import _as_text
from ...support.common import _detail
from ...support.attachments import _store_review_attachments
import asyncio
from ...runtime import database
import json
from ...runtime import settings
from .common import _labeling_actor, _labeling_payload, _public_label_revision, _require_active_labeling_issue, _require_labeling_writer

router = APIRouter()


@router.post("/api/labeling/cases/{issue_id}/revisions")
async def create_label_revision(issue_id: str, request: Request) -> dict[str, Any]:
    await _require_active_labeling_issue(issue_id)
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "标注请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "标注请求必须是 JSON 对象。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_actor, request
    )
    payload = _labeling_payload(body)
    raw_previous = body.get("expected_previous_revision_id")
    try:
        expected_previous = (
            None if raw_previous in (None, "", 0, "0") else int(raw_previous)
        )
    except (TypeError, ValueError) as exc:
        raise _detail(400, "expected_previous_revision_id 不合法。") from exc
    try:
        revision = await asyncio.to_thread(
            database.create_label_revision,
            issue_id=issue_id,
            author=actor,
            author_source=actor_source,
            author_verified=actor_verified,
            task_id=_as_text(body.get("task_id")),
            source_run_id="",
            expected_previous_revision_id=expected_previous,
            **payload,
        )
    except LabelAnnotationConflictError as exc:
        raise _detail(409, str(exc))
    except PermissionError as exc:
        raise _detail(403, str(exc))
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {
        "revision": _public_label_revision(revision),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }

@router.post("/api/labeling/cases/{issue_id}/revisions-with-attachments")
async def create_label_revision_with_attachments(
    issue_id: str,
    request: Request,
    payload: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
) -> dict[str, Any]:
    await _require_active_labeling_issue(issue_id)
    try:
        body = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, "标注 payload 必须是 JSON 对象。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "标注 payload 必须是 JSON 对象。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_actor, request
    )
    normalized = _labeling_payload(body)
    raw_previous = body.get("expected_previous_revision_id")
    try:
        expected_previous = (
            None if raw_previous in (None, "", 0, "0") else int(raw_previous)
        )
    except (TypeError, ValueError) as exc:
        raise _detail(400, "expected_previous_revision_id 不合法。") from exc
    records: list[dict[str, Any]] = []
    paths: list[Path] = []
    try:
        records, paths = await _store_review_attachments(attachments or [])
        revision = await asyncio.to_thread(
            database.create_label_revision,
            issue_id=issue_id,
            author=actor,
            author_source=actor_source,
            author_verified=actor_verified,
            task_id=_as_text(body.get("task_id")),
            source_run_id="",
            expected_previous_revision_id=expected_previous,
            attachments=records,
            **normalized,
        )
    except LabelAnnotationConflictError as exc:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise _detail(409, str(exc))
    except PermissionError as exc:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise _detail(403, str(exc))
    except Exception as exc:
        for path in paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        if isinstance(exc, ValueError):
            raise _detail(400, str(exc))
        raise
    return {
        "revision": _public_label_revision(revision),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }

@router.get("/api/labeling/attachments/{attachment_id}")
async def get_label_attachment(attachment_id: str, request: Request) -> FileResponse:
    await _require_labeling_writer(request)
    attachment = await asyncio.to_thread(database.get_label_attachment, attachment_id)
    if attachment is None:
        raise _detail(404, "标注图片不存在。")
    await _require_active_labeling_issue(attachment["issue_id"])
    root = settings.review_attachments_dir.resolve()
    path = (root / attachment["stored_name"]).resolve()
    if root not in path.parents or not await asyncio.to_thread(path.is_file):
        raise _detail(404, "标注图片文件不存在。")
    return FileResponse(
        path,
        media_type=attachment["media_type"],
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-cache",
        },
    )
