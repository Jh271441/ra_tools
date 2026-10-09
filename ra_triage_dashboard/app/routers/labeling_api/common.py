"""Labeling common HTTP contracts."""
from __future__ import annotations
from typing import Any
from fastapi import Request
from ...support.identity import _admin_identity
from ...support.common import _as_text
from ...support.catalogs import _csv_filter_values
from ...support.common import _detail
from ...support.catalogs import _normalise_missing_evidence
from ...support.catalogs import _normalise_review_excluded
from ...support.catalogs import _normalise_review_tags
from ...runtime import _public_path
from ...support.catalogs import _review_tag_catalog
from ...support.identity import _writer_identity
import asyncio
from ...runtime import database
import re
from ...auth import request_identity
from ...review_workflow import resolve_expected_output
from ...runtime import settings

_COMMENT_ATTACHMENT_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]{1,80}$")


def _labeling_filter_values(
    value: Any,
    *,
    allowed: set[str] | None = None,
    error: str = "筛选值不合法。",
    lower: bool = False,
) -> list[str]:
    raw_values = (
        [_as_text(item).strip() for item in value]
        if isinstance(value, (list, tuple, set))
        else _csv_filter_values(_as_text(value))
    )
    values = list(dict.fromkeys(item for item in raw_values if item and item != "all"))
    if lower:
        values = list(dict.fromkeys(item.lower() for item in values))
    if allowed is not None and any(item not in allowed for item in values):
        raise _detail(400, error)
    return values

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
    identity = _writer_identity(request)
    return identity.username, identity.source, True

def _labeling_snapshot_actor(request: Request) -> tuple[str, str, bool]:
    identity = request_identity(request, settings)
    role = (
        database.access_role(identity.username)
        if identity.verified and identity.username
        else ""
    )
    if not identity.verified or not identity.username or role not in {"writer", "admin"}:
        raise _detail(403, "保存 Label snapshot 仅限 Dashboard writer 或管理员。")
    return identity.username, identity.source, True

def _snapshot_allow_partial(body: dict[str, Any]) -> bool:
    value = body.get("allow_partial", False)
    if type(value) is not bool:
        raise _detail(400, "allow_partial 必须是 JSON boolean。")
    return value

async def _require_labeling_admin(request: Request) -> None:
    await asyncio.to_thread(_admin_identity, request)

async def _require_labeling_writer(request: Request):
    return await asyncio.to_thread(_writer_identity, request)

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
