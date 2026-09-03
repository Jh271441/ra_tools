"""GT sync HTTP helpers."""

from __future__ import annotations

import logging
from typing import Any

from ..gt_sync import TRAIL_GT_FIELD, read_trail_gt_labels
from ..runtime import baseline_registry, database, gt_sync_lock, runtime_state, settings

logger = logging.getLogger("ra_triage_dashboard")


def configured_gt_sync_baseline_ids() -> list[str]:
    configured = tuple(settings.gt_sync_baseline_ids)
    if "*" in configured:
        return [entry.id for entry in baseline_registry.entries]
    return list(dict.fromkeys(configured))

def resolve_gt_sync_baseline_ids(
    raw: Any = None,
    *,
    strict: bool = False,
) -> list[str]:
    configured = configured_gt_sync_baseline_ids()
    if raw is None or raw == "":
        return configured
    values: list[str] = []
    source = raw if isinstance(raw, (list, tuple, set)) else [raw]
    for item in source:
        values.extend(
            part.strip()
            for part in str(item or "").split(",")
            if part.strip()
        )
    requested = list(dict.fromkeys(values))
    invalid = [
        baseline_id
        for baseline_id in requested
        if baseline_id not in configured
    ]
    if strict and invalid:
        raise ValueError(
            "GT 同步仅支持已配置数据集："
            + "、".join(configured)
            + "；不支持："
            + "、".join(invalid)
        )
    return [baseline_id for baseline_id in requested if baseline_id in configured]

def _gt_sync_item(baseline_id: str) -> dict[str, Any]:
    entry = baseline_registry.by_id(baseline_id)
    if entry is None:
        return {
            "status": "unavailable",
            "enabled": settings.gt_sync_enabled,
            "baseline_id": baseline_id,
            "baseline_label": baseline_id,
            "baseline_scope": "",
            "source_view_id": settings.gt_sync_view_id,
            "source_field": TRAIL_GT_FIELD,
            "message": f"GT 同步 baseline {baseline_id} 不存在。",
        }
    persisted = database.gt_sync_status(entry.scope)
    running_by_scope = runtime_state.get("gt_sync") or {}
    running = running_by_scope.get(entry.scope) or {}
    if running.get("status") == "running":
        persisted = {**persisted, **running}
    return {
        **persisted,
        "enabled": settings.gt_sync_enabled,
        "baseline_id": entry.id,
        "baseline_label": entry.label,
        "baseline_scope": entry.scope,
        "interval_seconds": settings.gt_sync_interval_seconds,
        "source_view_id": settings.gt_sync_view_id,
        "source_field": TRAIL_GT_FIELD,
    }

def gt_sync_status(baseline_ids: Any = None) -> dict[str, Any]:
    configured = configured_gt_sync_baseline_ids()
    requested = resolve_gt_sync_baseline_ids(baseline_ids)
    items = [_gt_sync_item(baseline_id) for baseline_id in requested]
    status_names = [str(item.get("status") or "not_started") for item in items]
    if not items:
        aggregate_status = "unavailable"
        message = "没有已配置的 GT 同步数据集。"
    elif any(status == "running" for status in status_names):
        aggregate_status = "running"
        message = "正在同步：" + "、".join(
            str(item.get("baseline_label") or item.get("baseline_id") or "")
            for item in items
            if item.get("status") == "running"
        )
    elif any(status in {"failed", "unavailable"} for status in status_names):
        aggregate_status = "failed"
        ready_count = sum(status == "ready" for status in status_names)
        failed_labels = "、".join(
            str(item.get("baseline_label") or item.get("baseline_id") or "")
            for item in items
            if item.get("status") in {"failed", "unavailable"}
        )
        message = f"{ready_count}/{len(items)} 个数据集同步成功；{failed_labels} 失败。"
    elif status_names and all(status == "ready" for status in status_names):
        aggregate_status = "ready"
        changed = sum(
            int(item.get("last_check_change_count") or 0) for item in items
        )
        message = f"{len(items)}/{len(items)} 个数据集 GT 已完整校验，本次更新 {changed} 条。"
    else:
        aggregate_status = "not_started"
        message = "尚未从 Trail 同步全部权威 GT。"

    payload: dict[str, Any] = dict(items[0]) if len(items) == 1 else {}
    payload.update(
        {
            "status": aggregate_status,
            "enabled": settings.gt_sync_enabled,
            "baseline_ids": requested,
            "configured_baseline_ids": configured,
            "baselines": items,
            "interval_seconds": settings.gt_sync_interval_seconds,
            "source_view_id": settings.gt_sync_view_id,
            "source_field": TRAIL_GT_FIELD,
            "source_row_count": sum(
                int(item.get("source_row_count") or 0) for item in items
            ),
            "last_check_change_count": sum(
                int(item.get("last_check_change_count") or 0) for item in items
            ),
            "last_applied_change_count": sum(
                int(item.get("last_applied_change_count") or 0) for item in items
            ),
            "message": message,
        }
    )
    return payload

