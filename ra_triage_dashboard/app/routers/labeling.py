"""Independent RA Case-labeling APIs."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import openpyxl
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response

from ..auth import request_identity
from ..case_media import empty_case_media
from ..db import LabelAnnotationConflictError
from ..review_mentions import extract_review_mentions, notification_recipients
from ..review_workflow import resolve_expected_output
from ..runtime import _public_path, database, review_notification_dispatcher, settings
from ..support.baselines import resolve_request_baseline_scopes
from ..support.catalogs import (
    _normalise_missing_evidence,
    _normalise_review_excluded,
    _normalise_review_tags,
    _review_tag_catalog,
)
from ..support.common import _as_text, _detail
from ..support.external_links import _voyager_issue_url
from ..support.identity import _admin_identity
from ..support.attachments import _store_comment_attachments, _store_review_attachments
from ..work_split import distribute_issue_ids, normalize_overlap_ratio
from .case_comments import _public_review_comment

router = APIRouter()
_COMMENT_ATTACHMENT_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]{1,80}$")


def _public_label_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(attachment.get("id") or ""),
        "media_type": str(attachment.get("media_type") or ""),
        "size_bytes": int(attachment.get("size_bytes") or 0),
        "width": int(attachment.get("width") or 0),
        "height": int(attachment.get("height") or 0),
        "url": _public_path(
            f"/api/labeling/attachments/{attachment.get('id') or ''}"
        ),
    }


def _public_label_case(label_case: dict[str, Any]) -> dict[str, Any]:
    public = dict(label_case)
    revisions = []
    for revision in public.get("revisions") or []:
        item = dict(revision)
        item["attachments"] = [
            _public_label_attachment(attachment)
            for attachment in item.get("attachments") or []
        ]
        revisions.append(item)
    public["revisions"] = revisions
    by_id = {int(item["id"]): item for item in revisions}
    resolution = dict(public.get("resolution") or {})
    if resolution.get("result_revision"):
        result_id = int(resolution["result_revision"]["id"])
        resolution["result_revision"] = by_id.get(
            result_id, resolution["result_revision"]
        )
    resolution["heads"] = [
        by_id.get(int(item["id"]), item) for item in resolution.get("heads") or []
    ]
    public["resolution"] = resolution
    return public


def _public_label_revision(revision: dict[str, Any]) -> dict[str, Any]:
    public = dict(revision)
    public["attachments"] = [
        _public_label_attachment(attachment)
        for attachment in public.get("attachments") or []
    ]
    if isinstance(public.get("label_case"), dict):
        public["label_case"] = _public_label_case(public["label_case"])
    return public


def _labeling_actor(request: Request) -> tuple[str, str, bool]:
    identity = request_identity(request, settings)
    role = (
        database.access_role(identity.username)
        if identity.verified and identity.username
        else ""
    )
    if not identity.verified or not identity.username or role != "admin":
        raise _detail(403, "Case 标注内测仅限 Dashboard 管理员。")
    return identity.username, identity.source, True


async def _require_labeling_admin(request: Request) -> None:
    await asyncio.to_thread(_admin_identity, request)


async def _active_labeling_scopes(scopes: list[str]) -> list[str]:
    active = set(await asyncio.to_thread(database.active_labeling_scopes))
    return [scope for scope in scopes if scope in active]


async def _require_active_labeling_issue(issue_id: str) -> dict[str, Any]:
    issue = await asyncio.to_thread(database.get_issue, issue_id)
    if issue is None:
        raise _detail(404, "Issue 不存在。")
    active = set(await asyncio.to_thread(database.active_labeling_scopes))
    if str(issue.get("baseline_scope") or "") not in active:
        raise _detail(409, "该数据集的 Case 标注迁移尚未激活。")
    return issue


async def _require_active_gt_export_batch(batch_id: str) -> dict[str, Any]:
    batch = await asyncio.to_thread(database.get_label_gt_export_batch, batch_id)
    if batch is None:
        raise _detail(404, "GT 更新导出批次不存在。")
    scopes = list(batch["baseline_scopes"])
    active_scopes = await _active_labeling_scopes(scopes)
    if not scopes or set(active_scopes) != set(scopes):
        raise _detail(409, "该导出批次包含已暂停或未激活的数据集。")
    return batch


def _labeling_payload(body: dict[str, Any]) -> dict[str, Any]:
    tags = body.get("tags") or []
    evidence = body.get("evidence_gaps") or []
    if not isinstance(tags, list) or not isinstance(evidence, list):
        raise _detail(400, "tags 和 evidence_gaps 必须是数组。")
    tags = _normalise_review_tags(tags)
    evidence = _normalise_missing_evidence(evidence)
    try:
        expected_output = resolve_expected_output(
            body.get("expected_output"), tags, _review_tag_catalog()
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {
        "expected_output": expected_output,
        "tags": tags,
        "evidence_gaps": evidence,
        "rationale": _as_text(body.get("rationale")),
        "is_excluded": _normalise_review_excluded(body.get("is_excluded", False)),
    }


@router.get("/api/labeling/tasks")
async def list_labeling_tasks(request: Request, baselines: str = "") -> dict[str, Any]:
    await _require_labeling_admin(request)
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = await _active_labeling_scopes(scopes)
    return {
        "items": (
            await asyncio.to_thread(database.list_labeling_tasks, scopes)
            if scopes else []
        ),
        "baseline_scopes": scopes,
    }


@router.post("/api/labeling/tasks")
async def create_labeling_task(request: Request) -> dict[str, Any]:
    identity = await asyncio.to_thread(_admin_identity, request)
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "任务请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "任务请求必须是 JSON 对象。")
    raw_issue_ids = body.get("issue_ids") or []
    if not isinstance(raw_issue_ids, list):
        raise _detail(400, "issue_ids 必须是数组。")
    issue_ids = list(dict.fromkeys(_as_text(value) for value in raw_issue_ids))
    issue_ids = [value for value in issue_ids if value]
    if len(issue_ids) > 5000:
        raise _detail(400, "单个标注任务最多包含 5000 个 Issue。")
    assignees = body.get("assignees") or []
    if not issue_ids or not isinstance(assignees, list) or not assignees:
        raise _detail(400, "任务必须包含 Issue 和标注人。")
    try:
        reviewers_per_issue = int(body.get("reviewers_per_issue") or 1)
        seed = int(body["seed"]) if body.get("seed") not in (None, "") else None
        overlap_ratio = normalize_overlap_ratio(
            body.get("overlap_ratio"), reviewers_per_issue=reviewers_per_issue
        )
        assignments = distribute_issue_ids(
            issue_ids,
            assignees,
            seed=seed,
            reviewers_per_issue=reviewers_per_issue,
            overlap_ratio=overlap_ratio,
        )
        scope_values = {
            str((await asyncio.to_thread(database.get_issue, issue_id) or {}).get("baseline_scope") or "")
            for issue_id in issue_ids
        }
        if len(scope_values) != 1 or "" in scope_values:
            raise ValueError("一个标注任务只能包含一个已注册数据集。")
        if next(iter(scope_values)) not in set(
            await asyncio.to_thread(database.active_labeling_scopes)
        ):
            raise ValueError("该数据集的 Case 标注迁移尚未激活。")
        workset = await asyncio.to_thread(
            database.create_review_workset,
            baseline_scope=next(iter(scope_values)),
            issue_ids=issue_ids,
            name=_as_text(body.get("name")) or f"标注任务 {len(issue_ids)}",
            selection_source_run_id=_as_text(body.get("selection_source_run_id")),
            source_filter=body.get("source_filter") if isinstance(body.get("source_filter"), dict) else {},
            created_by=identity.username,
            created_by_source=identity.source,
            created_by_verified=True,
        )
        task = await asyncio.to_thread(
            database.create_labeling_task,
            workset_id=workset["id"],
            assignments=assignments,
            created_by=identity.username,
            seed=seed,
            reviewers_per_issue=reviewers_per_issue,
            overlap_ratio=overlap_ratio,
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {
        "task": task,
        "workset": workset,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.get("/api/labeling/cases")
async def list_labeling_cases(
    request: Request,
    baselines: str = "",
    task_id: str = "",
    q: str = "",
    status: str = "all",
    author: str = "",
    exclusion: str = "all",
    label: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    await _require_labeling_admin(request)
    normalized_status = _as_text(status).lower() or "all"
    if normalized_status not in {"all", "pending", "resolved", "conflict"}:
        raise _detail(400, "标注状态不合法。")
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = await _active_labeling_scopes(scopes)
    normalized_task_id = _as_text(task_id)
    if normalized_task_id:
        tasks = (
            await asyncio.to_thread(database.list_labeling_tasks, scopes)
            if scopes else []
        )
        if not any(task["id"] == normalized_task_id for task in tasks):
            raise _detail(404, "标注任务不在当前已激活的数据集中。")
    normalized_author = _as_text(author).strip().lower()
    normalized_exclusion = (_as_text(exclusion).lower() or "all")
    if normalized_exclusion not in {"all", "excluded", "active"}:
        raise _detail(400, "排除筛选不合法。")
    normalized_label = _as_text(label).strip()
    try:
        result = await asyncio.to_thread(
            database.list_labeling_cases,
            baseline_scopes=scopes,
            task_id=normalized_task_id,
            search=_as_text(q),
            status=normalized_status,
            author=normalized_author,
            exclusion=normalized_exclusion,
            expected_output=normalized_label,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    for item in result["items"]:
        item["thumbnail_url"] = _public_path(
            f"/api/case-thumbnails/{item['issue_id']}"
        )
        item["voyager_issue_url"] = _voyager_issue_url(item["issue_id"])
    result["filters"] = {
        "baseline_scopes": scopes,
        "task_id": _as_text(task_id),
        "q": _as_text(q),
        "status": normalized_status,
        "author": normalized_author,
        "exclusion": normalized_exclusion,
        "label": normalized_label,
    }
    return result


@router.get("/api/labeling/cases/{issue_id}")
async def get_labeling_case(
    issue_id: str,
    request: Request,
    task_id: str = "",
) -> dict[str, Any]:
    await _require_labeling_admin(request)
    issue = await _require_active_labeling_issue(issue_id)
    scopes = resolve_request_baseline_scopes("", request=request)
    if scopes and str(issue.get("baseline_scope") or "") not in scopes:
        raise _detail(404, "Issue 不在当前数据集。")
    cases = await asyncio.to_thread(database.label_cases_for_issue, issue_id, _as_text(task_id))
    detailed_cases = []
    for item in cases:
        detail = await asyncio.to_thread(database.get_label_case, item["id"])
        detailed_cases.append(_public_label_case(detail or item))
    comments = await asyncio.to_thread(
        database.list_label_comments,
        issue_id=issue_id,
        task_id=_as_text(task_id),
    )
    assets, camera = empty_case_media(issue_id)
    return {
        "issue_id": issue_id,
        "baseline_scope": str(issue.get("baseline_scope") or ""),
        "title": str(issue.get("title") or ""),
        "scenario": str(issue.get("scenario") or ""),
        "summary": str(issue.get("summary") or ""),
        "gt_label": str(issue.get("gt_label") or ""),
        "gt_source": str(issue.get("gt_source") or ""),
        "trail_url": str(issue.get("trail_url") or ""),
        "voyager_issue_url": _voyager_issue_url(issue_id),
        "label_cases": detailed_cases,
        "comments": [_public_label_comment(comment) for comment in comments],
        "task_id": _as_text(task_id),
        "assets": assets,
        "camera": camera,
        "media_status": "pending",
    }


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
    await _require_labeling_admin(request)
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
    if task_id:
        tasks = await asyncio.to_thread(
            database.list_labeling_tasks, [str(issue.get("baseline_scope") or "")]
        )
        if not any(task["id"] == task_id for task in tasks):
            raise _detail(404, "标注任务不在当前已激活的数据集中。")
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
        if parent is None or parent_link is None:
            raise _detail(404, "回复的评论不存在。")
        if str(parent.get("issue_id") or "") != issue_id:
            raise _detail(400, "只能回复当前 Case 的标注讨论。")
        model_run_id = str(parent.get("model_run_id") or "")
        source_run_id = str(parent_link.get("source_run_id") or "")
        if not task_id:
            task_id = str(parent_link.get("task_id") or "")
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
            model_run_id=model_run_id,
            body=text,
            author=actor,
            author_source=actor_source,
            author_verified=actor_verified,
            mentions=mentions,
            notification_recipients=queued_recipients,
            reply_to_id=reply_to_id,
            attachments=attachments,
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
    issue_id: str, request: Request, task_id: str = ""
) -> dict[str, Any]:
    await _require_labeling_admin(request)
    await _require_active_labeling_issue(issue_id)
    comments = await asyncio.to_thread(
        database.list_label_comments,
        issue_id=issue_id,
        task_id=_as_text(task_id),
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
    await _require_labeling_admin(request)
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


@router.post("/api/labeling/label-cases/{label_case_id}/adjudications")
async def adjudicate_label_case(label_case_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "裁决请求必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "裁决请求必须是 JSON 对象。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _labeling_actor, request
    )
    current_case = await asyncio.to_thread(database.get_label_case, label_case_id)
    if current_case is None:
        raise _detail(404, "标注 Case 不存在。")
    await _require_active_labeling_issue(current_case["issue_id"])
    payload = _labeling_payload(body)
    raw_sources = body.get("source_revision_ids") or []
    if not isinstance(raw_sources, list):
        raise _detail(400, "source_revision_ids 必须是数组。")
    try:
        source_ids = [int(value) for value in raw_sources]
        raw_previous = body.get("expected_previous_resolution_id")
        expected_previous = (
            None if raw_previous in (None, "", 0, "0") else int(raw_previous)
        )
    except (TypeError, ValueError) as exc:
        raise _detail(400, "裁决版本参数不合法。") from exc
    try:
        label_case = await asyncio.to_thread(
            database.adjudicate_label_case,
            label_case_id=label_case_id,
            source_revision_ids=source_ids,
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
            expected_previous_resolution_id=expected_previous,
            **payload,
        )
    except LabelAnnotationConflictError as exc:
        raise _detail(409, str(exc))
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {
        "label_case": _public_label_case(label_case),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.get("/api/labeling/gt-candidates")
async def get_gt_candidates(request: Request, baselines: str = "") -> dict[str, Any]:
    await _require_labeling_admin(request)
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    scopes = await _active_labeling_scopes(scopes)
    items = await asyncio.to_thread(database.label_gt_candidates, scopes)
    return {
        "items": items,
        "ready_count": sum(item["status"] == "ready" for item in items),
        "conflict_count": sum(item["status"] != "ready" for item in items),
        "baseline_scopes": scopes,
    }


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
    scopes = resolve_request_baseline_scopes(
        _as_text(body.get("baselines")), request=request
    )
    scopes = await _active_labeling_scopes(scopes)
    if not scopes:
        raise _detail(409, "当前选择的数据集尚未激活 Case 标注迁移。")
    issue_ids = body.get("issue_ids") or []
    if not isinstance(issue_ids, list):
        raise _detail(400, "issue_ids 必须是数组。")
    preview = await asyncio.to_thread(
        database.create_label_gt_export_preview,
        baseline_scopes=scopes,
        issue_ids=[_as_text(value) for value in issue_ids],
        created_by=actor,
        created_by_source=actor_source,
        created_by_verified=actor_verified,
    )
    if not preview["item_count"]:
        raise _detail(400, "当前没有已解决且需要更新的 GT 候选。")
    return {
        "preview": preview,
        "download_url": _public_path(f"/api/labeling/gt-exports/{preview['id']}"),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.get("/api/labeling/gt-export-previews/{batch_id}")
async def get_gt_export_preview(batch_id: str, request: Request) -> dict[str, Any]:
    await _require_labeling_admin(request)
    batch = await _require_active_gt_export_batch(batch_id)
    return {"preview": batch}


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
