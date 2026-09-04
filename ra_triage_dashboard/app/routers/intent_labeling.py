from __future__ import annotations

import asyncio
import json
import random
import secrets
import uuid
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..auth import normalise_username
from ..db_parts.shared import IntentAnnotationConflictError
from ..support.common import _detail
from ..support.identity import _action_actor, _admin_identity, _intent_identity
from ..intent_experiments import build_intent_experiment_assignments
from ..intent_name_suggestion import (
    IntentNameSuggestionError,
    rule_based_intent_name,
    suggest_intent_name_with_llm,
)
from ..model_catalog import ModelCatalogError
from ..intent_summary import (
    intent_frame_counts,
    intent_labels_complete,
    public_intent_contributors,
    summarize_intent,
)
from ..runtime import database, intent_dataset_registry, model_catalog, settings


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
MAX_BULK_DELETE_REQUEST_BYTES = 64 * 1024


def _attach_intent_frame_distributions(
    report: dict[str, Any], timeline_for_item: Any
) -> None:
    routing: Counter[str] = Counter()
    lane_change: Counter[str] = Counter()
    all_items = report.pop("_all_items", report.get("items", []))
    for item in all_items:
        frame_counts = intent_frame_counts(
            timeline_for_item(item),
            routing_default=str(item.get("routing_default") or ""),
            lane_change_default=str(item.get("lane_change_default") or ""),
            overrides=item.get("overrides") or [],
        )
        item["frame_counts"] = frame_counts
        routing.update(frame_counts.get("routing") or {})
        lane_change.update(frame_counts.get("lane_change") or {})
    report["frame_distributions"] = {
        "routing": dict(routing),
        "lane_change": dict(lane_change),
    }


def _intent_summary_payload(dataset_id: str, identity: Any, experiment_id: str,
                            assignees: tuple[str, ...], reveal_answers: bool,
                            axis: str, page: int, page_size: int,
                            comment_query: str = "") -> dict[str, Any]:
    try:
        case_ids = intent_dataset_registry.case_ids(dataset_id)
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    experiments = database.list_intent_experiments(dataset_id)
    selected_experiment = next((item for item in experiments if item["id"] == experiment_id), None)
    if experiment_id and not selected_experiment:
        raise _detail(404, "实验不属于当前数据集。")
    data = database.intent_report_rows(dataset_id)
    report = summarize_intent(data, case_ids, username=identity.username,
                              experiment_id=experiment_id, assignees=assignees,
                              reveal_answers=reveal_answers, axis=axis,
                              page=page, page_size=page_size,
                              label_scope=(selected_experiment or {}).get("label_scope", "all"))
    timeline_cache: dict[str, list[dict[str, Any]]] = {}
    _attach_intent_frame_distributions(
        report,
        lambda item: timeline_cache.setdefault(
            str(item["case_id"]),
            intent_dataset_registry.timeline(dataset_id, str(item["case_id"])),
        ),
    )
    report["experiments"] = [{"id": item["id"], "name": item["name"],
                              "label_scope": item.get("label_scope", "all")} for item in experiments]
    assignment_owners = {row["username"] for row in data["assignments"]
                         if not experiment_id or row["experiment_id"] == experiment_id}
    head_owners = {row["username"] for row in data["heads"]} if not experiment_id else set()
    report["owners"] = sorted(assignment_owners | head_owners)
    report["comment_query"] = str(comment_query or "").strip()[:80]
    report["comment_hits"] = database.search_intent_comments(
        dataset_id,
        comment_query,
        username=identity.username,
        reveal_answers=reveal_answers,
        experiment_id=experiment_id,
    ) if report["comment_query"] else []
    return report


def _intent_summary_payload_multi(dataset_ids: tuple[str, ...], identity: Any,
                                  experiment_id: str, assignees: tuple[str, ...],
                                  reveal_answers: bool, axis: str, page: int,
                                  page_size: int, comment_query: str = "") -> dict[str, Any]:
    if len(dataset_ids) == 1:
        report = _intent_summary_payload(
            dataset_ids[0], identity, experiment_id, assignees, reveal_answers,
            axis, page, page_size, comment_query,
        )
        for collection in ("items", "comment_hits", "experiments"):
            for item in report.get(collection, []):
                item["dataset_id"] = dataset_ids[0]
        report["dataset_ids"] = list(dataset_ids)
        return report

    separator = "\x1f"
    combined: dict[str, list[dict[str, Any]]] = {
        "heads": [], "assignments": [], "comments": []
    }
    experiments: list[dict[str, Any]] = []
    keyed_case_ids: list[str] = []
    comments: list[dict[str, Any]] = []
    for dataset_id in dataset_ids:
        try:
            case_ids = intent_dataset_registry.case_ids(dataset_id)
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
        keyed_case_ids.extend(f"{dataset_id}{separator}{case_id}" for case_id in case_ids)
        dataset_experiments = database.list_intent_experiments(dataset_id)
        experiments.extend({**item, "dataset_id": dataset_id} for item in dataset_experiments)
        data = database.intent_report_rows(dataset_id)
        combined["heads"].extend(
            {**row, "case_id": f"{dataset_id}{separator}{row['case_id']}"}
            for row in data["heads"]
        )
        combined["assignments"].extend(
            {**row, "case_id": f"{dataset_id}{separator}{row['case_id']}"}
            for row in data["assignments"]
        )
        combined["comments"].extend(
            {**row, "case_id": f"{dataset_id}{separator}{row['case_id']}"}
            for row in data.get("comments", [])
        )
        if comment_query:
            comments.extend(
                {**item, "dataset_id": dataset_id}
                for item in database.search_intent_comments(
                    dataset_id,
                    comment_query,
                    username=identity.username,
                    reveal_answers=reveal_answers,
                    experiment_id=experiment_id,
                )
            )
    if experiment_id and not any(item["id"] == experiment_id for item in experiments):
        raise _detail(404, "实验不属于所选数据集。")
    selected_experiment = next((item for item in experiments if item["id"] == experiment_id), None)
    report = summarize_intent(
        combined,
        tuple(keyed_case_ids),
        username=identity.username,
        experiment_id=experiment_id,
        assignees=assignees,
        reveal_answers=reveal_answers,
        axis=axis,
        page=page,
        page_size=page_size,
        label_scope=(selected_experiment or {}).get("label_scope", "all"),
    )
    def multi_timeline(item: dict[str, Any]) -> list[dict[str, Any]]:
        dataset_id, case_id = str(item["case_id"]).split(separator, 1)
        item["dataset_id"] = dataset_id
        item["case_id"] = case_id
        return intent_dataset_registry.timeline(dataset_id, case_id)

    _attach_intent_frame_distributions(report, multi_timeline)
    report["experiments"] = [
        {"id": item["id"], "name": item["name"], "dataset_id": item["dataset_id"],
         "label_scope": item.get("label_scope", "all")}
        for item in experiments
    ]
    assignment_owners = {
        row["username"] for row in combined["assignments"]
        if not experiment_id or row["experiment_id"] == experiment_id
    }
    head_owners = {row["username"] for row in combined["heads"]} if not experiment_id else set()
    report["owners"] = sorted(assignment_owners | head_owners)
    report["comment_query"] = str(comment_query or "").strip()[:80]
    report["comment_hits"] = sorted(
        comments,
        key=lambda item: (str(item.get("created_at") or ""), int(item.get("id") or 0)),
        reverse=True,
    )
    report["dataset_ids"] = list(dataset_ids)
    return report


@router.get("/api/intent-summary")
async def intent_summary(request: Request, dataset_id: list[str] = Query(default=[]), experiment_id: str = "",
                         assignee: list[str] = Query(default=[]), reveal_answers: bool = False,
                         axis: str = "all", page: int = 1, page_size: int = 20,
                         q: str = "") -> dict[str, Any]:
    identity = await asyncio.to_thread(_intent_identity, request)
    if reveal_answers:
        await asyncio.to_thread(_admin_identity, request)
    if axis not in {"all", "routing", "lane_change"}:
        raise _detail(400, "汇总维度仅支持 all、routing 或 lane_change。")
    if page_size not in {10, 20, 50, 100}:
        raise _detail(400, "每页数量仅支持 10、20、50 或 100。")
    dataset_ids = tuple(dict.fromkeys(str(item).strip() for item in dataset_id if str(item).strip()))
    if not dataset_ids or len(dataset_ids) > 8:
        raise _detail(400, "请选择 1 到 8 个意图数据集。")
    return await asyncio.to_thread(_intent_summary_payload_multi, dataset_ids, identity,
                                   experiment_id, tuple(assignee[:20]), reveal_answers,
                                   axis, page, page_size, q)


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


def _case_status(summary: dict[str, Any] | None, label_scope: str = "all") -> str:
    if not summary:
        return "unlabeled"
    if intent_labels_complete(
        str(summary.get("routing_default") or ""),
        str(summary.get("lane_change_default") or ""),
        label_scope=label_scope,
    ):
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
    dataset_id: list[str] = Query(default=[]), experiment_id: str = ""
) -> dict[str, Any]:
    dataset_ids = tuple(dict.fromkeys(str(item).strip() for item in dataset_id if str(item).strip()))
    if not dataset_ids or len(dataset_ids) > 8:
        raise _detail(400, "请选择 1 到 8 个意图数据集。")
    experiments: list[dict[str, Any]] = []
    for selected_id in dataset_ids:
        try:
            intent_dataset_registry.dataset(selected_id)
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
        experiments.extend(
            {**item, "dataset_id": selected_id}
            for item in await asyncio.to_thread(database.list_intent_experiments, selected_id)
            if item["status"] == "active"
        )
    if experiment_id and not any(item["id"] == experiment_id for item in experiments):
        raise _detail(404, "实验分配不存在、已关闭或不属于当前数据集。")
    assignees: dict[str, dict[str, Any]] = {}
    for selected_id in dataset_ids:
        for item in await asyncio.to_thread(
            database.list_intent_assignment_assignees, selected_id, experiment_id
        ):
            username = str(item["username"])
            aggregate = assignees.setdefault(
                username, {"username": username, "case_count": 0, "experiment_count": 0}
            )
            aggregate["case_count"] += int(item.get("case_count") or 0)
            aggregate["experiment_count"] += int(item.get("experiment_count") or 0)
    return {
        "items": [assignees[name] for name in sorted(assignees)],
        "experiments": [
            {
                "id": item["id"],
                "name": item["name"],
                "case_count": item["case_count"],
                "member_count": item["member_count"],
                "dataset_id": item["dataset_id"],
                "label_scope": item.get("label_scope", "all"),
            }
            for item in experiments
        ],
    }


def _requested_experiment_dataset_ids(request: Request, body: dict[str, Any] | None = None) -> list[str]:
    ids: list[str] = []
    if body is not None:
        raw_ids = body.get("dataset_ids")
        if isinstance(raw_ids, list):
            ids.extend(str(item or "").strip() for item in raw_ids)
        single = str(body.get("dataset_id") or "").strip()
        if single:
            ids.append(single)
    ids.extend(str(item or "").strip() for item in request.query_params.getlist("dataset_id"))
    unique: list[str] = []
    for item in ids:
        if item and item not in unique:
            unique.append(item)
    return unique


@router.get(
    "/api/intent-experiments"
)
async def list_intent_experiments(request: Request) -> dict[str, Any]:
    dataset_ids = _requested_experiment_dataset_ids(request)
    for dataset_id in dataset_ids:
        try:
            intent_dataset_registry.dataset(dataset_id)
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
    experiments, users, name_suggestion_status = await asyncio.gather(
        asyncio.to_thread(database.list_intent_experiments, dataset_ids),
        asyncio.to_thread(database.list_access_users),
        asyncio.to_thread(model_catalog.status),
    )
    return {
        "items": experiments,
        "name_suggestion": {
            "llm_available": bool(name_suggestion_status.get("configured")),
            "credential_source": "server",
        },
        "eligible_members": [
            {"username": item["username"], "role": item["role"]}
            for item in users
            if item["intent_permission"] in {"manage", "annotate"}
        ],
    }