def _mark_authoritative_gt_sync_running(requested: list[str]) -> None:
    running_by_scope = runtime_state.setdefault("gt_sync", {})
    for baseline_id in requested:
        entry = baseline_registry.by_id(baseline_id)
        if entry is None:
            continue
        running_by_scope[entry.scope] = {
            "status": "running",
            "message": (
                f"正在从 Trail view {settings.gt_sync_view_id} 完整校验 "
                f"{entry.label} GT。"
            ),
            "baseline_id": entry.id,
            "baseline_label": entry.label,
            "baseline_scope": entry.scope,
            "source_view_id": settings.gt_sync_view_id,
            "source_field": TRAIL_GT_FIELD,
        }

def reserve_authoritative_gt_sync(
    baseline_ids: Any = None,
) -> tuple[list[str], bool]:
    """Reserve the global worker before returning an asynchronous HTTP accept."""

    requested = resolve_gt_sync_baseline_ids(baseline_ids)
    if not gt_sync_lock.acquire(blocking=False):
        return requested, False
    _mark_authoritative_gt_sync_running(requested)
    return requested, True

def sync_authoritative_gt(
    *,
    baseline_ids: Any = None,
    requested_by: str = "",
    identity_source: str = "service",
    identity_verified: bool = False,
    trigger: str = "manual",
    _lock_acquired: bool = False,
) -> dict[str, Any]:
    """Read complete fixed Trail snapshots and atomically update local GT."""

    requested = resolve_gt_sync_baseline_ids(baseline_ids)
    if not _lock_acquired and not gt_sync_lock.acquire(blocking=False):
        return {
            **gt_sync_status(requested),
            "status": "running",
            "message": "已有权威 GT 同步任务在运行。",
        }
    try:
        running_by_scope = runtime_state.setdefault("gt_sync", {})
        _mark_authoritative_gt_sync_running(requested)
        for baseline_id in requested:
            entry = baseline_registry.by_id(baseline_id)
            if entry is None:
                continue
            try:
                issue_ids = database.baseline_issue_ids(scope=entry.scope)
                result = read_trail_gt_labels(
                    ra_root=settings.ra_auto_triage_root,
                    issue_ids=issue_ids,
                    view_id=settings.gt_sync_view_id,
                    chunk_size=settings.gt_sync_chunk_size,
                )
                if (
                    not result.complete
                    or result.returned_issues != result.queried_issues
                    or TRAIL_GT_FIELD not in result.fields_visible
                ):
                    database.record_gt_sync_failure(
                        scope=entry.scope,
                        error_text=result.message,
                        source_name="Trail",
                        source_view_id=settings.gt_sync_view_id,
                        source_field=TRAIL_GT_FIELD,
                        trigger=trigger,
                        requested_by=requested_by,
                        requested_by_source=identity_source,
                        requested_by_verified=identity_verified,
                    )
                else:
                    database.apply_gt_sync_snapshot(
                        scope=entry.scope,
                        rows=result.rows,
                        source_name="Trail",
                        source_view_id=settings.gt_sync_view_id,
                        source_field=TRAIL_GT_FIELD,
                        trigger=trigger,
                        requested_by=requested_by,
                        requested_by_source=identity_source,
                        requested_by_verified=identity_verified,
                    )
            except Exception as exc:
                logger.exception(
                    "authoritative GT sync failed for baseline %s", entry.id
                )
                try:
                    database.record_gt_sync_failure(
                        scope=entry.scope,
                        error_text=str(exc),
                        source_name="Trail",
                        source_view_id=settings.gt_sync_view_id,
                        source_field=TRAIL_GT_FIELD,
                        trigger=trigger,
                        requested_by=requested_by,
                        requested_by_source=identity_source,
                        requested_by_verified=identity_verified,
                    )
                except Exception:
                    logger.exception(
                        "failed to persist authoritative GT sync failure for %s",
                        entry.id,
                    )
            finally:
                running_by_scope.pop(entry.scope, None)
        return gt_sync_status(requested)
    finally:
        gt_sync_lock.release()
