"""Labeling comments HTTP contracts."""
from __future__ import annotations
from fastapi import APIRouter
from typing import Any
from fastapi import File
from fastapi import Form
from typing import List
from typing import Optional
from pathlib import Path
from fastapi import Request
from fastapi import UploadFile
from ...support.common import _as_text
from ...support.common import _detail
from ..case_comments import _public_review_comment
from ...support.attachments import _store_comment_attachments
import asyncio
from ...runtime import database
from ...review_mentions import extract_review_mentions
import json
from ...review_mentions import notification_recipients
from ...runtime import review_notification_dispatcher
from ...runtime import settings
from .common import _labeling_actor, _require_active_labeling_issue, _require_labeling_writer
from .common import _COMMENT_ATTACHMENT_TOKEN_RE

router = APIRouter()


def _public_label_comment(comment: dict[str, Any]) -> dict[str, Any]:
    public = _public_review_comment(comment)
    public["label_task_id"] = str(comment.get("label_task_id") or "")
    public["source_run_id"] = str(comment.get("source_run_id") or "")
    return public

async def _create_label_comment_record(
    issue_id: str,
    request: Request,
    body: dict[str, Any],
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    await _require_labeling_writer(request)
    issue = await _require_active_labeling_issue(issue_id)
    text = _as_text(body.get("body")).strip()
    if not text:
        raise _detail(400, "评论内容不能为空。")
    if len(text) > 3500:
        raise _detail(400, "评论内容不能超过 3500 个字符。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_actor, request
    )
    task_id = _as_text(body.get("task_id"))
    discussion_channel = "campaign" if task_id else "case"
    if task_id:
        tasks = await asyncio.to_thread(
            database.list_labeling_tasks, [str(issue.get("baseline_scope") or "")]
        )
        if not any(task["id"] == task_id for task in tasks):
            raise _detail(404, "标注任务不在当前已激活的数据集中。")
        campaign_detail = await asyncio.to_thread(database.get_campaign, task_id, page=1, page_size=1)
        campaign = (campaign_detail or {}).get("campaign") or {}
        if campaign and (
            campaign.get("purpose") not in {None, "labeling"}
            or campaign.get("lifecycle") != "active"
            or campaign.get("legacy_read_only")
        ):
            raise _detail(409, "该 Campaign 当前只读，不能新增标注讨论。")
    raw_reply_to_id = body.get("reply_to_id")
    reply_to_id: int | None = None
    parent: dict[str, Any] | None = None
    parent_link: dict[str, Any] | None = None
    model_run_id = ""
    source_run_id = ""
    if raw_reply_to_id not in (None, "", 0, "0"):
        try:
            reply_to_id = int(raw_reply_to_id)
        except (TypeError, ValueError) as exc:
            raise _detail(400, "reply_to_id 不合法。") from exc
        if reply_to_id <= 0:
            raise _detail(400, "reply_to_id 不合法。")
        parent = await asyncio.to_thread(database.get_review_comment, reply_to_id)
        parent_link = await asyncio.to_thread(
            database.get_label_comment_link, reply_to_id
        )
        if parent is None:
            raise _detail(404, "回复的评论不存在。")
        if str(parent.get("issue_id") or "") != issue_id:
            raise _detail(400, "只能回复当前 Case 的标注讨论。")
        parent_channel = str(parent.get("discussion_channel") or "legacy")
        if parent_channel == "case":
            if str(parent.get("baseline_scope") or "") != str(issue.get("baseline_scope") or ""):
                raise _detail(400, "只能回复当前 baseline scope 下的 Case 公共讨论。")
            discussion_channel = "case"
            task_id = ""
            model_run_id = ""
            source_run_id = ""
        elif parent_channel == "campaign":
            parent_campaign_id = str(parent.get("campaign_id") or "")
            if not parent_campaign_id or (task_id and task_id != parent_campaign_id):
                raise _detail(400, "只能回复当前 Campaign 下的标注讨论。")
            discussion_channel = "campaign"
            task_id = parent_campaign_id
            model_run_id = ""
            source_run_id = str((parent_link or {}).get("source_run_id") or "")
        else:
            raise _detail(400, "只能回复 Case 公共频道或 Labeling Campaign 频道。")
    if task_id and not source_run_id:
        campaign_detail = await asyncio.to_thread(database.get_campaign, task_id, page=1, page_size=1)
        source_run_id = str(((campaign_detail or {}).get("campaign") or {}).get("selection_source_run_id") or "")
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
    recipients = notification_recipients(enabled_recipients, author=actor)
    queued_recipients = (
        recipients if settings.dchat_notifications_enabled and actor_verified else []
    )
    states = await asyncio.to_thread(
        database.labeling_scope_states, [str(issue.get("baseline_scope") or "")]
    )
    policy_version = (
        str(states[0].get("policy_version") or "case-labeling-v1")
        if states
        else "case-labeling-v1"
    )
    try:
        comment = await asyncio.to_thread(
            database.create_review_comment,
            issue_id=issue_id,
            model_run_id="",
            body=text,
            author=actor,
            author_source=actor_source,
            author_verified=actor_verified,
            mentions=mentions,
            notification_recipients=queued_recipients,
            reply_to_id=reply_to_id,
            attachments=attachments,
            discussion_channel=discussion_channel,
            campaign_id=task_id,
            baseline_scope=str(issue.get("baseline_scope") or ""),
            require_existing_model_run=False,
        )
        await asyncio.to_thread(
            database.link_label_comment,
            comment_id=int(comment["id"]),
            task_id=task_id,
            source_run_id=source_run_id or model_run_id,
            policy_version=policy_version,
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if queued_recipients:
        review_notification_dispatcher.wake()
    comments = await asyncio.to_thread(
        database.list_label_comments, issue_id=issue_id, task_id=task_id
    )
    linked = dict(comment)
    linked["label_task_id"] = task_id
    linked["source_run_id"] = source_run_id or model_run_id
    return {
        "comment": _public_label_comment(linked),
        "comment_count": len(comments),
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

@router.get("/api/labeling/cases/{issue_id}/comments")
async def list_labeling_comments(
    issue_id: str, request: Request, task_id: str = "", channel: str = "both"
) -> dict[str, Any]:
    await _require_labeling_writer(request)
    await _require_active_labeling_issue(issue_id)
    comments = await asyncio.to_thread(
        database.list_label_comments,
        issue_id=issue_id,
        task_id=_as_text(task_id),
        discussion_channel=_as_text(channel or "both"),
    )
    return {
        "comments": [_public_label_comment(comment) for comment in comments],
        "count": len(comments),
        "task_id": _as_text(task_id),
    }

@router.post("/api/labeling/cases/{issue_id}/comments")
async def create_labeling_comment(issue_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "评论请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "评论请求必须是 JSON 对象。")
    return await _create_label_comment_record(issue_id, request, body)

@router.post("/api/labeling/cases/{issue_id}/comments-with-attachments")
async def create_labeling_comment_with_attachments(
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
        return await _create_label_comment_record(
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
                persisted = False
        if not persisted:
            for path in paths:
                await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
