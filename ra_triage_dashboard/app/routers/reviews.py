from __future__ import annotations

from typing import Any, List, Optional, Union

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from ..http_support import *  # noqa: F401,F403
from ..runtime import *  # noqa: F401,F403

router = APIRouter()

@router.post("/api/review-tags")
async def create_review_tag(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "场景标签目录请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "场景标签目录请求必须是 JSON 对象。")
    label, hint, group, section = _validate_review_tag_input(body)
    actor, _, _ = await asyncio.to_thread(
        _action_actor, request, body.get("created_by")
    )
    if not actor:
        raise _detail(400, "无法确认场景标签目录创建人。")
    catalog = await asyncio.to_thread(_review_tag_catalog)
    if any(
        str(item.get("label")) == label and not bool(item.get("deleted"))
        for item in catalog
    ):
        raise _detail(409, "该场景标签标题已经存在。")
    try:
        item = await asyncio.to_thread(
            database.create_review_tag,
            label=label,
            hint=hint,
            section=section,
            group_key=group,
            created_by=actor,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    return {
        "item": _review_tag_payload(item),
        "review_tag_catalog": await asyncio.to_thread(_review_tag_catalog),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.put("/api/review-tags/{key:path}")
async def update_review_tag(key: str, request: Request) -> dict[str, Any]:
    normalized_key = _as_text(key).strip()
    if not normalized_key or len(normalized_key) > 160:
        raise _detail(400, "场景标签 key 不合法。")
    catalog = await asyncio.to_thread(_review_tag_catalog)
    current = next(
        (item for item in catalog if item["key"] == normalized_key),
        None,
    )
    if current is None:
        raise _detail(404, "场景标签目录项不存在。")
    if bool(current.get("deleted")):
        raise _detail(409, "该场景标签已经删除。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "场景标签目录请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "场景标签目录请求必须是 JSON 对象。")
    current_group = str(current.get("group") or "environment")
    current_section = str(current.get("section") or "scene")
    if current_group in REVIEW_TAG_MANAGED_GROUPS or current_section in {
        "scene",
        "interaction_decision",
        "egress",
    }:
        # Keep the tag on its axis; group may only move within managed axes.
        label, hint, group, section = _validate_review_tag_input(
            body,
            default_group=current_group if current_group in REVIEW_TAG_MANAGED_GROUPS else "environment",
        )
        # Editing a managed-axis tag must stay in the same section (axis).
        if current_section in {"scene", "interaction_decision", "egress"} and section != current_section:
            group = current_group
            section = current_section
    else:
        # Legacy built-ins keep section/group; only label/hint edit.
        label = _as_text(body.get("label"))
        hint = _as_text(body.get("hint"))
        group = current_group
        section = current_section
        if not label:
            raise _detail(400, "场景标签标题不能为空。")
        if len(label) > 48 or re.search(r"[\x00-\x1f\x7f]", label):
            raise _detail(400, "场景标签标题长度或字符不合法。")
        if len(hint) > 160 or re.search(r"[\x00-\x1f\x7f]", hint):
            raise _detail(400, "场景标签说明长度或字符不合法。")
    actor, _, _ = await asyncio.to_thread(
        _action_actor, request, body.get("updated_by")
    )
    if not actor:
        raise _detail(400, "无法确认场景标签目录编辑人。")
    if any(
        item["key"] != normalized_key
        and str(item.get("label")) == label
        and not bool(item.get("deleted"))
        for item in catalog
    ):
        raise _detail(409, "该场景标签标题已经存在。")
    try:
        item = await asyncio.to_thread(
            database.update_review_tag,
            key=normalized_key,
            label=label,
            hint=hint,
            section=section,
            group_key=group,
            updated_by=actor,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    payload = _review_tag_payload(item, builtin=bool(current.get("builtin")))
    payload["section"] = section
    payload["group"] = group
    return {
        "item": payload,
        "review_tag_catalog": await asyncio.to_thread(_review_tag_catalog),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.delete("/api/review-tags/{key:path}")
async def delete_review_tag(key: str, request: Request) -> dict[str, Any]:
    normalized_key = _as_text(key).strip()
    if not normalized_key or len(normalized_key) > 160:
        raise _detail(400, "场景标签 key 不合法。")
    catalog = await asyncio.to_thread(_review_tag_catalog)
    current = next(
        (item for item in catalog if item["key"] == normalized_key),
        None,
    )
    if current is None:
        raise _detail(404, "场景标签目录项不存在。")
    if bool(current.get("deleted")):
        raise _detail(409, "该场景标签已经删除。")
    actor, _, _ = await asyncio.to_thread(_action_actor, request, "")
    if not actor:
        raise _detail(400, "无法确认场景标签目录删除人。")
    try:
        item = await asyncio.to_thread(
            database.delete_review_tag,
            key=normalized_key,
            deleted_by=actor,
            label=str(current.get("label") or ""),
            hint=str(current.get("hint") or ""),
            section=str(current.get("section") or "scene"),
            group_key=str(current.get("group") or "environment"),
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    payload = _review_tag_payload(item, builtin=bool(current.get("builtin")))
    payload["deleted"] = True
    return {
        "item": payload,
        "review_tag_catalog": await asyncio.to_thread(_review_tag_catalog),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.post("/api/missing-evidence")
async def create_missing_evidence(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "缺失信息目录请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "缺失信息目录请求必须是 JSON 对象。")
    label = _as_text(body.get("label"))
    hint = _as_text(body.get("hint"))
    actor, _, _ = await asyncio.to_thread(
        _action_actor, request, body.get("created_by")
    )
    if not actor:
        raise _detail(400, "无法确认缺失信息目录创建人。")
    catalog = await asyncio.to_thread(_missing_evidence_catalog)
    if any(
        str(item["label"]) == label and not bool(item.get("deleted"))
        for item in catalog
    ):
        raise _detail(409, "该缺失信息标题已经存在于内置目录。")
    try:
        item = await asyncio.to_thread(
            database.create_missing_evidence,
            label=label,
            hint=hint,
            created_by=actor,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    item = {
        **item,
        "builtin": False,
        "deleted": not bool(item.get("active", 1)),
    }
    item.pop("active", None)
    return {
        "item": item,
        "missing_evidence_catalog": await asyncio.to_thread(_missing_evidence_catalog),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.put("/api/missing-evidence/{key:path}")
async def update_missing_evidence(key: str, request: Request) -> dict[str, Any]:
    normalized_key = _as_text(key).strip()
    if not normalized_key or len(normalized_key) > 160:
        raise _detail(400, "缺失信息 key 不合法。")
    catalog = await asyncio.to_thread(_missing_evidence_catalog)
    current = next(
        (item for item in catalog if item["key"] == normalized_key),
        None,
    )
    if current is None:
        raise _detail(404, "缺失信息目录项不存在。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "缺失信息目录请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "缺失信息目录请求必须是 JSON 对象。")
    label = _as_text(body.get("label"))
    hint = _as_text(body.get("hint"))
    actor, _, _ = await asyncio.to_thread(
        _action_actor, request, body.get("updated_by")
    )
    if not actor:
        raise _detail(400, "无法确认缺失信息目录编辑人。")
    if any(
        item["key"] != normalized_key
        and not bool(item.get("deleted"))
        and str(item["label"]) == label
        for item in catalog
    ):
        raise _detail(409, "该缺失信息标题已经存在。")
    try:
        item = await asyncio.to_thread(
            database.update_missing_evidence,
            key=normalized_key,
            label=label,
            hint=hint,
            updated_by=actor,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    item = {
        **item,
        "builtin": bool(current.get("builtin")),
        "deleted": not bool(item.get("active", 1)),
    }
    item.pop("active", None)
    return {
        "item": item,
        "missing_evidence_catalog": await asyncio.to_thread(_missing_evidence_catalog),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.delete("/api/missing-evidence/{key:path}")
async def delete_missing_evidence(key: str, request: Request) -> dict[str, Any]:
    normalized_key = _as_text(key).strip()
    if not normalized_key or len(normalized_key) > 160:
        raise _detail(400, "缺失信息 key 不合法。")
    catalog = await asyncio.to_thread(_missing_evidence_catalog)
    current = next(
        (item for item in catalog if item["key"] == normalized_key),
        None,
    )
    if current is None:
        raise _detail(404, "缺失信息目录项不存在。")
    if bool(current.get("deleted")):
        raise _detail(409, "该缺失信息已经删除。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    actor, _, _ = await asyncio.to_thread(
        _action_actor, request, body.get("deleted_by")
    )
    if not actor:
        raise _detail(400, "无法确认缺失信息目录删除人。")
    try:
        item = await asyncio.to_thread(
            database.delete_missing_evidence,
            key=normalized_key,
            label=str(current.get("label") or ""),
            hint=str(current.get("hint") or ""),
            deleted_by=actor,
        )
    except ValueError as exc:
        raise _detail(409, str(exc))
    item = {
        **item,
        "builtin": bool(current.get("builtin")),
        "deleted": True,
    }
    item.pop("active", None)
    return {
        "item": item,
        "missing_evidence_catalog": await asyncio.to_thread(_missing_evidence_catalog),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }



@router.get("/api/review-attachments/{attachment_id}")
async def get_review_attachment(attachment_id: str) -> FileResponse:
    attachment = await asyncio.to_thread(
        database.get_review_attachment, attachment_id
    )
    if attachment is None:
        raise _detail(404, "Review 截图不存在。")
    root = settings.review_attachments_dir.resolve()
    path = (root / attachment["stored_name"]).resolve()
    if root not in path.parents or not await asyncio.to_thread(path.is_file):
        raise _detail(404, "Review 截图文件不存在。")
    return FileResponse(
        path,
        media_type=attachment["media_type"],
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )
