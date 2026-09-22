from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..runtime import database
from ..support.baselines import resolve_request_baseline_scopes
from ..support.identity import _admin_identity
from ..db_parts.legacy_cutover import S6_POLICY_VERSION

router = APIRouter()


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="请求必须为 JSON 对象。") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求必须为 JSON 对象。")
    return body


async def _admin(request: Request):
    return await asyncio.to_thread(_admin_identity, request)


def _scopes(value: Any, request: Request) -> list[str]:
    if value:
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    return resolve_request_baseline_scopes("", request=request)


@router.get("/api/legacy-cutover/status")
async def legacy_cutover_status(request: Request, baselines: str = "") -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    policies = await asyncio.to_thread(database.legacy_read_policies, scopes)
    states = await asyncio.to_thread(database.labeling_scope_states, scopes)
    receipts = await asyncio.to_thread(database.legacy_shadow_receipts, scopes)
    return {"policy_version": S6_POLICY_VERSION, "policies": policies, "labeling_scopes": states, "receipts": receipts}


@router.get("/api/legacy-cutover/inventory")
async def legacy_cutover_inventory(request: Request, baselines: str = "") -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return await asyncio.to_thread(database.legacy_scope_inventory, scopes)


@router.post("/api/legacy-cutover/classify")
async def classify_legacy_cutover(request: Request) -> dict[str, Any]:
    identity = await _admin(request)
    body = await _json_body(request)
    scopes = _scopes(body.get("baseline_scopes"), request)
    apply = bool(body.get("apply"))
    if apply and not identity.verified:
        raise HTTPException(status_code=403, detail="verified admin only")
    return await asyncio.to_thread(
        database.classify_legacy_annotations,
        scopes=scopes,
        policy_version=str(body.get("policy_version") or S6_POLICY_VERSION),
        actor=str(identity.username or "s6-admin"),
        apply=apply,
        expected_inventory_sha256=str(body.get("expected_inventory_sha256") or ""),
    )


@router.post("/api/legacy-cutover/policy")
async def update_legacy_policy(request: Request) -> dict[str, Any]:
    identity = await _admin(request)
    if not identity.verified:
        raise HTTPException(status_code=403, detail="verified admin only")
    body = await _json_body(request)
    scope = str(body.get("baseline_scope") or "").strip()
    inventory = await asyncio.to_thread(database.legacy_scope_inventory, [scope])
    return await asyncio.to_thread(
        database.set_legacy_read_policy,
        baseline_scope=scope,
        policy=str(body.get("policy") or "shadow"),
        policy_version=str(body.get("policy_version") or S6_POLICY_VERSION),
        inventory_sha256=str(body.get("inventory_sha256") or inventory["inventory_sha256"]),
        updated_by=str(identity.username or "s6-admin"),
        expected_epoch=body.get("expected_epoch"),
        receipt=body.get("receipt") if isinstance(body.get("receipt"), dict) else {},
    )


@router.get("/api/legacy-cutover/shadow")
async def legacy_shadow(request: Request, baselines: str = "", component: str = "") -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return await asyncio.to_thread(database.legacy_shadow_compare, scopes=scopes, component=component)


@router.get("/api/legacy-cutover/exclusion")
async def legacy_exclusion(request: Request, baselines: str = "") -> dict[str, Any]:
    scopes = resolve_request_baseline_scopes(baselines, request=request)
    return {"items": await asyncio.to_thread(database.legacy_exclusion_projection, scopes=scopes, policy_version=S6_POLICY_VERSION)}


@router.get("/api/legacy/{kind}/{value}")
async def resolve_legacy(kind: str, value: str) -> dict[str, Any]:
    item = await asyncio.to_thread(database.resolve_legacy_evidence, kind=kind, value=value)
    if item is None:
        raise HTTPException(status_code=404, detail="历史证据不存在。")
    return item


@router.get("/api/issues/{issue_id}/canonical-projection")
async def canonical_projection(
    issue_id: str,
    model_run_id: str = "",
    campaign_id: str = "",
    reference_id: str = "",
    reviewer: str = "",
) -> dict[str, Any]:
    item = await asyncio.to_thread(
        database.canonical_issue_projection,
        issue_id=issue_id, model_run_id=model_run_id,
        campaign_id=campaign_id, reference_id=reference_id, reviewer=reviewer,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Issue 不存在。")
    return item
