from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from ..review_mentions import extract_review_mentions, notification_recipients
from ..runtime import database, review_notification_dispatcher, settings
from ..support.attachments import (
    _public_comment_attachment,
    _store_comment_attachments,
)
from ..support.common import _as_text, _detail
from ..support.identity import _action_actor

router = APIRouter()

_COMMENT_ATTACHMENT_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]{1,80}$")


def _public_review_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        **comment,
        "attachments": [
            _public_comment_attachment(attachment)
            for attachment in comment.get("attachments", [])
        ],
    }


@router.get("/api/cases/{issue_id}/comments")
async def list_review_comments(
    issue_id: str, model_run_id: str = ""
) -> dict[str, Any]:
    if await asyncio.to_thread(database.get_issue, issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    comments = await asyncio.to_thread(
        database.list_review_comments,
        issue_id=issue_id,
        model_run_id=str(model_run_id or "").strip(),
    )
    count = await asyncio.to_thread(
        database.review_comment_count,
        issue_id=issue_id,
        model_run_id=str(model_run_id or "").strip(),
    )
    return {
        "comments": [_public_review_comment(comment) for comment in comments],
        "count": count,
    }


@router.post("/api/cases/{issue_id}/comments")
async def create_review_comment(issue_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "评论请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "评论请求必须是 JSON 对象。")
    return await _create_review_comment_record(issue_id, request, body)


@router.post("/api/cases/{issue_id}/comments-with-attachments")
async def create_review_comment_with_attachments(
    issue_id: str,
    request: Request,
    payload: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
) -> dict[str, Any]:
    try:
        body = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, "评论 payload 不是合法 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "评论 payload 必须是 JSON 对象。")
    uploads = attachments or []
    raw_tokens = body.get("attachment_tokens", [])
    if not isinstance(raw_tokens, list) or len(raw_tokens) != len(uploads):
        raise _detail(400, "评论图片占位符与上传文件不匹配。")
    tokens = [str(token or "").strip() for token in raw_tokens]
    if (
        len(set(tokens)) != len(tokens)
        or any(not _COMMENT_ATTACHMENT_TOKEN_RE.fullmatch(token) for token in tokens)
    ):
        raise _detail(400, "评论图片占位符不合法。")
    records: list[dict[str, Any]] = []
    paths: list[Path] = []
    try:
        records, paths = await _store_comment_attachments(uploads)
        text = _as_text(body.get("body"))
        for token, record in zip(tokens, records):
            placeholder = f"attachment:{token}"
            if placeholder not in text:
                raise _detail(400, "评论内容缺少已选图片的 Markdown 占位符。")
            text = text.replace(placeholder, f"attachment:{record['id']}")
        body["body"] = text
        return await _create_review_comment_record(
            issue_id,
            request,
            body,
            attachments=records,
        )
    except Exception:
        persisted = False
        if records:
            try:
                persisted = bool(
                    await asyncio.to_thread(
                        database.get_comment_attachment,
                        str(records[0]["id"]),
                    )
                )
            except Exception:
                persisted = True
        if not persisted:
            for path in paths:
                await asyncio.to_thread(path.unlink, missing_ok=True)
        raise


async def _create_review_comment_record(
    issue_id: str,
    request: Request,
    body: dict[str, Any],
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = _as_text(body.get("body")).strip()
    if not text:
        raise _detail(400, "评论内容不能为空。")
    if len(text) > 3500:
        raise _detail(400, "评论内容不能超过 3500 个字符。")
    model_run_id = _as_text(body.get("model_run_id")).strip()
    author, author_source, author_verified = await asyncio.to_thread(
        _action_actor, request, body.get("author")
    )
    if not author:
        raise _detail(400, "无法确认评论人。")
    raw_reply_to_id = body.get("reply_to_id")
    reply_to_id: int | None = None
    parent: dict[str, Any] | None = None
    if raw_reply_to_id not in (None, "", 0, "0"):
        try:
            reply_to_id = int(raw_reply_to_id)
        except (TypeError, ValueError) as exc:
            raise _detail(400, "reply_to_id 不合法。") from exc
        if reply_to_id <= 0:
            raise _detail(400, "reply_to_id 不合法。")
        parent = await asyncio.to_thread(database.get_review_comment, reply_to_id)
        if parent is None:
            raise _detail(404, "回复的评论不存在。")
        if (
            parent["issue_id"] != issue_id
            or str(parent.get("model_run_id") or "") != model_run_id
        ):
            raise _detail(400, "只能回复当前 Issue 与 Model Run 下的评论。")
    try:
        mentions = extract_review_mentions(text)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    requested_recipients = list(mentions)
    if parent and parent.get("author"):
        requested_recipients.append(str(parent["author"]).strip().lower())
    requested_recipients = list(dict.fromkeys(requested_recipients))
    enabled_recipients = await asyncio.to_thread(
        database.enabled_mention_recipients, requested_recipients
    )
    unsupported_mentions = [
        username for username in mentions if username not in enabled_recipients
    ]
    if unsupported_mentions:
        raise _detail(
            400,
            "以下用户不在可 @ / DChat 通知人员目录中："
            + "、".join(f"@{item}" for item in unsupported_mentions),
        )
    recipients = notification_recipients(enabled_recipients, author=author)
    queued_recipients = (
        recipients if settings.dchat_notifications_enabled and author_verified else []
    )
    try:
        comment = await asyncio.to_thread(
            database.create_review_comment,
            issue_id=issue_id,
            model_run_id=model_run_id,
            body=text,
            author=author,
            author_source=author_source,
            author_verified=author_verified,
            mentions=mentions,
            notification_recipients=queued_recipients,
            reply_to_id=reply_to_id,
            attachments=attachments,
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if queued_recipients:
        review_notification_dispatcher.wake()
    comment_count = await asyncio.to_thread(
        database.review_comment_count,
        issue_id=issue_id,
        model_run_id=model_run_id,
    )
    return {
        "comment": _public_review_comment(comment),
        "comment_count": comment_count,
        "notification": {
            "mentions": mentions,
            "queued": queued_recipients,
            "status": (
                "no_recipients"
                if not recipients
                else "queued"
                if queued_recipients
                else "disabled"
                if not settings.dchat_notifications_enabled
                else "unverified_identity"
            ),
        },
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.get("/api/comment-attachments/{attachment_id}")
async def get_comment_attachment(attachment_id: str) -> FileResponse:
    attachment = await asyncio.to_thread(
        database.get_comment_attachment, attachment_id
    )
    if attachment is None:
        raise _detail(404, "评论图片不存在。")
    root = settings.comment_attachments_dir.resolve()
    path = (root / attachment["stored_name"]).resolve()
    if root not in path.parents or not await asyncio.to_thread(path.is_file):
        raise _detail(404, "评论图片文件不存在。")
    return FileResponse(
        path,
        media_type=attachment["media_type"],
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )
