from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..db_parts.campaigns import CampaignConflictError, CampaignReadOnlyError
from ..db_parts.run_collections import RunCollectionConflictError
from ..runtime import database
from ..support.baselines import resolve_request_baseline_scopes
from ..support.identity import _admin_identity
from .campaigns import _require_known_assignees

router = APIRouter()


async def _body(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="请求必须为 JSON 对象。") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="请求必须为 JSON 对象。")
    return value


async def _actor(request: Request) -> tuple[str, str, bool]:
    identity = await asyncio.to_thread(_admin_identity, request)
    return str(identity.username or ""), str(identity.source or "verified_sso"), bool(identity.verified)


def _integration_idempotency_key(request: Request, body: dict[str, Any]) -> str:
    key = str(request.headers.get("idempotency-key") or body.get("idempotency_key") or "").strip()
    if not key or len(key) > 160:
        raise HTTPException(status_code=400, detail="Idempotency-Key 必须为 1 到 160 个字符。")
    return key


def _evaluation_task_context(payload: dict[str, Any]) -> tuple[str, list[str], list[dict[str, str]]]:
    workset = payload.get("workset") or {}
    workset_id = str(workset.get("workset_id") or "").strip()
    issue_ids = [str(item or "").strip() for item in workset.get("issue_ids") or [] if str(item or "").strip()]
    if not workset_id:
        raise HTTPException(status_code=400, detail="Campaign 需要绑定 Evaluation 的单数据集冻结 Workset。")
    if not issue_ids or len(issue_ids) > 5000:
        raise HTTPException(status_code=400, detail="Campaign Workset 必须包含 1 到 5000 个 Issue。")
    reference = payload.get("reference") or {}
    ref_type = str(reference.get("type") or "")
    snapshot = reference.get("snapshot") or {}
    scopes = [str(item or "").strip() for item in workset.get("baseline_scopes") or [] if str(item or "").strip()]
    if ref_type == "label_result" and reference.get("id"):
        references = [
            {"baseline_scope": scope, "reference_type": "label_result_snapshot", "reference_id": str(reference["id"])}
            for scope in scopes
        ]
    elif ref_type == "gt":
        refs_by_scope = {
            str(item.get("baseline_scope") or ""): item
            for item in snapshot.get("gt_snapshots") or [] if isinstance(item, dict)
        }
        references = [
            {"baseline_scope": scope, "reference_type": "gt_snapshot", "reference_id": str(refs_by_scope[scope].get("id") or "")}
            for scope in scopes if scope in refs_by_scope
        ]
    else:
        references = []
    if not references or len(references) != len(scopes):
        raise HTTPException(status_code=400, detail="Campaign 需要与 Workset scope 一致的不可变 GT 或 Label snapshot。")
    return workset_id, issue_ids, references


def _raise_database_error(exc: ValueError) -> None:
    if isinstance(exc, RunCollectionConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/run-collections")
async def list_run_collections() -> dict[str, Any]:
    items = await asyncio.to_thread(database.list_run_collections)
    return {"items": items, "total": len(items)}


@router.get("/api/run-collections/{collection_id}")
async def get_run_collection(collection_id: str) -> dict[str, Any]:
    item = await asyncio.to_thread(database.get_run_collection, collection_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Run Collection 不存在。")
    return item


@router.post("/api/run-collections")
async def create_run_collection(request: Request) -> dict[str, Any]:
    actor, actor_source, actor_verified = await _actor(request)
    body = await _body(request)
    try:
        return await asyncio.to_thread(
            database.create_run_collection,
            name=str(body.get("name") or ""),
            description=str(body.get("description") or ""),
            members=body.get("members") or [],
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
            source=str(body.get("source") or "user"),
            idempotency_key=str(request.headers.get("idempotency-key") or body.get("idempotency_key") or ""),
        )
    except ValueError as exc:
        _raise_database_error(exc)


@router.patch("/api/run-collections/{collection_id}")
async def rename_run_collection(collection_id: str, request: Request) -> dict[str, Any]:
    actor, actor_source, actor_verified = await _actor(request)
    body = await _body(request)
    try:
        return await asyncio.to_thread(
            database.rename_run_collection,
            collection_id=collection_id,
            expected_revision=int(body.get("expected_revision") or 0),
            expected_metadata_revision=int(body.get("expected_metadata_revision") or 0),
            name=str(body.get("name") or ""),
            description=str(body.get("description") or ""),
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            _raise_database_error(exc)
        raise HTTPException(status_code=400, detail="expected_revision 必须为正整数。") from exc


@router.post("/api/run-collections/{collection_id}/revisions")
async def create_run_collection_revision(collection_id: str, request: Request) -> dict[str, Any]:
    actor, actor_source, actor_verified = await _actor(request)
    body = await _body(request)
    try:
        expected_revision = int(body.get("expected_revision") or 0)
        return await asyncio.to_thread(
            database.create_run_collection_revision,
            collection_id=collection_id,
            expected_revision=expected_revision,
            members=body.get("members") or [],
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
            source=str(body.get("source") or "user"),
            idempotency_key=str(request.headers.get("idempotency-key") or body.get("idempotency_key") or ""),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            _raise_database_error(exc)
        raise HTTPException(status_code=400, detail="expected_revision 必须为正整数。") from exc


@router.post("/api/run-comparison/save-collection")
async def save_pairwise_as_collection(request: Request) -> dict[str, Any]:
    actor, actor_source, actor_verified = await _actor(request)
    body = await _body(request)
    baseline = str(body.get("baseline_run_id") or "").strip()
    candidate = str(body.get("candidate_run_id") or "").strip()
    if not baseline or not candidate or baseline == candidate:
        raise HTTPException(status_code=400, detail="保存 Pairwise Collection 需要两个不同的 Run。")
    try:
        return await asyncio.to_thread(
            database.create_run_collection,
            name=str(body.get("name") or ""),
            description=str(body.get("description") or ""),
            members=[
                {"run_id": baseline, "role": "baseline", "is_reference": True},
                {"run_id": candidate, "role": "candidate", "is_reference": False},
            ],
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
            source="pairwise_save",
            idempotency_key=str(request.headers.get("idempotency-key") or body.get("idempotency_key") or ""),
        )
    except ValueError as exc:
        _raise_database_error(exc)


@router.post("/api/run-evaluations")
async def create_run_evaluation(request: Request) -> dict[str, Any]:
    actor, actor_source, actor_verified = await _actor(request)
    body = await _body(request)
    try:
        revision = body.get("collection_revision")
        scopes = (
            body.get("baseline_scopes")
            if body.get("baseline_scopes")
            else resolve_request_baseline_scopes(body.get("baselines"), request=request)
        )
        return await asyncio.to_thread(
            database.create_run_evaluation,
            collection_id=str(body.get("collection_id") or ""),
            collection_revision=int(revision) if revision not in (None, "") else None,
            workset_id=str(body.get("workset_id") or ""),
            workset_issue_ids=body.get("workset_issue_ids") or [],
            baseline_scopes=scopes or [],
            reference_type=str(body.get("reference_type") or "gt"),
            reference_id=str(body.get("reference_id") or ""),
            excluded_issue_ids=body.get("excluded_issue_ids"),
            scoring_policy=body.get("scoring_policy"),
            selection_source_run_id=str(body.get("selection_source_run_id") or ""),
            comparison_reference_run_id=str(body.get("comparison_reference_run_id") or ""),
            actor=actor,
            actor_source=actor_source,
            actor_verified=actor_verified,
            idempotency_key=str(request.headers.get("idempotency-key") or body.get("idempotency_key") or ""),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            _raise_database_error(exc)
        raise HTTPException(status_code=400, detail="collection_revision 必须为整数。") from exc


@router.get("/api/run-evaluations")
async def list_run_evaluations(collection_id: str = "", limit: int = 100) -> dict[str, Any]:
    items = await asyncio.to_thread(
        database.list_run_evaluations, collection_id=collection_id, limit=limit
    )
    return {"items": items, "total": len(items)}


@router.get("/api/run-evaluations/{context_id}")
async def get_run_evaluation(
    context_id: str,
    page: int = 1,
    page_size: int = 50,
    q: str = "",
) -> dict[str, Any]:
    try:
        item = await asyncio.to_thread(
            database.get_run_evaluation,
            context_id,
            page=page,
            page_size=page_size,
            search=q,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Evaluation Context 不存在。")
    return item


@router.get("/api/run-evaluations/{context_id}/export")
async def export_run_evaluation(context_id: str) -> JSONResponse:
    item = await asyncio.to_thread(database.export_run_evaluation, context_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evaluation Context 不存在。")
    safe_id = "".join(char for char in str(context_id) if char.isalnum() or char in "-_")[:80] or "context"
    return JSONResponse(
        content=item,
        headers={"Content-Disposition": f'attachment; filename="run-evaluation-{safe_id}.json"'},
    )


@router.post("/api/run-evaluations/{context_id}/labeling-campaign")
async def create_evaluation_labeling_campaign(context_id: str, request: Request) -> dict[str, Any]:
    identity = await asyncio.to_thread(_admin_identity, request)
    body = await _body(request)
    payload = await asyncio.to_thread(database.get_run_evaluation, context_id, page=1, page_size=1)
    if payload is None:
        raise HTTPException(status_code=404, detail="Evaluation Context 不存在。")
    workset_id, issue_ids, references = _evaluation_task_context(payload)
    assignees = body.get("assignees")
    if not isinstance(assignees, list) or not assignees:
        raise HTTPException(status_code=400, detail="Labeling Campaign 需要至少一个已启用的 assignee。")
    spec = {
        "purpose": "labeling",
        "lifecycle": str(body.get("lifecycle") or "draft"),
        "campaign_name": str(body.get("name") or "Evaluation Labeling"),
        "workset_id": workset_id,
        "members": [{"issue_id": issue_id, "assignees": assignees} for issue_id in issue_ids],
        "references": references,
        "selection_source_run_id": str(payload.get("selection_source_run_id") or ""),
    }
    try:
        await asyncio.to_thread(_require_known_assignees, [spec])
        campaign = await asyncio.to_thread(
            database.create_campaign,
            spec=spec,
            actor=str(identity.username or ""),
            actor_source=str(identity.source or "verified_sso"),
            actor_verified=bool(identity.verified),
            idempotency_key=_integration_idempotency_key(request, body),
        )
    except CampaignConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (CampaignReadOnlyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"campaign": campaign, "evaluation_id": context_id}


@router.post("/api/run-evaluations/{context_id}/model-review-group")
async def create_evaluation_model_review_group(context_id: str, request: Request) -> dict[str, Any]:
    identity = await asyncio.to_thread(_admin_identity, request)
    body = await _body(request)
    payload = await asyncio.to_thread(database.get_run_evaluation, context_id, page=1, page_size=1)
    if payload is None:
        raise HTTPException(status_code=404, detail="Evaluation Context 不存在。")
    workset_id, issue_ids, references = _evaluation_task_context(payload)
    available_members = {str(item.get("run_id") or "") for item in payload.get("members") or []}
    selected_run_ids = body.get("run_ids") or list(available_members)
    if not isinstance(selected_run_ids, list) or not selected_run_ids:
        raise HTTPException(status_code=400, detail="Model Review Group 需要至少选择一个 Run。")
    run_ids = list(dict.fromkeys(str(item or "").strip() for item in selected_run_ids if str(item or "").strip()))
    if len(run_ids) != len(selected_run_ids) or any(run_id not in available_members for run_id in run_ids):
        raise HTTPException(status_code=400, detail="所有 Model Review Run 必须来自冻结的 Collection revision。")
    assignees_by_run = body.get("assignees_by_run") or {}
    default_assignees = body.get("assignees") or []
    campaigns = []
    for run_id in run_ids:
        assignees = assignees_by_run.get(run_id, default_assignees) if isinstance(assignees_by_run, dict) else default_assignees
        if not isinstance(assignees, list) or not assignees:
            raise HTTPException(status_code=400, detail=f"Run {run_id} 需要至少一个已启用的 assignee。")
        campaigns.append({
            "purpose": "model_review",
            "lifecycle": str(body.get("lifecycle") or "draft"),
            "campaign_name": f"{str(body.get('name') or 'Evaluation Model Review')} · {run_id[:8]}",
            "evaluation_run_id": run_id,
            "workset_id": workset_id,
            "members": [{"issue_id": issue_id, "assignees": assignees} for issue_id in issue_ids],
            "references": references,
            "selection_source_run_id": str(payload.get("selection_source_run_id") or ""),
        })
    try:
        await asyncio.to_thread(_require_known_assignees, campaigns)
        group = await asyncio.to_thread(
            database.create_campaign_group,
            name=str(body.get("name") or "Evaluation Model Review"),
            purpose="model_review",
            campaigns=campaigns,
            actor=str(identity.username or ""),
            actor_source=str(identity.source or "verified_sso"),
            actor_verified=bool(identity.verified),
            idempotency_key=_integration_idempotency_key(request, body),
        )
    except CampaignConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (CampaignReadOnlyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"group": group, "evaluation_id": context_id}
