"""Author/admin comment editing, tombstones and private change history."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request

from ..db_parts.comment_mutations import CommentConflictError, CommentMissingError
from ..review_mentions import extract_review_mentions
from ..runtime import database, intent_dataset_registry
from ..support.common import _detail
from ..support.identity import _intent_identity, _writer_identity
from .case_comments import _public_review_comment

router = APIRouter()


async def _comment_actor(request: Request, kind: str, dataset_id: str, case_id: str):
    if kind == "intent":
        identity = await asyncio.to_thread(_intent_identity, request, "annotate")
        try:
            exists = intent_dataset_registry.has_case(dataset_id, case_id)
        except KeyError:
            exists = False
        if not exists:
            raise _detail(404, "Case 不在该数据集中。 / Case not found in this dataset.")
        admin = await asyncio.to_thread(database.intent_permission, identity.username) == "manage"
    else:
        identity = await asyncio.to_thread(_writer_identity, request)
        admin = await asyncio.to_thread(database.access_role, identity.username) == "admin"
    return identity, admin


async def _change(request: Request, *, kind: str, issue_id: str, comment_id: int,
                  dataset_id: str = "", delete: bool = False) -> dict[str, Any]:
    identity, admin = await _comment_actor(request, kind, dataset_id, issue_id)
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise _detail(413, "评论请求过大。 / Comment request is too large.")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError()
        version = payload.get("expected_version")
        if type(version) is not int or version < 1:
            raise ValueError()
    except (ValueError, TypeError, UnicodeDecodeError):
        raise _detail(400, "请提供评论内容和有效版本。 / Provide a comment body and a valid version.")
    try:
        mentions = [] if delete else extract_review_mentions(payload.get("body", ""))
        if mentions:
            enabled = await asyncio.to_thread(database.enabled_mention_recipients, mentions)
            if any(name not in enabled for name in mentions):
                raise ValueError("评论包含目录外的 @ 用户。 / The comment mentions a user outside the directory.")
        await asyncio.to_thread(database.mutate_comment, kind=kind, comment_id=comment_id,
            issue_id=issue_id, dataset_id=dataset_id, actor=identity.username,
            actor_source=identity.source, actor_verified=identity.verified, is_admin=admin,
            expected_version=version, body=payload.get("body"), delete=delete, mentions=mentions)
    except CommentMissingError as exc:
        raise _detail(404, str(exc))
    except PermissionError as exc:
        raise _detail(403, str(exc))
    except CommentConflictError as exc:
        raise _detail(409, str(exc))
    except ValueError as exc:
        raise _detail(400, str(exc))
    comment = await asyncio.to_thread(database.get_intent_comment, dataset_id, issue_id, comment_id) if kind == "intent" else await asyncio.to_thread(database.get_review_comment, comment_id)
    return {"comment": comment if kind == "intent" else _public_review_comment(comment),
            "notification": {"queued": []}}


async def _history(request: Request, *, kind: str, issue_id: str, comment_id: int,
                   dataset_id: str = ""):
    identity, admin = await _comment_actor(request, kind, dataset_id, issue_id)
    try:
        items = await asyncio.to_thread(database.comment_change_history, kind=kind,
            comment_id=comment_id, issue_id=issue_id, dataset_id=dataset_id,
            actor=identity.username, actor_verified=identity.verified, is_admin=admin)
    except CommentMissingError as exc:
        raise _detail(404, str(exc))
    except PermissionError as exc:
        raise _detail(403, str(exc))
    except CommentConflictError as exc:
        raise _detail(409, str(exc))
    return {"items": items, "count": len(items)}


@router.patch("/api/cases/{issue_id}/comments/{comment_id}")
async def edit_comment(issue_id: str, comment_id: int, request: Request):
    return await _change(request, kind="review", issue_id=issue_id, comment_id=comment_id)


@router.delete("/api/cases/{issue_id}/comments/{comment_id}")
async def delete_comment(issue_id: str, comment_id: int, request: Request):
    return await _change(request, kind="review", issue_id=issue_id, comment_id=comment_id, delete=True)


@router.get("/api/cases/{issue_id}/comments/{comment_id}/history")
async def comment_history(issue_id: str, comment_id: int, request: Request):
    return await _history(request, kind="review", issue_id=issue_id, comment_id=comment_id)


@router.patch("/api/intent-datasets/{dataset_id}/cases/{case_id}/comments/{comment_id}")
async def edit_intent_comment(dataset_id: str, case_id: str, comment_id: int, request: Request):
    return await _change(request, kind="intent", issue_id=case_id, dataset_id=dataset_id, comment_id=comment_id)


@router.delete("/api/intent-datasets/{dataset_id}/cases/{case_id}/comments/{comment_id}")
async def delete_intent_comment(dataset_id: str, case_id: str, comment_id: int, request: Request):
    return await _change(request, kind="intent", issue_id=case_id, dataset_id=dataset_id, comment_id=comment_id, delete=True)


@router.get("/api/intent-datasets/{dataset_id}/cases/{case_id}/comments/{comment_id}/history")
async def intent_comment_history(dataset_id: str, case_id: str, comment_id: int, request: Request):
    return await _history(request, kind="intent", issue_id=case_id, dataset_id=dataset_id, comment_id=comment_id)
