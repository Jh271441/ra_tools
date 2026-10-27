"""GT sync HTTP helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..gt_sync import TRAIL_GT_FIELD, read_trail_gt_labels
from ..dataset_partitions import PARTITION_IDS, SOURCE_IDS, load_partitions
from ..runtime import baseline_registry, database, gt_sync_lock, runtime_state, settings

logger = logging.getLogger("ra_triage_dashboard")


@dataclass(frozen=True)
class _VersionGtSource:
    id: str
    label: str
    scope: str
    gt_mode: str = "sparse"


def _gt_sync_catalog():
    """Resolve version selectors to original GT sources, never move Issue rows.

    The incremental scope is not a file-backed baseline. Discover it from the
    registered version membership, and keep the ordinary full-scope snapshot
    writer (including its membership race check) as the only apply path.
    """
    entries = {entry.id: entry for entry in baseline_registry.entries}
    aliases = {}
    for family, scopes in database.version_gt_sync_sources().items():
        public_id = "version-" + family
        source_ids = []
        for scope in scopes:
            source = baseline_registry.by_scope(scope)
            if source is not None:
                source_ids.append(source.id)
            elif scope == "manual_sidecar_version_" + family:
                entries[public_id] = _VersionGtSource(public_id, family[4:], scope)
                source_ids.append(public_id)
            else:
                # An unknown source must not silently become a successful partial sync.
                source_ids.append("unavailable:" + scope)
        aliases[public_id] = list(dict.fromkeys(source_ids))
    return entries, aliases


def configured_gt_sync_baseline_ids() -> list[str]:
    entries, aliases = _gt_sync_catalog()
    return _configured_gt_sources(entries, aliases)


def _configured_gt_sources(entries, aliases):
    configured = tuple(settings.gt_sync_baseline_ids)
    if "*" in configured:
        return list(entries)
    return list(dict.fromkeys(source for key in configured
                              for source in aliases.get(key, [key])))

def resolve_gt_sync_baseline_ids(
    raw: Any = None,
    *,
    strict: bool = False,
    _catalog=None,
) -> list[str]:
    entries, aliases = _catalog or _gt_sync_catalog()
    configured = _configured_gt_sources(entries, aliases)
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
    if set(requested).intersection(PARTITION_IDS):
        partitions = load_partitions(settings.data_dir)
        if set(requested).intersection(PARTITION_IDS) - set(partitions):
            raise ValueError("数据集分区暂不可用 / Dataset partition unavailable")
        requested = list(dict.fromkeys(part for value in requested
                                      for part in (SOURCE_IDS if value in PARTITION_IDS else [value])))
    requested = list(dict.fromkeys(source for key in requested
                                  for source in (aliases.get(key) or [key])))
    invalid = [
        baseline_id
        for baseline_id in requested
        if baseline_id not in configured or baseline_id not in entries
    ]
    if strict and invalid:
        raise ValueError(
            "GT 同步仅支持已配置数据集："
            + "、".join(configured)
            + "；不支持："
            + "、".join(invalid)
        )
    return [baseline_id for baseline_id in requested if baseline_id in configured and baseline_id in entries]

def _gt_sync_item(baseline_id: str, entries=None) -> dict[str, Any]:
    entry = (entries if entries is not None else _gt_sync_catalog()[0]).get(baseline_id)
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
    active_snapshot = database.get_active_gt_snapshot(entry.scope)
    running_by_scope = runtime_state.get("gt_sync") or {}
    running = running_by_scope.get(entry.scope) or {}
    if running.get("status") == "running":
        persisted = {**persisted, **running}
    target_count = (len(database.baseline_issue_ids(scope=entry.scope))
                    if entry.gt_mode == "sparse" else int(persisted.get("source_row_count") or 0))
    if (isinstance(entry, _VersionGtSource) and persisted.get("status") == "ready"
            and (not active_snapshot or active_snapshot.get("member_count") != target_count)):
        persisted = {**persisted, "status": "not_started",
                     "message": "新增成员待校验 / New members await GT verification"}
    if (entry.gt_mode == "sparse" and persisted.get("status") == "ready"
            and (active_snapshot or {}).get("source_metadata", {}).get("raw_gt_observation_version") != 1):
        persisted = {**persisted, "status": "not_started",
                     "message": "GT 原值待校验 / Raw GT values await verification"}
    return {
        **persisted,
        "enabled": settings.gt_sync_enabled,
        "baseline_id": entry.id,
        "baseline_label": entry.label,
        "baseline_scope": entry.scope,
        "interval_seconds": settings.gt_sync_interval_seconds,
        "source_view_id": settings.gt_sync_view_id,
        "source_field": TRAIL_GT_FIELD,
        "gt_mode": entry.gt_mode,
        "active_gt_snapshot": active_snapshot,
        "target_row_count": target_count,
    }

def gt_sync_status(baseline_ids: Any = None) -> dict[str, Any]:
    catalog = _gt_sync_catalog()
    configured = _configured_gt_sources(*catalog)
    requested = resolve_gt_sync_baseline_ids(baseline_ids, _catalog=catalog)
    items = [_gt_sync_item(baseline_id, catalog[0]) for baseline_id in requested]
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
            "baseline_sources": catalog[1],
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

def _mark_authoritative_gt_sync_running(requested: list[str], entries=None) -> None:
    entries = entries if entries is not None else _gt_sync_catalog()[0]
    running_by_scope = runtime_state.setdefault("gt_sync", {})
    for baseline_id in requested:
        entry = entries.get(baseline_id)
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

    catalog = _gt_sync_catalog()
    requested = resolve_gt_sync_baseline_ids(baseline_ids, _catalog=catalog)
    if not gt_sync_lock.acquire(blocking=False):
        return requested, False
    _mark_authoritative_gt_sync_running(requested, catalog[0])
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

    if not _lock_acquired and not gt_sync_lock.acquire(blocking=False):
        return {
            **gt_sync_status(baseline_ids),
            "status": "running",
            "message": "已有权威 GT 同步任务在运行。",
        }
    try:
        catalog = _gt_sync_catalog()
        requested = resolve_gt_sync_baseline_ids(baseline_ids, _catalog=catalog)
        running_by_scope = runtime_state.setdefault("gt_sync", {})
        _mark_authoritative_gt_sync_running(requested, catalog[0])
        for baseline_id in requested:
            entry = catalog[0].get(baseline_id)
            if entry is None:
                continue
            try:
                issue_ids = database.baseline_issue_ids(scope=entry.scope)
                allow_sparse = entry.gt_mode == "sparse"
                result = read_trail_gt_labels(
                    ra_root=settings.ra_auto_triage_root,
                    issue_ids=issue_ids,
                    view_id=settings.gt_sync_view_id,
                    chunk_size=settings.gt_sync_chunk_size,
                    allow_unmapped=allow_sparse,
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
                        expected_issue_ids=issue_ids,
                        allow_sparse=allow_sparse,
                        raw_labels=result.raw_labels if allow_sparse else None,
                    )
                    try:
                        database.reconcile_label_gt_export_batches_for_scope(
                            entry.scope
                        )
                    except Exception as reconcile_exc:
                        logger.exception(
                            "GT export reconciliation failed after sync for %s",
                            entry.id,
                        )
                        try:
                            database.record_label_gt_export_reconcile_error_for_scope(
                                entry.scope, str(reconcile_exc)
                            )
                        except Exception:
                            logger.exception(
                                "failed to record GT export reconciliation error for %s",
                                entry.id,
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
