"""Top-level workflow orchestration, issue listing, status projection, and scheduling tick.

Strictly sits at the top of the service DAG: composes core release_workflow operations
with backfill, watch, resume, publication, and ordinary evaluation without circular imports.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os

from sqlalchemy import select

from app.domain.cycle import resolve_current
from app.domain.metrics import cohort_for_issue, excluded_issue, summarize_population
from app.infra.locks import LockBusyError, advisory_lock
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services import (
    auto_triage_metrics,
    batch_poller,
    business_population,
    label_issue_view,
    ordinary_evaluation,
    release_backfill,
    release_inventory,
    release_resume,
    release_watch,
    release_workflow as w,
    result_publication,
)

logger = logging.getLogger(__name__)


def poll_batches(db, config):
    return batch_poller.poll_batches(db, config)


def execute_batch(db, batch, config, *, release=None):
    return w.execute_batch(
        db,
        batch,
        config,
        release=release,
        delta_validator=release_backfill.validate_delta,
    )


def set_mode(db, mode):
    return w.set_mode(db, mode)


def metrics_for_snapshot(db, snapshot):
    if not snapshot:
        return {"available": False, "reason": "尚无完整周期人口快照"}
    population_hash = w.population_identity(snapshot.payload)
    published = result_publication.published_batch(db, snapshot.release)
    if published and release_backfill.frozen_snapshot_valid(db, published):
        scope = business_population.scope_for_batch(db, published)
        if scope["available"]:
            return result_publication.effective_publication(db, published)
        return {"available": False, "reason": scope["reason_code"], "collection_scope": scope}
    batches = db.scalars(
        select(ReleaseSimulationBatch)
        .where(
            ReleaseSimulationBatch.release == snapshot.release,
            ReleaseSimulationBatch.status == "complete",
        )
        .order_by(ReleaseSimulationBatch.updated_at.desc())
    ).all()
    for batch in batches:
        if batch.payload.get("backfill"):
            continue
        if batch.payload.get("result_import") and not batch.payload["result_import"].get("primary"):
            continue
        if batch.payload.get("population_hash") == population_hash:
            scope = business_population.scope_for_batch(db, batch)
            if not scope["available"]:
                return {
                    "available": False,
                    "reason": scope["reason_code"],
                    "collection_scope": scope,
                }
            return {
                **batch.payload.get("summary", {}),
                "job_id": batch.payload.get("job_id"),
                "release": snapshot.release,
                "generated_at": batch.updated_at.replace(tzinfo=timezone.utc).isoformat(),
            }
    return {"available": False, "reason": "当前人口尚无通过验收的完整仿真结果"}


def status(db, config=None):
    config = config if config is not None else w.effective_config(db)
    result = resolve_current(config)
    period = result["current_period"]
    snapshot = w.latest_snapshot(db, w.period_key(config, period)) if period else None
    driver_ready = bool(config.get("simulation", {}).get("driver_command"))
    return {
        **result,
        "mode": w.get_state(db, "settings", {"mode": "manual"})["mode"],
        "driver_ready": driver_ready,
        "scheduler_enabled": os.getenv("RELEASE_WORKFLOW_ENABLED") == "1",
        "last_sync": w.get_state(db, "sync"),
        "release_monitor": w.get_state(db, "release_monitor"),
        "snapshot_id": snapshot.id if snapshot else None,
        "population_complete": snapshot.payload.get("population_complete", False)
        if snapshot
        else False,
        "collected_through": snapshot.payload.get("collected_through") if snapshot else None,
        "acceptance_only": bool(config.get("simulation", {}).get("acceptance_only", False)),
        "metrics": metrics_for_snapshot(db, snapshot),
        "source_metrics": summarize_population(snapshot.payload["issues"], [], {})
        if snapshot
        else None,
        "synced_at": snapshot.created_at.replace(tzinfo=timezone.utc).isoformat()
        if snapshot
        else None,
        "issue_count": sum(int(i["ra_type"]) == 2 for i in snapshot.payload["issues"])
        if snapshot
        else 0,
        "manual_population_count": sum(int(i["ra_type"]) == 3 for i in snapshot.payload["issues"])
        if snapshot
        else 0,
        "scenario_count": len(snapshot.payload["scenarios"]) if snapshot else 0,
        "periods": [
            {
                "release": p.get("release"),
                "cycle_end": p.get("cycle_end"),
                "verified": p.get("verified", False),
                "basis": p.get("basis"),
                "status": p.get("status"),
            }
            for p in config.get("periods", [])
        ],
        "batches": [
            {
                "fingerprint": b.fingerprint,
                "release": b.release,
                "status": b.status,
                "job_id": b.payload.get("job_id"),
                "scenario_count": len(b.payload.get("scenarios", [])),
            }
            for b in db.scalars(
                select(ReleaseSimulationBatch)
                .order_by(ReleaseSimulationBatch.created_at.desc())
                .limit(20)
            )
        ],
    }


def list_issues(db, release=None, page=1, page_size=25, query="", label="", view="collection"):
    if view not in ("simulation", "collection") or page < 1 or not 1 <= page_size <= 200:
        raise ValueError("invalid_pagination")
    config = w.effective_config(db)
    catalog = release_inventory.inventory(db, config)
    if release == "@stable":
        release = catalog["default_release"]
        if not release:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "status": "pending",
            }
    selected = next((v for v in catalog["versions"] if v["release"] == release), None)
    if view == "collection" and selected and selected["source"] == "observation":
        return release_inventory.observation_issues(db, release, page, page_size, query, label)
    if view == "simulation" and release not in (None, "", "@current"):
        ordinary = ordinary_evaluation.issue_page(db, release, page, page_size, query, label)
        if ordinary is not None:
            return ordinary
        applied = label_issue_view.applied_rows(db, release, {}, published=True)
        if applied is not None:
            applied = result_publication.annotate_standard_rows(db, release, applied)
            needle = query.casefold()
            items = [
                row
                for row in applied
                if (not label or label in row["scenario_labels"])
                and (not needle or w._issue_row_matches_query(row, needle))
            ]
            items.sort(
                key=lambda row: (row.get("issue_time") or 0, row["issue_id"], row["scenario_id"]),
                reverse=True,
            )
            return {
                "items": items[(page - 1) * page_size : page * page_size],
                "total": len(items),
                "page": page,
                "page_size": page_size,
                "status": "published",
            }

    current = resolve_current(config)
    if release in (None, "", "@current"):
        period = current["current_period"]
    else:
        candidates = [
            p
            for p in config.get("periods", [])
            if p.get("release") == release
            and p.get("status") == "completed"
            and (p.get("verified") or p.get("basis") == "inferred")
        ]
        period = candidates[0] if len(candidates) == 1 else None
    snapshot = w.latest_snapshot(db, w.period_key(config, period)) if period else None
    if view == "simulation" and snapshot:
        # A published simulation is bound to its frozen source, not the latest
        # observation/snapshot whose labels may still be awaiting processing.
        base = result_publication.published_batch(db, snapshot.release)
        if base:
            _, receipt = auto_triage_metrics.execution_inputs(db, base)
            if receipt.get("snapshot_id"):
                snapshot = db.get(ReleaseIssueSnapshot, receipt["snapshot_id"])
    if snapshot is None:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "status": current["status"],
        }
    scenarios = snapshot.payload["scenarios"]
    scenes_by_issue = {}
    for scene in scenarios:
        scenes_by_issue.setdefault(scene["issue_id"], []).append(scene)
    batches = db.scalars(
        select(ReleaseSimulationBatch)
        .where(ReleaseSimulationBatch.release == snapshot.release)
        .order_by(ReleaseSimulationBatch.updated_at)
    ).all()
    population_hash = w.population_identity(snapshot.payload)
    batch_by_scene = {}
    batches.sort(key=lambda b: bool(b.payload.get("result_import", {}).get("primary")))
    for batch in batches:
        if batch.payload.get(
            "population_hash"
        ) == population_hash or release_backfill.frozen_snapshot_valid(db, batch):
            for scene in batch.payload.get("scenarios", []):
                previous = batch_by_scene.get(scene["scenario_id"])
                if not previous or scene["scenario_id"] not in previous.payload.get("results", {}):
                    batch_by_scene[scene["scenario_id"]] = batch
    items = []
    for issue in snapshot.payload["issues"]:
        if view == "collection" and int(issue["ra_type"]) != 2:
            continue
        mapped = scenes_by_issue.get(str(issue["issue_id"]), [])
        for scenario in mapped or [None]:
            row = {
                "issue_id": str(issue["issue_id"]),
                "issue_topic": str(issue.get("issue_topic") or ""),
                "source_result": issue.get("ra_merge_result"),
                "ra_type": int(issue["ra_type"]),
                "version_key": snapshot.release,
                "road_version": str(issue.get("version", "")),
                "scenario_id": scenario["scenario_id"] if scenario else "",
                "scenario_name": scenario.get("scenario_name", "") if scenario else "",
                "scenario_labels": scenario["scenario_labels"] if scenario else [],
                "simulation_status": "excluded"
                if excluded_issue(issue)
                else "pending_gt"
                if cohort_for_issue(issue) is None
                else "pending_simulation"
                if scenario
                else "pending_mapping",
                "sim_triggered": None,
                "reproduced": None,
                "precision_label": None,
            }
            # A result from another population/config cannot silently evaluate this snapshot.
            batch = batch_by_scene.get(row["scenario_id"])
            if batch:
                row["simulation_status"] = batch.status
                result = batch.payload.get("results", {}).get(row["scenario_id"])
                imported = batch.payload.get("result_import", {}).get("primary", False)
                detail = (
                    batch.payload.get("scenario_results", {}).get(row["scenario_id"], {})
                    if imported
                    else {}
                )
                if detail:
                    row.update(
                        simulation_status=detail["status"],
                        job_id=detail["job_id"],
                        result_note=(
                            str(detail.get("outcome") or "")
                            + "\n"
                            + str(detail.get("outcome_detail") or "")
                        )
                        if detail.get("errors")
                        else "两次执行触发结果不一致"
                        if detail.get("conflict")
                        else "",
                        execution_conflict=detail.get("conflict", False),
                    )
                if (batch.status == "complete" or imported) and result:
                    row.update(
                        {
                            k: result.get(k)
                            for k in ("sim_triggered", "reproduced", "precision_label")
                        }
                    )
            if query and not w._issue_row_matches_query(row, query.casefold()):
                continue
            if label and label not in row["scenario_labels"]:
                continue
            items.append(row)
    if view == "simulation":
        items = result_publication.annotate_standard_rows(db, snapshot.release, items)
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "status": "ready",
    }


def run_tick(sync_source=True, source_interval_seconds=0):
    try:
        lock_ctx = advisory_lock("ra_sim:release_workflow", blocking=False)
        lock_ctx.__enter__()
    except LockBusyError:
        return
    try:
        with w.SessionLocal() as db:
            config = w.effective_config(db)
            if sync_source and source_interval_seconds:
                now = datetime.now(timezone.utc)
                last = w.get_state(db, "source_poll").get("started_at")
                try:
                    age = (now - datetime.fromisoformat(last)).total_seconds()
                    sync_source = not 0 <= age < source_interval_seconds
                except (TypeError, ValueError):
                    pass
                if sync_source:
                    w.put_state(
                        db,
                        "source_poll",
                        {
                            "started_at": now.isoformat(),
                            "interval_seconds": source_interval_seconds,
                        },
                    )
            watch_enabled = config.get("release_monitor", {}).get("enabled", False)
            if sync_source and watch_enabled:
                release_watch.monitor_releases(db, config)
                config = w.effective_config(db)
            if sync_source:
                # Discover historical releases even while the watcher observes
                # each tracked release. Discovery never queues simulations.
                w.refresh_catalog(db, config)
                config = w.effective_config(db)
                try:
                    w.sync_once(db, config)
                    if (
                        not watch_enabled
                        and w.get_state(db, "settings", {"mode": "manual"})["mode"] == "auto"
                    ):
                        w.prepare_missing_scenes(db, config)
                        w.queue_plan(db, w.make_plan(db, config)["fingerprint"], config)
                except Exception as exc:
                    logger.exception("run_tick sync_once failed")
                    db.rollback()
                    w.put_state(
                        db,
                        "sync",
                        {
                            "status": "failed",
                            "reason": str(exc)
                            if isinstance(exc, ValueError)
                            else type(exc).__name__,
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            for batch in db.scalars(
                select(ReleaseSimulationBatch).where(ReleaseSimulationBatch.status == "queued")
            ).all():
                # Quiet-window batches must be freshly observed by monitor_tick,
                # including queued batches recovered after a process restart.
                if not batch.payload.get("backfill") and batch.payload.get("period", {}).get(
                    "completion_rule"
                ) in {"issue_inactivity_24h", "issue_last_time_24h"}:
                    continue
                try:
                    execute_batch(db, batch, config, release=batch.release)
                except ValueError as exc:
                    batch.status = "cancelled_stale"
                    batch.payload = {**batch.payload, "error": str(exc)}
                    db.commit()
            poll_batches(db, config)  # Track active jobs even after switching to manual mode.
            release_resume.process_requests(db, config, poll_fn=poll_batches)
            release_backfill.tick(db, config)
    finally:
        lock_ctx.__exit__(None, None, None)


def tick():
    run_tick(source_interval_seconds=3600)


def process_queued():
    """Dispatch queue without fetching a new source population first."""
    run_tick(sync_source=False)
