"""Read-only Campaign listing and guarded Campaign management APIs."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..db_parts.campaigns import CampaignConflictError, CampaignReadOnlyError
from ..review_mentions import extract_review_mentions, notification_recipients
from ..runtime import database, review_notification_dispatcher, settings
from ..support.baselines import resolve_request_baseline_scopes
from ..support.common import _as_text, _detail
from ..support.identity import _admin_identity
from .case_comments import _public_review_comment

router = APIRouter()


def _json_body(raw: bytes, *, maximum: int = 2 * 1024 * 1024) -> dict[str, Any]:
    if len(raw) > maximum:
        raise _detail(413, "Campaign 请求过大。")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "Campaign 请求必须是合法 JSON。") from exc
    if not isinstance(value, dict):
        raise _detail(400, "Campaign 请求必须是 JSON 对象。")
    return value


def _required_integer(body: dict[str, Any], key: str) -> int:
    value = body.get(key)
    if isinstance(value, bool):
        raise _detail(400, f"{key} 必须是正整数。")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _detail(400, f"{key} 必须是正整数。") from exc
    if result < 1:
        raise _detail(400, f"{key} 必须是正整数。")
    return result


def _idempotency_key(request: Request, body: dict[str, Any]) -> str:
    value = _as_text(request.headers.get("idempotency-key") or body.get("idempotency_key")).strip()
    if not value or len(value) > 160:
        raise _detail(400, "Idempotency-Key 必须为 1 到 160 个字符。")
    return value


def _campaign_admin(request: Request) -> tuple[str, str, bool]:
    identity = _admin_identity(request)
    return identity.username, identity.source, bool(identity.verified)


def _require_known_assignees(specs: list[dict[str, Any]]) -> None:
    allowed = {
        str(item.get("username") or "").strip().lower()
        for item in database.list_access_users()
        if item.get("enabled", True)
    }
    for spec in specs:
        for member in spec.get("members") or []:
            if not isinstance(member, dict):
                continue
            values = member.get("assignees", member.get("assignments", []))
            if not isinstance(values, list):
                continue
            for value in values:
                name = str(
                    value.get("assignee") or value.get("name") or ""
                    if isinstance(value, dict) else value or ""
                ).strip().lower()
                if name and name not in allowed:
                    raise _detail(400, f"Assignee 不在启用的 Dashboard 用户列表中：{name}")


async def _campaign_issue_exists(campaign_id: str, issue_id: str) -> bool:
    detail = await asyncio.to_thread(
        database.get_campaign, campaign_id, page=1, page_size=100, query=issue_id
    )
    return bool(detail and any(str(item.get("issue_id") or "") == issue_id for item in detail.get("issues", [])))


@router.get("/api/campaigns")
async def list_campaigns(
    request: Request,
    baselines: str = "",
    purpose: str = "",
    lifecycle: str = "all",
    group_id: str = "",
    include_legacy: bool = True,
    q: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    try:
        result = await asyncio.to_thread(
            database.list_campaigns,
            baseline_scopes=scopes,
            purpose=_as_text(purpose),
            lifecycle=_as_text(lifecycle or "all"),
            task_group_id=_as_text(group_id),
            include_legacy=bool(include_legacy),
            query=_as_text(q),
            page=max(1, int(page or 1)),
            page_size=max(1, min(int(page_size or 50), 100)),
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    result["change_revision"] = await asyncio.to_thread(database.change_revision)
    return result


@router.get("/api/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    page: int = 1,
    page_size: int = 50,
    assignee: str = "",
    state: str = "all",
    q: str = "",
) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(
            database.get_campaign,
            campaign_id,
            page=max(1, int(page or 1)),
            page_size=max(1, min(int(page_size or 50), 100)),
            assignee=_as_text(assignee),
            state=_as_text(state or "all"),
            query=_as_text(q),
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if result is None:
        raise _detail(404, "Campaign 不存在。")
    return result


@router.get("/api/campaigns/{campaign_id}/analysis")
async def campaign_analysis(
    campaign_id: str,
    page: int = 1,
    page_size: int = 100,
    q: str = "",
    assignee: str = "",
    state: str = "all",
) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(
            database.get_campaign,
            campaign_id,
            page=max(1, int(page or 1)),
            page_size=max(1, min(int(page_size or 100), 100)),
            query=_as_text(q),
            assignee=_as_text(assignee),
            state=_as_text(state or "all"),
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if result is None:
        raise _detail(404, "Campaign 不存在。")
    campaign = result.get("campaign") or {}
    if campaign.get("purpose") != "labeling":
        raise _detail(400, "Label Analysis 只适用于 Labeling Campaign。")
    return {
        "campaign_id": campaign_id,
        "reference": {
            "type": campaign.get("reference_type"),
            "id": campaign.get("reference_id"),
            "sha256": campaign.get("reference_sha256"),
            "baseline_scopes": campaign.get("baseline_scopes", []),
        },
        "progress": result.get("progress") or {},
        "assignees": result.get("assignees") or [],
        "items": result.get("issues") or [],
        "total": result.get("total", 0),
        "page": result.get("page", 1),
        "page_size": result.get("page_size", 100),
        "page_count": result.get("page_count", 1),
        "close_snapshot": result.get("close_snapshot"),
    }


@router.get("/api/campaigns/{campaign_id}/analysis/export.csv")
async def export_campaign_label_analysis(
    campaign_id: str,
    request: Request,
    q: str = "",
    assignee: str = "",
    state: str = "all",
) -> Response:
    _campaign_admin(request)
    try:
        detail = await asyncio.to_thread(
            database.campaign_label_analysis_export,
            campaign_id,
            query=_as_text(q),
            assignee=_as_text(assignee),
            state=_as_text(state or "all"),
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if detail is None:
        raise _detail(404, "Campaign 不存在。")
    campaign = detail.get("campaign") or {}
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "campaign_id", "workset_id", "baseline_scopes", "reference_type",
        "reference_id", "issue_id", "title", "scenario", "reference_label",
        "reference_relation", "expected_output", "tags", "evidence_gaps",
        "is_excluded", "submitted", "required", "state", "assignees",
        "author", "revision_kind", "rationale", "revision_id", "created_at",
    ])

    def safe_cell(value: Any) -> str:
        text = str(value or "")
        if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
            return "'" + text
        return text

    for item in detail.get("issues") or []:
        revisions = item.get("label_revisions") or [{}]
        assignees = ", ".join(str(value.get("assignee") or "") for value in item.get("assignments") or [])
        for revision in revisions:
            writer.writerow([
                safe_cell(campaign.get("id")),
                safe_cell(campaign.get("workset_id")),
                safe_cell(",".join(campaign.get("baseline_scopes") or [])),
                safe_cell(item.get("reference_type") or campaign.get("reference_type")),
                safe_cell(item.get("reference_id") or campaign.get("reference_id")),
                safe_cell(item.get("issue_id")),
                safe_cell(item.get("title")),
                safe_cell(item.get("scenario")),
                safe_cell(item.get("reference_label")),
                safe_cell(item.get("reference_relation")),
                safe_cell(revision.get("expected_output") if "expected_output" in revision else item.get("expected_output")),
                safe_cell(", ".join(str(value) for value in (revision.get("tags") if "tags" in revision else item.get("tags") or []))),
                safe_cell(", ".join(str(value) for value in (revision.get("evidence_gaps") if "evidence_gaps" in revision else item.get("evidence_gaps") or []))),
                "true" if revision.get("is_excluded", item.get("is_excluded")) else "false",
                int(item.get("submitted") or 0),
                int(item.get("required_submitter_count") or 0),
                safe_cell(item.get("state")),
                safe_cell(assignees),
                safe_cell(revision.get("author")),
                safe_cell(revision.get("revision_kind")),
                safe_cell(revision.get("rationale")),
                revision.get("revision_id", ""),
                safe_cell(revision.get("created_at")),
            ])
    safe_id = "".join(char for char in str(campaign.get("id") or campaign_id) if char.isalnum() or char in "-_")[:80]
    filename = f"campaign-{safe_id}-label-analysis.csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/campaigns")
async def create_campaign(request: Request) -> dict[str, Any]:
    actor, source, verified = _campaign_admin(request)
    body = _json_body(await request.body())
    try:
        await asyncio.to_thread(_require_known_assignees, [body])
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    try:
        result = await asyncio.to_thread(
            database.create_campaign,
            spec=body,
            actor=actor,
            actor_source=source,
            actor_verified=verified,
            idempotency_key=_idempotency_key(request, body),
        )
    except CampaignConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except (CampaignReadOnlyError, ValueError) as exc:
        raise _detail(400, str(exc)) from exc
    return {"campaign": result, "change_revision": await asyncio.to_thread(database.change_revision)}


@router.post("/api/review-task-groups")
async def create_campaign_group(request: Request) -> dict[str, Any]:
    actor, source, verified = _campaign_admin(request)
    body = _json_body(await request.body())
    campaigns = body.get("campaigns")
    if not isinstance(campaigns, list):
        raise _detail(400, "campaigns 必须是数组。")
    try:
        await asyncio.to_thread(_require_known_assignees, [item for item in campaigns if isinstance(item, dict)])
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    try:
        result = await asyncio.to_thread(
            database.create_campaign_group,
            name=_as_text(body.get("name")),
            purpose=_as_text(body.get("purpose")),
            campaigns=campaigns,
            actor=actor,
            actor_source=source,
            actor_verified=verified,
            idempotency_key=_idempotency_key(request, body),
        )
    except CampaignConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except (CampaignReadOnlyError, ValueError) as exc:
        raise _detail(400, str(exc)) from exc
    return {"group": result, "change_revision": await asyncio.to_thread(database.change_revision)}


@router.get("/api/review-task-groups/{group_id}")
async def get_campaign_group(group_id: str) -> dict[str, Any]:
    result = await asyncio.to_thread(database.get_campaign_group, group_id)
    if result is None:
        raise _detail(404, "Review Task Group 不存在。")
    return result


@router.patch("/api/campaigns/{campaign_id}/issues/{issue_id}/assignments")
async def update_campaign_assignment(
    campaign_id: str, issue_id: str, request: Request
) -> dict[str, Any]:
    actor, source, verified = _campaign_admin(request)
    body = _json_body(await request.body(), maximum=16 * 1024)
    access_users = await asyncio.to_thread(database.list_access_users)
    allowed = {
        str(item.get("username") or "").strip().lower()
        for item in access_users if item.get("enabled", True)
    }
    assignee = _as_text(body.get("assignee")).strip().lower()
    from_assignee = _as_text(body.get("from_assignee")).strip().lower()
    if assignee and assignee not in allowed:
        raise _detail(400, "新负责人不在 Dashboard 用户列表中。")
    try:
        result = await asyncio.to_thread(
            database.update_campaign_assignment,
            campaign_id=campaign_id,
            issue_id=issue_id,
            action=_as_text(body.get("action")),
            actor=actor,
            actor_source=source,
            actor_verified=verified,
            expected_revision=_required_integer(body, "expected_revision"),
            idempotency_key=_idempotency_key(request, body),
            assignee=assignee,
            from_assignee=from_assignee,
            assignment_kind=_as_text(body.get("assignment_kind") or "base"),
            reason=_as_text(body.get("reason")),
        )
    except CampaignConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except CampaignReadOnlyError as exc:
        raise _detail(409, str(exc)) from exc
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    result["change_revision"] = await asyncio.to_thread(database.change_revision)
    return result


@router.post("/api/campaigns/{campaign_id}/close")
async def close_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    actor, source, verified = _campaign_admin(request)
    body = _json_body(await request.body(), maximum=16 * 1024)
    try:
        result = await asyncio.to_thread(
            database.close_campaign,
            campaign_id=campaign_id,
            actor=actor,
            actor_source=source,
            actor_verified=verified,
            expected_revision=_required_integer(body, "expected_revision"),
            idempotency_key=_idempotency_key(request, body),
            reason=_as_text(body.get("reason")),
        )
    except CampaignConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except CampaignReadOnlyError as exc:
        raise _detail(409, str(exc)) from exc
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    result["change_revision"] = await asyncio.to_thread(database.change_revision)
    return result


@router.post("/api/campaigns/{campaign_id}/reopen")
async def reopen_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    actor, source, verified = _campaign_admin(request)
    body = _json_body(await request.body(), maximum=16 * 1024)
    try:
        result = await asyncio.to_thread(
            database.reopen_campaign,
            campaign_id=campaign_id,
            actor=actor,
            actor_source=source,
            actor_verified=verified,
            expected_revision=_required_integer(body, "expected_revision"),
            idempotency_key=_idempotency_key(request, body),
            reason=_as_text(body.get("reason")),
        )
    except CampaignConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except CampaignReadOnlyError as exc:
        raise _detail(409, str(exc)) from exc
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    result["change_revision"] = await asyncio.to_thread(database.change_revision)
    return result


async def _transition_campaign(
    campaign_id: str, request: Request, *, action: str
) -> dict[str, Any]:
    actor, source, verified = _campaign_admin(request)
    body = _json_body(await request.body(), maximum=16 * 1024)
    try:
        result = await asyncio.to_thread(
            database.transition_campaign,
            campaign_id=campaign_id,
            action=action,
            actor=actor,
            actor_source=source,
            actor_verified=verified,
            expected_revision=_required_integer(body, "expected_revision"),
            idempotency_key=_idempotency_key(request, body),
            reason=_as_text(body.get("reason")),
        )
    except CampaignConflictError as exc:
        raise _detail(409, str(exc)) from exc
    except CampaignReadOnlyError as exc:
        raise _detail(409, str(exc)) from exc
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    result["change_revision"] = await asyncio.to_thread(database.change_revision)
    return result


@router.post("/api/campaigns/{campaign_id}/activate")
async def activate_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    return await _transition_campaign(campaign_id, request, action="activate")


@router.post("/api/campaigns/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    return await _transition_campaign(campaign_id, request, action="cancel")


@router.post("/api/campaigns/{campaign_id}/supersede")
async def supersede_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    return await _transition_campaign(campaign_id, request, action="supersede")


@router.get("/api/campaigns/{campaign_id}/issues/{issue_id}/comments")
async def list_campaign_comments(campaign_id: str, issue_id: str) -> dict[str, Any]:
    if not await _campaign_issue_exists(campaign_id, issue_id):
        raise _detail(404, "Campaign Issue 不存在。")
    comments = await asyncio.to_thread(
        database.list_review_comments,
        issue_id=issue_id,
        discussion_channel="campaign",
        campaign_id=campaign_id,
    )
    count = await asyncio.to_thread(
        database.review_comment_count,
        issue_id=issue_id,
        discussion_channel="campaign",
        campaign_id=campaign_id,
    )
    return {"comments": [_public_review_comment(item) for item in comments], "count": count}


@router.get("/api/campaigns/{campaign_id}/issues/{issue_id}/discussion")
async def get_campaign_discussion(campaign_id: str, issue_id: str) -> dict[str, Any]:
    if not await _campaign_issue_exists(campaign_id, issue_id):
        raise _detail(404, "Campaign Issue 不存在。")
    detail = await asyncio.to_thread(database.get_campaign, campaign_id, page=1, page_size=1)
    campaign = (detail or {}).get("campaign") or {}
    issue = await asyncio.to_thread(database.get_issue, issue_id)
    if issue is None:
        raise _detail(404, "Issue 不存在。")
    baseline_scope = str(issue.get("baseline_scope") or "")
    case_comments = await asyncio.to_thread(
        database.list_review_comments,
        issue_id=issue_id,
        discussion_channel="case",
        baseline_scope=baseline_scope,
    )
    campaign_comments = await asyncio.to_thread(
        database.list_review_comments,
        issue_id=issue_id,
        discussion_channel="campaign",
        campaign_id=campaign_id,
    )
    other_campaigns = await asyncio.to_thread(
        database.list_related_campaign_comment_groups,
        issue_id=issue_id,
        exclude_campaign_id=campaign_id,
    )
    run_id = str(campaign.get("evaluation_run_id") or "")
    run_comments = await asyncio.to_thread(
        database.list_review_comments,
        issue_id=issue_id,
        discussion_channel="model_review",
        model_run_id=run_id,
    ) if run_id else []
    public = lambda rows: [_public_review_comment(item) for item in rows]
    return {
        "campaign_id": campaign_id,
        "issue_id": issue_id,
        "baseline_scope": baseline_scope,
        "case_comments": public(case_comments),
        "campaign_comments": public(campaign_comments),
        "other_campaigns": [
            {**group, "comments": public(group.get("comments") or [])}
            for group in other_campaigns
        ],
        "run_id": run_id,
        "run_comments": public(run_comments),
    }


@router.post("/api/campaigns/{campaign_id}/issues/{issue_id}/comments")
async def create_campaign_comment(
    campaign_id: str, issue_id: str, request: Request
) -> dict[str, Any]:
    actor, source, verified = _campaign_admin(request)
    body = _json_body(await request.body(), maximum=64 * 1024)
    text = _as_text(body.get("body")).strip()
    if not text or len(text) > 3500:
        raise _detail(400, "评论内容必须为 1 到 3500 个字符。")
    if not await _campaign_issue_exists(campaign_id, issue_id):
        raise _detail(404, "Campaign Issue 不存在。")
    campaign_detail = await asyncio.to_thread(database.get_campaign, campaign_id, page=1, page_size=1)
    campaign = (campaign_detail or {}).get("campaign") or {}
    parent_id = None
    parent = None
    raw_parent = body.get("reply_to_id")
    if raw_parent not in (None, "", 0, "0"):
        try:
            parent_id = int(raw_parent)
        except (TypeError, ValueError) as exc:
            raise _detail(400, "reply_to_id 不合法。") from exc
        parent = await asyncio.to_thread(database.get_review_comment, parent_id)
        if parent is None or parent.get("issue_id") != issue_id or parent.get("discussion_channel") != "campaign" or parent.get("campaign_id") != campaign_id:
            raise _detail(400, "只能回复当前 Campaign Issue 下的评论。")
    try:
        mentions = extract_review_mentions(text)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    requested = list(mentions)
    if parent and parent.get("author"):
        requested.append(str(parent["author"]).strip().lower())
    enabled = await asyncio.to_thread(database.enabled_mention_recipients, list(dict.fromkeys(requested)))
    unsupported = [name for name in mentions if name not in enabled]
    if unsupported:
        raise _detail(400, "以下用户不在可 @ / DChat 通知人员目录中：" + "、".join(f"@{name}" for name in unsupported))
    recipients = notification_recipients(enabled, author=actor)
    queued = recipients if settings.dchat_notifications_enabled else []
    try:
        comment = await asyncio.to_thread(
            database.create_review_comment,
            issue_id=issue_id,
            body=text,
            author=actor,
            author_source=source,
            author_verified=verified,
            mentions=mentions,
            notification_recipients=queued,
            reply_to_id=parent_id,
            discussion_channel="campaign",
            campaign_id=campaign_id,
            require_existing_model_run=False,
        )
    except ValueError as exc:
        raise _detail(409, str(exc)) from exc
    if campaign.get("purpose") == "labeling":
        try:
            await asyncio.to_thread(
                database.link_label_comment,
                comment_id=int(comment["id"]),
                task_id=campaign_id,
                source_run_id=str(campaign.get("selection_source_run_id") or ""),
                policy_version="s4-campaign-v1",
            )
        except ValueError as exc:
            raise _detail(409, str(exc)) from exc
    if queued:
        review_notification_dispatcher.wake()
    count = await asyncio.to_thread(
        database.review_comment_count,
        issue_id=issue_id,
        discussion_channel="campaign",
        campaign_id=campaign_id,
    )
    return {"comment": _public_review_comment(comment), "comment_count": count,
            "notification": {"mentions": mentions, "queued": queued}}
