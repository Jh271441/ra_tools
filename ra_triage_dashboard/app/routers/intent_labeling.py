from __future__ import annotations

import asyncio
import json
import random
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..db_parts.shared import IntentAnnotationConflictError
from ..http_support import _action_actor, _admin_identity, _detail, _intent_identity
from ..intent_experiments import build_intent_experiment_assignments
from ..intent_summary import summarize_intent
from ..runtime import database, intent_dataset_registry


async def _require_intent_writer(request: Request) -> None:
    """Protect mutations independently of read access."""

    await asyncio.to_thread(_intent_identity, request, "annotate")


async def _require_intent_viewer(request: Request) -> None:
    await asyncio.to_thread(_intent_identity, request)


async def _require_intent_manager(request: Request) -> None:
    await asyncio.to_thread(_intent_identity, request, "manage")


async def _require_intent_admin(request: Request) -> None:
    """Keep explicit blind-answer reveal and bulk export administrator-only."""

    await asyncio.to_thread(_admin_identity, request)


router = APIRouter(dependencies=[Depends(_require_intent_viewer)])
MAX_LABEL_REQUEST_BYTES = 512 * 1024
MAX_EXPERIMENT_REQUEST_BYTES = 64 * 1024
MAX_COMMENT_REQUEST_BYTES = 8 * 1024