@router.post(
    "/api/intent-experiments/name-suggestion",
    dependencies=[Depends(_require_intent_manager)],
)
async def suggest_intent_experiment_name(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > 8 * 1024:
        raise _detail(413, "实验名称推荐请求过大。")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "实验名称推荐请求必须是 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "实验名称推荐请求必须是 JSON 对象。")
    dataset_ids = _requested_experiment_dataset_ids(request, body)
    if not dataset_ids or len(dataset_ids) > 8:
        raise _detail(400, "请为名称推荐选择 1 到 8 个数据集。")
    datasets: list[dict[str, Any]] = []
    for dataset_id in dataset_ids:
        try:
            datasets.append(intent_dataset_registry.dataset(dataset_id))
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
    mode = str(body.get("annotation_mode") or "blind").strip().lower()
    label_scope = str(body.get("label_scope") or "all").strip().lower()
    if mode not in {"blind", "full"}:
        raise _detail(400, "实验模式仅支持交叉盲标或全量盲标。")
    if label_scope not in {"all", "routing", "lane_change"}:
        raise _detail(400, "标注维度仅支持 Routing、变道意图或两者。")
    try:
        case_count = max(1, min(100_000, int(body.get("case_count") or 1)))
        overlap_ratio = max(0.0, min(1.0, float(body.get("overlap_ratio") or 0)))
        overlap_reviewers = max(1, min(100, int(body.get("overlap_reviewers") or 1)))
        member_count = max(0, min(100, int(body.get("member_count") or 0)))
    except (TypeError, ValueError) as exc:
        raise _detail(400, "实验名称推荐参数不合法。") from exc
    labels = [str(item.display_name or item.dataset_id) for item in datasets]
    draft_name = " ".join(str(body.get("draft_name") or "").replace("\u0000", "").split())[:160]
    fallback = rule_based_intent_name(
        labels,
        annotation_mode=mode,
        case_count=case_count,
        overlap_ratio=overlap_ratio,
        overlap_reviewers=overlap_reviewers,
        member_count=member_count,
        label_scope=label_scope,
    )
    name_suggestion_status = await asyncio.to_thread(model_catalog.status)
    if not name_suggestion_status.get("configured"):
        return {"suggestion": fallback, "source": "rule"}
    try:
        suggestion = await asyncio.to_thread(
            suggest_intent_name_with_llm,
            settings,
            model_catalog,
            fallback=fallback,
            dataset_labels=labels,
            annotation_mode=mode,
            case_count=case_count,
            overlap_ratio=overlap_ratio,
            overlap_reviewers=overlap_reviewers,
            member_count=member_count,
            draft_name=draft_name,
            label_scope=label_scope,
        )
    except (IntentNameSuggestionError, ModelCatalogError):
        return {"suggestion": fallback, "source": "rule"}
    return {"suggestion": suggestion, "source": "llm"}


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
    dataset_ids = _requested_experiment_dataset_ids(request, body)
    if not dataset_ids:
        raise _detail(400, "请至少选择 1 个数据集。")
    name = " ".join(str(body.get("name") or "").split())
    mode = str(body.get("annotation_mode") or "blind").strip().lower()
    label_scope = str(body.get("label_scope") or "all").strip().lower()
    if not name or len(name) > 160:
        raise _detail(400, "实验名称不能为空且不能超过 160 个字符。")
    if mode not in {"blind", "full"}:
        raise _detail(400, "实验模式仅支持交叉盲标或全量盲标。")
    if label_scope not in {"all", "routing", "lane_change"}:
        raise _detail(400, "标注维度仅支持 Routing、变道意图或两者。")
    dataset_cases: list[tuple[str, tuple[str, ...]]] = []
    for dataset_id in dataset_ids:
        try:
            all_case_ids = intent_dataset_registry.case_ids(dataset_id)
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
        if not all_case_ids:
            raise _detail(400, f"{dataset_id} 没有可分配的 Case。")
        dataset_cases.append((dataset_id, all_case_ids))
    max_available = max(len(cases) for _, cases in dataset_cases)
    try:
        requested_count = int(body.get("case_count") or max_available)
        overlap_ratio = float(body.get("overlap_ratio") or 0)
        overlap_reviewers = int(body.get("overlap_reviewers") or 1)
    except (TypeError, ValueError) as exc:
        raise _detail(400, "Case 数量、交叉比例或交叉人数不合法。") from exc
    if requested_count < 1:
        raise _detail(400, "Case 数量必须至少为 1。")
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
    existing = await asyncio.to_thread(database.list_intent_experiments, dataset_ids)
    conflicts = [
        dataset_id
        for dataset_id in dataset_ids
        if any(
            item["dataset_id"] == dataset_id
            and item["name"].casefold() == name.casefold()
            for item in existing
        )
    ]
    if conflicts:
        raise _detail(409, f"以下数据集已经存在同名实验：{', '.join(conflicts)}")
    identity = await asyncio.to_thread(_intent_identity, request, "manage")
    created: list[dict[str, Any]] = []
    for dataset_id, all_case_ids in dataset_cases:
        seed = secrets.randbelow(2_147_483_647)
        case_count = min(requested_count, len(all_case_ids))
        selected_cases = list(all_case_ids)
        random.Random(seed).shuffle(selected_cases)
        selected_cases = selected_cases[:case_count]
        assignments = build_intent_experiment_assignments(
            selected_cases, members, mode, overlap_ratio, seed, overlap_reviewers
        )
        created.append(
            await asyncio.to_thread(
                database.create_intent_experiment,
                experiment_id=str(uuid.uuid4()),
                dataset_id=dataset_id,
                name=name,
                annotation_mode=mode,
                label_scope=label_scope,
                overlap_ratio=overlap_ratio,
                overlap_reviewers=overlap_reviewers,
                case_count=case_count,
                seed=seed,
                assignments=assignments,
                created_by=identity.username,
                created_by_source=identity.source,
                created_by_verified=identity.verified,
            )
        )
    return {
        "experiment": created[0],
        "experiments": created,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.patch(
    "/api/intent-experiments/{experiment_id}",
    dependencies=[Depends(_require_intent_manager)],
)
async def update_intent_experiment(experiment_id: str, request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > 8 * 1024:
        raise _detail(413, "实验修改请求过大。")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "实验修改请求必须是 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "实验修改请求必须是 JSON 对象。")
    experiments = await asyncio.to_thread(database.list_intent_experiments)
    current = next((item for item in experiments if item["id"] == experiment_id), None)
    if current is None:
        raise _detail(404, "实验不存在。")
    if current["status"] != "active":
        raise _detail(409, "已关闭实验不能修改。")
    name = " ".join(str(body.get("name") or "").split())
    label_scope = str(body.get("label_scope") or "").strip().lower()
    if not name or len(name) > 160:
        raise _detail(400, "实验名称不能为空且不能超过 160 个字符。")
    if label_scope not in {"all", "routing", "lane_change"}:
        raise _detail(400, "标注维度仅支持 Routing、变道意图或两者。")
    conflict = next(
        (
            item for item in experiments
            if item["id"] != experiment_id
            and item["dataset_id"] == current["dataset_id"]
            and item["name"].casefold() == name.casefold()
        ),
        None,
    )
    if conflict is not None:
        raise _detail(409, "当前数据集已经存在同名实验。")
    identity = await asyncio.to_thread(_intent_identity, request, "manage")
    try:
        experiment = await asyncio.to_thread(
            database.update_intent_experiment,
            experiment_id,
            name=name,
            label_scope=label_scope,
            updated_by=identity.username,
            updated_by_source=identity.source,
            updated_by_verified=identity.verified,
        )
    except ValueError as exc:
        raise _detail(409, str(exc)) from exc
    if experiment is None:
        raise _detail(404, "实验不存在。")
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


@router.delete(
    "/api/intent-datasets/{dataset_id}/cases/{case_id}/labels/{username}",
    dependencies=[Depends(_require_intent_admin)],
)
async def admin_delete_intent_labels(
    dataset_id: str,
    case_id: str,
    username: str,
    request: Request,
    expected_revision_id: int = Query(gt=0),
) -> dict[str, Any]:
    normalized_username = normalise_username(username)
    if not normalized_username:
        raise _detail(400, "标注人账号格式非法。")
    try:
        if not intent_dataset_registry.has_case(dataset_id, case_id):
            raise _detail(404, "Case 不在该意图标注数据集中。")
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    identity = await asyncio.to_thread(_admin_identity, request)
    actor, actor_source, actor_verified = await asyncio.to_thread(_action_actor, request)
    try:
        deleted = await asyncio.to_thread(
            database.delete_intent_labels,
            dataset_id=dataset_id,
            case_id=case_id,
            username=normalized_username,
            expected_revision_id=expected_revision_id,
            deleted_by=actor or identity.username,
            deleted_by_source=actor_source,
            deleted_by_verified=actor_verified,
        )
    except IntentAnnotationConflictError as exc:
        raise _detail(409, str(exc)) from exc
    if deleted is None:
        raise _detail(404, "该标注人的当前标注不存在。")
    return {
        "deleted": deleted,
        "change_revision": await asyncio.to_thread(database.change_revision),
    }


@router.post(
    "/api/intent-labels/bulk-delete",
    dependencies=[Depends(_require_intent_admin)],
)
async def admin_bulk_delete_intent_labels(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BULK_DELETE_REQUEST_BYTES:
        raise _detail(413, "批量删除请求过大。")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "批量删除请求必须是 JSON。") from exc
    raw_items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 100:
        raise _detail(400, "每次请选择 1 到 100 条标注。")
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            raise _detail(400, "批量删除条目格式非法。")
        dataset_id = str(item.get("dataset_id") or "").strip()
        case_id = str(item.get("case_id") or "").strip()
        username = normalise_username(item.get("username"))
        revision_id = item.get("expected_revision_id")
        if not dataset_id or not case_id or not username:
            raise _detail(400, "批量删除条目缺少数据集、Case 或标注人。")
        if isinstance(revision_id, bool) or not isinstance(revision_id, int) or revision_id <= 0:
            raise _detail(400, "批量删除条目的 revision id 非法。")
        try:
            if not intent_dataset_registry.has_case(dataset_id, case_id):
                raise _detail(404, "Case 不在对应的意图标注数据集中。")
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
        key = (dataset_id, case_id, username)
        if key in seen:
            raise _detail(400, "批量删除请求包含重复标注。")
        seen.add(key)
        targets.append({
            "dataset_id": dataset_id,
            "case_id": case_id,
            "username": username,
            "expected_revision_id": revision_id,
        })
    identity = await asyncio.to_thread(_admin_identity, request)
    actor, actor_source, actor_verified = await asyncio.to_thread(_action_actor, request)
    try:
        deleted = await asyncio.to_thread(
            database.delete_intent_labels_bulk,
            targets=targets,
            deleted_by=actor or identity.username,
            deleted_by_source=actor_source,
            deleted_by_verified=actor_verified,
        )
    except IntentAnnotationConflictError as exc:
        raise _detail(409, str(exc)) from exc
    return {
        "deleted": deleted,
        "count": len(deleted),
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
    label_scope = "all"
    if experiment_id:
        experiment = next(
            (item for item in database.list_intent_experiments(dataset_id)
             if item["id"] == experiment_id and item["status"] == "active"),
            None,
        )
        label_scope = (experiment or {}).get("label_scope", "all")
        assigned = set(database.intent_experiment_case_ids(dataset_id, experiment_id))
        case_ids = tuple(case_id for case_id in case_ids if case_id in assigned)
    if assignees:
        assigned = set(database.intent_assigned_case_ids(dataset_id, assignees, experiment_id))
        case_ids = tuple(case_id for case_id in case_ids if case_id in assigned)
    summaries = database.intent_label_summaries(dataset_id, username)
    normalized_search = search.strip().lower()
    items = []
    for ordinal, case_id in enumerate(case_ids, 1):
        item_status = _case_status(summaries.get(case_id), label_scope)
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


def _list_cases_multi(
    dataset_ids: tuple[str, ...],
    *,
    status: str,
    search: str,
    page: int,
    page_size: int,
    username: str = "",
    assignees: tuple[str, ...] = (),
    experiment_id: str = "",
) -> dict[str, Any]:
    scoped: list[dict[str, Any]] = []
    for dataset_id in dataset_ids:
        try:
            count = len(intent_dataset_registry.case_ids(dataset_id))
        except KeyError as exc:
            raise _detail(404, str(exc)) from exc
        payload = _list_cases(
            dataset_id,
            status="all",
            search="",
            page=1,
            page_size=max(1, count),
            username=username,
            assignees=assignees,
            experiment_id=experiment_id,
        )
        scoped.extend({**item, "dataset_id": dataset_id} for item in payload["items"])
    for index, item in enumerate(scoped):
        item["ordinal"] = index + 1
        item["previous"] = (
            {"dataset_id": scoped[index - 1]["dataset_id"], "case_id": scoped[index - 1]["case_id"]}
            if index > 0 else None
        )
        item["next"] = (
            {"dataset_id": scoped[index + 1]["dataset_id"], "case_id": scoped[index + 1]["case_id"]}
            if index + 1 < len(scoped) else None
        )
    normalized_search = search.strip().lower()
    filtered = [
        item for item in scoped
        if (status == "all" or item["status"] == status)
        and (not normalized_search or normalized_search in item["case_id"].lower())
    ]
    total = len(filtered)
    start = (page - 1) * page_size
    return {
        "items": filtered[start:start + page_size],
        "total": total,
        "scope_total": len(scoped),
        "page": page,
        "page_size": page_size,
        "page_count": max(1, (total + page_size - 1) // page_size),
        "dataset_ids": list(dataset_ids),
    }


@router.get("/api/intent-cases")
async def list_multi_dataset_intent_cases(
    request: Request,
    dataset_id: list[str] = Query(default=[]),
    status: str = "all",
    q: str = "",
    page: int = 1,
    page_size: int = 100,
    assignee: list[str] = Query(default=[]),
    experiment_id: str = "",
) -> dict[str, Any]:
    if status not in {"all", "unlabeled", "partial", "completed"}:
        raise _detail(400, "意图标注状态筛选不合法。")
    dataset_ids = tuple(dict.fromkeys(str(item).strip() for item in dataset_id if str(item).strip()))
    if not dataset_ids or len(dataset_ids) > 8:
        raise _detail(400, "请选择 1 到 8 个意图数据集。")
    identity = await asyncio.to_thread(_intent_identity, request)
    return await asyncio.to_thread(
        _list_cases_multi,
        dataset_ids,
        status=status,
        search=q[:256],
        page=max(1, int(page)),
        page_size=max(1, min(int(page_size), 200)),
        username=identity.username,
        assignees=tuple(assignee[:20]),
        experiment_id=experiment_id,
    )


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
    experiment = None
    if experiment_id:
        experiment = next(
            (item for item in database.list_intent_experiments(dataset_id)
             if item["id"] == experiment_id and item["status"] == "active"),
            None,
        )
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
    labels["frame_counts"] = intent_frame_counts(
        timeline,
        routing_default=str(labels.get("routing_default") or ""),
        lane_change_default=str(labels.get("lane_change_default") or ""),
        overrides=labels.get("overrides") or [],
    )
    contributors = database.list_intent_contributors(dataset_id, case_id)
    assignees = database.list_intent_case_assignees(dataset_id, case_id)
    blind_active = bool(assignees)
    answers_revealed = reveal_answers or not blind_active
    public_contributors = public_intent_contributors(
        username=username,
        contributors=contributors,
        assignees=assignees,
        answers_revealed=answers_revealed,
        timeline=timeline,
        label_scope=(experiment or {}).get("label_scope", "all"),
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
        "status": _case_status(
            labels if labels["revision_id"] else None,
            (experiment or {}).get("label_scope", "all"),
        ),
        "experiment": ({
            "id": experiment["id"],
            "name": experiment["name"],
            "label_scope": experiment.get("label_scope", "all"),
        } if experiment else None),
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


@router.get("/api/intent-datasets/{dataset_id}/cases/{case_id}/comments")
async def list_intent_comments(
    request: Request, dataset_id: str, case_id: str
) -> dict[str, Any]:
    await asyncio.to_thread(_intent_identity, request)
    try:
        if not intent_dataset_registry.has_case(dataset_id, case_id):
            raise _detail(404, "Case 不在该意图标注数据集中。")
    except KeyError as exc:
        raise _detail(404, str(exc)) from exc
    comments = await asyncio.to_thread(
        database.list_intent_comments, dataset_id, case_id
    )
    return {"comments": comments, "count": len(comments)}


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
    raw_reply_to_id = body.get("reply_to_id")
    reply_to_id: int | None = None
    if raw_reply_to_id not in (None, "", 0, "0"):
        try:
            reply_to_id = int(raw_reply_to_id)
        except (TypeError, ValueError) as exc:
            raise _detail(400, "reply_to_id 不合法。") from exc
        if reply_to_id <= 0:
            raise _detail(400, "reply_to_id 不合法。")
    try:
        comment = await asyncio.to_thread(
            database.create_intent_comment,
            dataset_id=dataset_id,
            case_id=case_id,
            body=body.get("body") or "",
            author=actor,
            author_source=actor_source,
            author_verified=actor_verified,
            reply_to_id=reply_to_id,
        )
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return {
        "comment": comment,
        "comment_count": len(
            await asyncio.to_thread(
                database.list_intent_comments, dataset_id, case_id
            )
        ),
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
