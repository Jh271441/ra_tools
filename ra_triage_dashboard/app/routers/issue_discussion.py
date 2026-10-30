"""Issue conversations are independent from tasks, Runs and display filters."""
from __future__ import annotations
import asyncio
from typing import List, Optional
from fastapi import APIRouter, File, Form, Request, UploadFile
from ..runtime import database
from ..support.common import _detail
from .case_comments import _public_review_comment, _create_review_comment_record, _create_comment_with_attachments

router = APIRouter()

@router.get("/api/cases/{issue_id}/discussion")
async def list_issue_discussion(issue_id: str):
    if await asyncio.to_thread(database.get_issue, issue_id) is None:
        raise _detail(404, "Issue 不存在。 / Issue not found.")
    comments = await asyncio.to_thread(database.list_issue_discussion, issue_id)
    count = await asyncio.to_thread(database.issue_discussion_count, issue_id)
    return {"comments": [_public_review_comment(item) for item in comments], "count": count}

@router.post("/api/cases/{issue_id}/discussion")
async def post_issue_discussion(issue_id: str, request: Request):
    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise _detail(400, "评论请求必须是 JSON 对象。 / Provide a JSON object.")
    if not isinstance(body, dict):
        raise _detail(400, "评论请求必须是 JSON 对象。 / Provide a JSON object.")
    return await _create_review_comment_record(issue_id, request, body, issue_discussion=True)

@router.post("/api/cases/{issue_id}/discussion-with-attachments")
async def post_issue_discussion_with_attachments(issue_id: str, request: Request,
        payload: str = Form(...), attachments: Optional[List[UploadFile]] = File(None)):
    return await _create_comment_with_attachments(issue_id, request, payload, attachments, issue_discussion=True)