def _intent_summary_payload(dataset_id: str, identity: Any, experiment_id: str,
                            assignees: tuple[str, ...], reveal_answers: bool,
                            axis: str, page: int, page_size: int) -> dict[str, Any]:
    try:
        case_ids = intent_dataset_registry.case_ids(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    experiments = database.list_intent_experiments(dataset_id)
    if experiment_id and not any(item["id"] == experiment_id for item in experiments):
        raise _detail(404, "实验不属于当前数据集。")
    data = database.intent_report_rows(dataset_id)
    report = summarize_intent(data, case_ids, username=identity.username,
                              experiment_id=experiment_id, assignees=assignees,
                              reveal_answers=reveal_answers, axis=axis,
                              page=page, page_size=page_size)
    report["experiments"] = [{"id": item["id"], "name": item["name"]} for item in experiments]
    assignment_owners = {row["username"] for row in data["assignments"]
                         if not experiment_id or row["experiment_id"] == experiment_id}
    head_owners = {row["username"] for row in data["heads"]} if not experiment_id else set()
    report["owners"] = sorted(assignment_owners | head_owners)
    return report


@router.get("/api/intent-summary")
async def intent_summary(request: Request, dataset_id: str, experiment_id: str = "",
                         assignee: list[str] = Query(default=[]), reveal_answers: bool = False,
                         axis: str = "all", page: int = 1, page_size: int = 20) -> dict[str, Any]:
    identity = await asyncio.to_thread(_intent_identity, request)
    if reveal_answers:
        await asyncio.to_thread(_admin_identity, request)
    if axis not in {"all", "routing", "lane_change"}:
        raise _detail(400, "汇总维度仅支持 all、routing 或 lane_change。")
    if page_size not in {10, 20, 50}:
        raise _detail(400, "每页数量仅支持 10、20 或 50。")
    return await asyncio.to_thread(_intent_summary_payload, dataset_id, identity,
                                   experiment_id, tuple(assignee[:20]), reveal_answers,
                                   axis, page, page_size)


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


def _dataset_payloads(username: str = "") -> list[dict[str, Any]]:
    result = []
    for item in intent_dataset_registry.public_datasets():
        summaries = database.intent_label_summaries(str(item["id"]), username)
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
async def list_intent_datasets(request: Request) -> dict[str, Any]:
    identity = await asyncio.to_thread(_intent_identity, request)
    return {
        "items": await asyncio.to_thread(_dataset_payloads, identity.username)
    }


@router.get("/api/intent-assignees")
async def list_intent_assignees(
    dataset_id: str, experiment_id: str = ""
) -> dict[str, Any]:
    try:
        intent_dataset_registry.dataset(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    experiments = [
        item for item in await asyncio.to_thread(
            database.list_intent_experiments, dataset_id
        )
        if item["status"] == "active"
    ]
    if experiment_id and not any(item["id"] == experiment_id for item in experiments):
        raise _detail(404, "实验分配不存在、已关闭或不属于当前数据集。")
    return {
        "items": await asyncio.to_thread(
            database.list_intent_assignment_assignees, dataset_id, experiment_id
        ),
        "experiments": [
            {
                "id": item["id"],
                "name": item["name"],
                "case_count": item["case_count"],
                "member_count": item["member_count"],
            }
            for item in experiments
        ],
    }


@router.get(
    "/api/intent-experiments"
)
async def list_intent_experiments(dataset_id: str = "") -> dict[str, Any]:
    if dataset_id:
        try:
            intent_dataset_registry.dataset(dataset_id)
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
    experiments, users = await asyncio.gather(
        asyncio.to_thread(database.list_intent_experiments, dataset_id),
        asyncio.to_thread(database.list_access_users),
    )
    return {
        "items": experiments,
        "eligible_members": [
            {"username": item["username"], "role": item["role"]}
            for item in users
            if item["intent_permission"] in {"manage", "annotate"}
        ],
    }


@router.post(
    "/api/intent-experiments", dependencies=[Depends(_require_intent_manager)]
)
async def create_intent_experiment(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_EXPERIMENT_REQUEST_BYTES:
        raise _detail(413, "实验分配请求过大。")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "实验分配请求必须是 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "实验分配请求必须是 JSON 对象。")
    dataset_id = str(body.get("dataset_id") or "").strip()
    name = " ".join(str(body.get("name") or "").split())
    mode = str(body.get("annotation_mode") or "blind").strip().lower()
    if not name or len(name) > 160:
        raise _detail(400, "实验名称不能为空且不能超过 160 个字符。")
    if mode not in {"blind", "full"}:
        raise _detail(400, "实验模式仅支持交叉盲标或全量盲标。")
    try:
        all_case_ids = intent_dataset_registry.case_ids(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    try:
        requested_count = int(body.get("case_count") or len(all_case_ids))
        overlap_ratio = float(body.get("overlap_ratio") or 0)
        overlap_reviewers = int(body.get("overlap_reviewers") or 1)
    except (TypeError, ValueError) as exc:
        raise _detail(400, "Case 数量、交叉比例或交叉人数不合法。") from exc
    if requested_count < 1 or requested_count > len(all_case_ids):
        raise _detail(400, f"Case 数量必须在 1 到 {len(all_case_ids)} 之间。")
    if not 0 <= overlap_ratio <= 1:
        raise _detail(400, "交叉比例必须在 0 到 1 之间。")
    if mode == "full":
        overlap_ratio = 1.0
    raw_members = body.get("members") or []
    if not isinstance(raw_members, list):
        raise _detail(400, "标注成员必须是数组。")
    members = list(dict.fromkeys(str(item or "").strip().lower() for item in raw_members))
    members = [item for item in members if item]
    if len(members) < 1:
        raise _detail(400, "任务分配至少选择 1 名标注成员。")
    if mode == "full":
        overlap_reviewers = len(members)
    elif not 1 <= overlap_reviewers <= len(members):
        raise _detail(400, f"每个 Case 的标注人数必须在 1 到 {len(members)} 之间。")
    access_users = await asyncio.to_thread(database.list_access_users)
    eligible = {item["username"] for item in access_users if item["intent_permission"] in {"manage", "annotate"}}
    unknown = [member for member in members if member not in eligible]
    if unknown:
        raise _detail(400, f"以下成员没有 Dashboard 写入权限：{', '.join(unknown)}")
    existing = await asyncio.to_thread(database.list_intent_experiments, dataset_id)
    if any(item["name"].casefold() == name.casefold() for item in existing):
        raise _detail(409, "该数据集已经存在同名实验。")
    seed = secrets.randbelow(2_147_483_647)
    selected_cases = list(all_case_ids)
    random.Random(seed).shuffle(selected_cases)
    selected_cases = selected_cases[:requested_count]
    assignments = build_intent_experiment_assignments(
        selected_cases, members, mode, overlap_ratio, seed, overlap_reviewers
    )
    identity = await asyncio.to_thread(_intent_identity, request, "manage")
    experiment = await asyncio.to_thread(
        database.create_intent_experiment,
        experiment_id=str(uuid.uuid4()),
        dataset_id=dataset_id,
        name=name,
        annotation_mode=mode,
        overlap_ratio=overlap_ratio,
        overlap_reviewers=overlap_reviewers,
        case_count=requested_count,
        seed=seed,
        assignments=assignments,
        created_by=identity.username,
        created_by_source=identity.source,
        created_by_verified=identity.verified,
    )
    return {
        "experiment": experiment,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.post(
    "/api/intent-experiments/{experiment_id}/close",
    dependencies=[Depends(_require_intent_manager)],
)
async def close_intent_experiment(experiment_id: str, request: Request) -> dict[str, Any]:
    identity = await asyncio.to_thread(_intent_identity, request, "manage")
    experiment = await asyncio.to_thread(
        database.close_intent_experiment,
        experiment_id,
        closed_by=identity.username,
    )
    if experiment is None:
        raise _detail(404, "实验不存在。")
    return {
        "experiment": experiment,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


def _list_cases(
    dataset_id: str,
    *,
    status: str,
    search: str,
    page: int,
    page_size: int,
    username: str = "",
    assignees: tuple[str, ...] = (),
    experiment_id: str = "",
) -> dict[str, Any]:
    try:
        case_ids = intent_dataset_registry.case_ids(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    if experiment_id:
        assigned = set(database.intent_experiment_case_ids(dataset_id, experiment_id))
        case_ids = tuple(case_id for case_id in case_ids if case_id in assigned)
    if assignees:
        assigned = set(database.intent_assigned_case_ids(dataset_id, assignees, experiment_id))
        case_ids = tuple(case_id for case_id in case_ids if case_id in assigned)
    summaries = database.intent_label_summaries(dataset_id, username)
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
    request: Request,
    dataset_id: str,
    status: str = "all",
    q: str = "",
    page: int = 1,
    page_size: int = 100,
    assignee: list[str] = Query(default=[]),
    experiment_id: str = "",
) -> dict[str, Any]:
    if status not in {"all", "unlabeled", "partial", "completed"}:
        raise _detail(400, "意图标注状态筛选不合法。")
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    identity = await asyncio.to_thread(_intent_identity, request)
    return await asyncio.to_thread(
        _list_cases,
        dataset_id,
        status=status,
        search=q[:256],
        page=page,
        page_size=page_size,
        username=identity.username,
        assignees=tuple(assignee[:20]),
        experiment_id=experiment_id,
    )


def _case_payload(
    dataset_id: str,
    case_id: str,
    username: str = "",
    assignees: tuple[str, ...] = (),
    experiment_id: str = "",
    reveal_answers: bool = False,
) -> dict[str, Any]:
    try:
        case_ids = intent_dataset_registry.case_ids(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    if experiment_id:
        assigned = set(database.intent_experiment_case_ids(dataset_id, experiment_id))
        case_ids = tuple(item for item in case_ids if item in assigned)
    if assignees:
        assigned = set(database.intent_assigned_case_ids(dataset_id, assignees, experiment_id))
        case_ids = tuple(item for item in case_ids if item in assigned)
    try:
        ordinal_index = case_ids.index(case_id)
    except ValueError as exc:
        raise _detail(404, "Case 不在该意图标注数据集中。") from exc
    try:
        timeline = intent_dataset_registry.timeline(dataset_id, case_id)
    except (KeyError, ValueError) as exc:
        raise _detail(404, str(exc)) from exc
    labels = database.get_intent_labels(dataset_id, case_id, username) or _empty_labels(
        dataset_id, case_id
    )
    contributors = database.list_intent_contributors(dataset_id, case_id)
    blind_active = database.intent_case_has_active_experiment(
        dataset_id, case_id
    )
    answers_revealed = reveal_answers or not blind_active
    public_contributors = []
    for contributor in contributors:
        is_current = contributor["username"] == username.lower()
        item = {
            "username": contributor["username"],
            "version": contributor["version"],
            "updated_at": contributor["updated_at"],
            "completed": bool(
                contributor["routing_default"]
                and contributor["lane_change_default"]
            ),
            "is_current": is_current,
            "revealed": is_current or answers_revealed,
        }
        if item["revealed"]:
            item["routing_default"] = contributor["routing_default"]
            item["lane_change_default"] = contributor["lane_change_default"]
            item["overrides"] = contributor["overrides"]
        if item["revealed"]:
            public_contributors.append(item)
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
        "collaboration": {
            "blind_active": blind_active,
            "answers_revealed": answers_revealed,
            "contributors": public_contributors,
            "comments": database.list_intent_comments(dataset_id, case_id),
        },
    }


@router.get("/api/intent-datasets/{dataset_id}/cases/{case_id}")
async def get_intent_case(
    request: Request,
    dataset_id: str,
    case_id: str,
    assignee: list[str] = Query(default=[]),
    experiment_id: str = "",
    reveal_answers: bool = False,
) -> dict[str, Any]:
    identity = await asyncio.to_thread(_intent_identity, request)
    if reveal_answers:
        await asyncio.to_thread(_admin_identity, request)
    return await asyncio.to_thread(
        _case_payload,
        dataset_id,
        case_id,
        identity.username,
        tuple(assignee[:20]),
        experiment_id,
        reveal_answers,
    )


@router.get("/api/intent-datasets/{dataset_id}/cases/{case_id}/timeline")
async def get_intent_timeline(
    request: Request, dataset_id: str, case_id: str
) -> dict[str, Any]:
    identity = await asyncio.to_thread(_intent_identity, request)
    payload = await asyncio.to_thread(
        _case_payload, dataset_id, case_id, identity.username
    )
    return {"items": payload["timepoints"], "count": len(payload["timepoints"])}


@router.post("/api/intent-datasets/{dataset_id}/cases/{case_id}/comments", dependencies=[Depends(_require_intent_writer)])
async def post_intent_comment(
    request: Request, dataset_id: str, case_id: str
) -> dict[str, Any]:
    try:
        if not intent_dataset_registry.has_case(dataset_id, case_id):
            raise _detail(404, "Case 不在该意图标注数据集中。")
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    raw = await request.body()
    if len(raw) > MAX_COMMENT_REQUEST_BYTES:
        raise _detail(413, "评论请求过大。")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "评论请求必须是 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "评论请求必须是 JSON 对象。")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor, request
    )
    try:
        comment = await asyncio.to_thread(
            database.create_intent_comment,
            dataset_id=dataset_id,
            case_id=case_id,
            body=body.get("body") or "",
            author=actor,
            author_source=actor_source,
            author_verified=actor_verified,
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return {
        "comment": comment,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


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
    request: Request,
    dataset_id: str,
    view: str = "compact",
    include_incomplete: bool = False,
) -> StreamingResponse:
    await asyncio.to_thread(_admin_identity, request)
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


@router.put("/api/intent-datasets/{dataset_id}/cases/{case_id}/labels", dependencies=[Depends(_require_intent_writer)])
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


@router.delete(
    "/api/intent-datasets/{dataset_id}/cases/{case_id}/labels",
    dependencies=[Depends(_require_intent_writer)],
)
async def delete_intent_labels(
    dataset_id: str,
    case_id: str,
    request: Request,
    expected_revision_id: int = Query(gt=0),
) -> dict[str, Any]:
    try:
        if not intent_dataset_registry.has_case(dataset_id, case_id):
            raise _detail(404, "Case 不在该意图标注数据集中。")
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    identity = await asyncio.to_thread(_intent_identity, request, "annotate")
    actor, actor_source, actor_verified = await asyncio.to_thread(
        _action_actor, request
    )
    try:
        deleted = await asyncio.to_thread(
            database.delete_intent_labels,
            dataset_id=dataset_id,
            case_id=case_id,
            username=identity.username,
            expected_revision_id=expected_revision_id,
            deleted_by=actor or identity.username,
            deleted_by_source=actor_source,
            deleted_by_verified=actor_verified,
        )
    except IntentAnnotationConflictError as exc:
        raise _detail(409, str(exc)) from exc
    if deleted is None:
        raise _detail(404, "当前账号在该 Case 没有可删除的标注。")
    return {
        "deleted": deleted,
        "labels": _empty_labels(dataset_id, case_id),
        "status": "unlabeled",
        "change_revision": await asyncio.to_thread(database.change_revision),
    }
