from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..db_parts.shared import IntentAnnotationConflictError
from ..http_support import _action_actor, _detail
from ..runtime import database, intent_dataset_registry


router = APIRouter()
MAX_LABEL_REQUEST_BYTES = 512 * 1024


def _empty_labels(dataset_id: str, case_id: str) -> dict[str, Any]:
    return {
        "revision_id": None,
        "dataset_id": dataset_id,
        "case_id": case_id,
        "routing_default": "",
        "lane_change_default": "",
        "author": "",
        "author_source": "",
        "author_verified": False,
        "created_at": "",
        "overrides": [],
    }


def _case_status(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "unlabeled"
    if summary.get("routing_default") and summary.get("lane_change_default"):
        return "completed"
    return "partial"


def _dataset_payloads() -> list[dict[str, Any]]:
    result = []
    for item in intent_dataset_registry.public_datasets():
        summaries = database.intent_label_summaries(str(item["id"]))
        completed = sum(_case_status(summary) == "completed" for summary in summaries.values())
        partial = sum(_case_status(summary) == "partial" for summary in summaries.values())
        total = int(item.get("case_count") or 0)
        result.append(
            {
                **item,
                "completed_count": completed,
                "partial_count": partial,
                "unlabeled_count": max(0, total - completed - partial),
            }
        )
    return result


@router.get("/api/intent-datasets")
async def list_intent_datasets() -> dict[str, Any]:
    return {"items": await asyncio.to_thread(_dataset_payloads)}


def _list_cases(
    dataset_id: str,
    *,
    status: str,
    search: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    try:
        case_ids = intent_dataset_registry.case_ids(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    summaries = database.intent_label_summaries(dataset_id)
    normalized_search = search.strip().lower()
    items = []
    for ordinal, case_id in enumerate(case_ids, 1):
        item_status = _case_status(summaries.get(case_id))
        if status != "all" and item_status != status:
            continue
        if normalized_search and normalized_search not in case_id.lower():
            continue
        items.append(
            {
                "case_id": case_id,
                "issue_id": case_id.rsplit("_", 1)[0],
                "ordinal": ordinal,
                "status": item_status,
                "revision_id": (summaries.get(case_id) or {}).get("revision_id"),
            }
        )
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "page_count": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/api/intent-datasets/{dataset_id}/cases")
async def list_intent_cases(
    dataset_id: str,
    status: str = "all",
    q: str = "",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    if status not in {"all", "unlabeled", "partial", "completed"}:
        raise _detail(400, "意图标注状态筛选不合法。")
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    return await asyncio.to_thread(
        _list_cases,
        dataset_id,
        status=status,
        search=q[:256],
        page=page,
        page_size=page_size,
    )


def _case_payload(dataset_id: str, case_id: str) -> dict[str, Any]:
    try:
        case_ids = intent_dataset_registry.case_ids(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    try:
        ordinal_index = case_ids.index(case_id)
    except ValueError as exc:
        raise _detail(404, "Case 不在该意图标注数据集中。") from exc
    try:
        timeline = intent_dataset_registry.timeline(dataset_id, case_id)
    except (KeyError, ValueError) as exc:
        raise _detail(404, str(exc)) from exc
    labels = database.get_intent_labels(dataset_id, case_id) or _empty_labels(
        dataset_id, case_id
    )
    overrides = {item["timepoint_id"]: item for item in labels["overrides"]}
    enriched = []
    for timepoint in timeline:
        override = overrides.get(timepoint["id"], {})
        routing = override.get("routing_intent") or labels["routing_default"]
        lane_change = override.get("lane_change_intent") or labels["lane_change_default"]
        enriched.append(
            {
                **timepoint,
                "override": override or None,
                "effective": {
                    "routing_intent": routing,
                    "lane_change_intent": lane_change,
                    "routing_source": "override" if override.get("routing_intent") else "aggregate",
                    "lane_change_source": "override" if override.get("lane_change_intent") else "aggregate",
                },
                "suggestions": {},
            }
        )
    return {
        "dataset_id": dataset_id,
        "case_id": case_id,
        "issue_id": case_id.rsplit("_", 1)[0],
        "ordinal": ordinal_index + 1,
        "case_count": len(case_ids),
        "previous_case_id": case_ids[ordinal_index - 1] if ordinal_index > 0 else "",
        "next_case_id": case_ids[ordinal_index + 1] if ordinal_index + 1 < len(case_ids) else "",
        "labels": labels,
        "timepoints": enriched,
        "status": _case_status(labels if labels["revision_id"] else None),
        "suggestion_contract": {
            "read_only": True,
            "prefills_human_labels": False,
            "routing_per_frame_available": False,
        },
    }


@router.get("/api/intent-datasets/{dataset_id}/cases/{case_id}")
async def get_intent_case(dataset_id: str, case_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_case_payload, dataset_id, case_id)


@router.get("/api/intent-datasets/{dataset_id}/cases/{case_id}/timeline")
async def get_intent_timeline(dataset_id: str, case_id: str) -> dict[str, Any]:
    payload = await asyncio.to_thread(_case_payload, dataset_id, case_id)
    return {"items": payload["timepoints"], "count": len(payload["timepoints"])}


@router.get(
    "/api/intent-datasets/{dataset_id}/cases/{case_id}/assets/{asset_id}"
)
async def get_intent_asset(
    dataset_id: str, case_id: str, asset_id: str
) -> FileResponse:
    try:
        path, media_type = await asyncio.to_thread(
            intent_dataset_registry.resolve_asset,
            dataset_id,
            case_id,
            asset_id,
        )
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise _detail(404, str(exc)) from exc
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _export_jsonl(dataset_id: str, view: str, include_incomplete: bool):
    case_ids = intent_dataset_registry.case_ids(dataset_id)
    dataset = intent_dataset_registry.dataset(dataset_id)
    membership_sha256 = intent_dataset_registry.membership_sha256(dataset_id)
    for case_id in case_ids:
        labels = database.get_intent_labels(dataset_id, case_id)
        complete = bool(
            labels
            and labels.get("routing_default")
            and labels.get("lane_change_default")
        )
        if not labels or (not include_incomplete and not complete):
            continue
        common = {
            "schema": f"intent-label-export-{view}-v1",
            "dataset_id": dataset_id,
            "dataset_source_sha256": dataset.source_sha256,
            "membership_sha256": membership_sha256,
            "case_id": case_id,
            "revision_id": labels["revision_id"],
            "author": labels["author"],
            "created_at": labels["created_at"],
            "complete": complete,
        }
        if view == "compact":
            yield json.dumps(
                {
                    **common,
                    "routing_default": labels["routing_default"],
                    "lane_change_default": labels["lane_change_default"],
                    "overrides": labels["overrides"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n"
            continue
        overrides = {item["timepoint_id"]: item for item in labels["overrides"]}
        for timepoint in intent_dataset_registry.timeline(dataset_id, case_id):
            override = overrides.get(timepoint["id"], {})
            yield json.dumps(
                {
                    **common,
                    "timepoint_id": timepoint["id"],
                    "offset_ms": timepoint["offset_ms"],
                    "routing_intent": override.get("routing_intent") or labels["routing_default"],
                    "lane_change_intent": override.get("lane_change_intent") or labels["lane_change_default"],
                    "routing_source": "override" if override.get("routing_intent") else "aggregate",
                    "lane_change_source": "override" if override.get("lane_change_intent") else "aggregate",
                    "camera_available": bool(timepoint.get("camera")),
                    "bev_available": bool(timepoint.get("bev")),
                    "camera_delta_ms": timepoint.get("camera_delta_ms"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n"


@router.get("/api/intent-datasets/{dataset_id}/export")
async def export_intent_labels(
    dataset_id: str,
    view: str = "compact",
    include_incomplete: bool = False,
) -> StreamingResponse:
    if view not in {"compact", "expanded"}:
        raise _detail(400, "导出 view 仅支持 compact 或 expanded。")
    try:
        intent_dataset_registry.dataset(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    return StreamingResponse(
        _export_jsonl(dataset_id, view, include_incomplete),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{dataset_id}-{view}.jsonl"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("/api/intent-datasets/{dataset_id}/cases/{case_id}/labels")
async def put_intent_labels(
    dataset_id: str, case_id: str, request: Request
) -> dict[str, Any]:
    raw_length = request.headers.get("content-length", "").strip()
    if raw_length:
        try:
            if int(raw_length) < 0 or int(raw_length) > MAX_LABEL_REQUEST_BYTES:
                raise _detail(413, "意图标注保存请求过大。")
        except ValueError as exc:
            raise _detail(400, "Content-Length 非法。") from exc
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_LABEL_REQUEST_BYTES:
            raise _detail(413, "意图标注保存请求过大。")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks))
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "意图标注保存请求必须是 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "意图标注保存请求必须是 JSON 对象。")
    try:
        timeline = await asyncio.to_thread(
            intent_dataset_registry.timeline, dataset_id, case_id
        )
    except (KeyError, ValueError) as exc:
        raise _detail(404, str(exc)) from exc
    timeline_by_id = {item["id"]: item for item in timeline}
    overrides = body.get("overrides") or []
    if not isinstance(overrides, list):
        raise _detail(400, "单帧覆盖必须是数组。")
    if len(overrides) > len(timeline):
        raise _detail(400, "单帧覆盖数量超过该 Case 的时间点数量。")
    normalized_overrides = []
    for item in overrides:
        if not isinstance(item, dict):
            raise _detail(400, "单帧覆盖项必须是对象。")
        timepoint_id = str(item.get("timepoint_id") or "").strip()
        timepoint = timeline_by_id.get(timepoint_id)
        if timepoint is None:
            raise _detail(400, f"未知时间点: {timepoint_id}")
        normalized_overrides.append(
            {
                **item,
                "timepoint_id": timepoint_id,
                "offset_ms": int(timepoint["offset_ms"]),
            }
        )
    raw_expected = body.get("expected_revision_id")
    if raw_expected in (None, "", 0, "0"):
        expected_revision_id = None
    else:
        try:
            expected_revision_id = int(raw_expected)
        except (TypeError, ValueError) as exc:
            raise _detail(400, "expected_revision_id 不合法。") from exc
        if expected_revision_id <= 0:
            raise _detail(400, "expected_revision_id 不合法。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor, request, body.get("author")
    )
    try:
        labels = await asyncio.to_thread(
            database.save_intent_labels,
            dataset_id=dataset_id,
            case_id=case_id,
            routing_default=body.get("routing_default") or "",
            lane_change_default=body.get("lane_change_default") or "",
            overrides=normalized_overrides,
            expected_revision_id=expected_revision_id,
            author=actor or "anonymous",
            author_source=actor_source,
            author_verified=actor_verified,
        )
    except IntentAnnotationConflictError as exc:
        raise _detail(409, str(exc))
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return {
        "labels": labels,
        "status": _case_status(labels),
        "change_revision": await asyncio.to_thread(database.change_revision),
    }
