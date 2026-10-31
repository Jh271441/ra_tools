"""Per-release board with cached, read-only Orion task progress."""

from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path

from sqlalchemy import select
from app.config import DATA_DIR, config_hash, load_versions_config
from app.database import SessionLocal
from app.models import DashboardSnapshot, ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services import release_workflow as workflow
from app.services.release_metrics import summarize_population
from app.services.result_publication import publication, effective_publication, published_batch, coverage_policy
from app.services.release_inventory import inventory


def _jobs(db, versions):
    known = {int(v["sim_job_id"]) for v in versions.values() if v.get("sim_job_id")}
    for batch in db.scalars(select(ReleaseSimulationBatch)):
        if batch.payload.get("job_id"):
            known.add(int(batch.payload["job_id"]))
    return known


def _due(cache, force=False):
    then = cache.get("attempt_at", 0)
    value = cache.get("value") or {}
    ttl = (
        5
        if force
        else 30
        if cache.get("error") or value.get("state") not in ("COMPLETED", "CANCELLED")
        else 3600
    )
    return datetime.now(timezone.utc).timestamp() - then >= ttl


def refresh_progress(job_id, force=False):
    lock_dir = Path(
        os.getenv("RELEASE_WORKFLOW_LOCK", str(DATA_DIR / "release-workflow.lock"))
    ).parent
    with (lock_dir / f"job-progress-{int(job_id)}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with SessionLocal() as db:
            if int(job_id) not in _jobs(db, load_versions_config().get("versions", {})):
                return
            key = f"job-progress:{job_id}"
            cache = workflow.get_state(db, key)
            if not _due(cache, force):
                return
            attempt = datetime.now(timezone.utc).timestamp()
            try:
                result = workflow.driver_call(
                    workflow.effective_config(db), "progress", {"job_id": int(job_id)}
                )
                if result.get("job_id") != int(job_id) or "total" not in result:
                    raise ValueError(
                        result.get("error") or "Orion progress response mismatch"
                    )
                counts = [
                    result.get(k)
                    for k in (
                        "completed",
                        "running",
                        "queued",
                        "failed",
                        "cancelled",
                        "unknown",
                    )
                ]
                if (
                    any(not isinstance(n, int) or n < 0 for n in counts)
                    or sum(counts) != result["total"]
                ):
                    raise ValueError("Orion progress counts are inconsistent")
                workflow.put_state(db, key, {"value": result, "attempt_at": attempt})
            except Exception as exc:
                db.rollback()
                workflow.put_state(
                    db,
                    key,
                    {
                        **cache,
                        "attempt_at": attempt,
                        "error": str(exc)
                        if isinstance(exc, ValueError)
                        else type(exc).__name__,
                    },
                )


def board(db, release="@current", force=False):
    config = workflow.effective_config(db)
    current = workflow.status(db, config)
    archive_config = load_versions_config()
    versions = archive_config.get("versions", {})
    periods = {p["release"]: p for p in config.get("periods", [])}
    collections = {v["release"]: v for v in inventory(db, config)["versions"]}
    native = list(
        db.scalars(
            select(ReleaseSimulationBatch).order_by(
                ReleaseSimulationBatch.created_at.desc()
            )
        )
    )
    keys = set(versions) | set(periods) | set(collections) | {b.release for b in native}
    if current["current_version"]:
        keys.add(current["current_version"])
    selected = current["current_version"] if release == "@current" else release
    if selected not in keys:
        raise ValueError("未知版本，无法展示仿真看板")
    period = periods.get(selected)
    is_current = selected == current["current_version"]
    data = {
        "release": selected,
        "label": versions.get(selected, {}).get("label") or selected,
        "is_current": is_current,
        "period": period,
        "kind": "current" if is_current else "cycle" if period else "observation" if selected in collections else "archived",
        "collection": collections.get(selected),
        "issue_count": None,
        "scenario_count": None,
        "source_metrics": None,
        "metrics": {"available": False},
        "publication_policy": coverage_policy(config),
        "binary_id": (period or {}).get("binary_id")
        or versions.get(selected, {}).get("binary_id"),
        "synced_at": None,
        "population_complete": False,
    }
    if is_current:
        data.update(
            {
                k: current[k]
                for k in (
                    "issue_count",
                    "scenario_count",
                    "source_metrics",
                    "metrics",
                    "population_complete",
                )
            }
        )
        data["synced_at"] = (
            current["last_sync"].get("checked_at") or current["synced_at"]
        )
    elif period or selected in collections:
        snapshot = db.scalars(
            select(ReleaseIssueSnapshot)
            .where(ReleaseIssueSnapshot.release == selected)
            .order_by(ReleaseIssueSnapshot.id.desc())
            .limit(1)
        ).first()
        if snapshot:
            data.update(
                issue_count=sum(
                    int(i["ra_type"]) == 2 for i in snapshot.payload["issues"]
                ),
                scenario_count=len(snapshot.payload["scenarios"]),
                source_metrics=summarize_population(snapshot.payload["issues"], [], {}),
                metrics=workflow.metrics_for_snapshot(db, snapshot),
                synced_at=snapshot.created_at.replace(tzinfo=timezone.utc).isoformat(),
                population_complete=snapshot.payload.get("population_complete", False),
                binary_id=data["binary_id"] or snapshot.payload.get("period", {}).get("binary_id"),
            )
    if selected in collections and collections[selected]["source"] == "observation":
        collection = collections[selected]
        data.update(issue_count=collection["auto_count"], synced_at=collection["synced_at"])
    snapshot = db.scalars(
        select(DashboardSnapshot)
        .where(DashboardSnapshot.config_hash == config_hash(archive_config))
        .order_by(DashboardSnapshot.created_at.desc())
        .limit(1)
    ).first()
    historical = next(
        (
            i
            for i in (snapshot.snapshot.get("comparison", []) if snapshot else [])
            if i["version_key"] == selected
        ),
        None,
    )
    if historical and not data["metrics"].get("available") and not is_current:
        gt = historical.get("source_gt") or {}
        data.update(
            scenario_count=historical.get("total_cases"),
            source_metrics={
                "online_precision": gt.get("online_precision"),
                "online_recall": gt.get("online_recall"),
                "eligible": historical.get("evaluated_cases"),
                "excluded": None,
            },
            metrics={
                "available": historical.get("precision") is not None
                and historical.get("recall") is not None,
                "archived": True,
                "quality_gate_passed": bool(historical.get("quality_gate_passed")),
                **{
                    k: historical.get(k)
                    for k in ("precision", "recall", "sim_repro_rate")
                },
            },
            synced_at=snapshot.created_at.replace(tzinfo=timezone.utc).isoformat(),
        )
    jobs = [
        {
            "backfill": bool(b.payload.get("backfill")),
            "fingerprint": b.fingerprint,
            "job_id": b.payload.get("job_id"),
            "status": b.status,
            "scenario_count": len(b.payload.get("scenarios", [])),
            "created_at": b.created_at.replace(tzinfo=timezone.utc).isoformat(),
            "error": b.payload.get("error") or b.payload.get("last_poll_error"),
            "archived": False,
            "evaluation_task_key": b.payload.get("result_import", {}).get("task_key"),
            "primary_execution": b.payload.get("result_import", {}).get(
                "primary", False
            ),
        }
        for b in native
        if b.release == selected
    ]
    legacy_id = versions.get(selected, {}).get("sim_job_id")
    if legacy_id and str(legacy_id) not in {str(j["job_id"]) for j in jobs}:
        jobs.append(
            {
                "job_id": legacy_id,
                "status": "complete"
                if data["metrics"].get("available")
                else "verifying",
                "scenario_count": historical.get("total_cases") if historical else None,
                "archived": True,
                "error": None,
            }
        )
    refresh_ids = []
    for job in jobs:
        cache = (
            workflow.get_state(db, f"job-progress:{job['job_id']}")
            if job["job_id"]
            else {}
        )
        job.update(
            progress=cache.get("value"),
            progress_error=cache.get("error"),
            url=f"http://voyager.intra.xiaojukeji.com/static/management/#/orion/job/detail?job_id={job['job_id']}"
            if job["job_id"]
            else None,
        )
        if job["job_id"] and _due(cache, force) and current["driver_ready"]:
            refresh_ids.append(int(job["job_id"]))
    data["jobs"] = jobs
    from app.services.release_backfill import public_state as backfill_state
    from app.services.release_resume import public_state as resume_state
    data["backfill"] = backfill_state(db, selected)
    data["resume"] = resume_state(db, selected)
    from ra_api.release_tolerance import validate_frozen
    latest_plan = next((b.payload for b in native if b.release == selected and not b.payload.get("backfill") and b.payload.get("issue_tolerance")), None)
    if latest_plan:
        data["issue_tolerance"] = {**latest_plan["issue_tolerance"], **validate_frozen(latest_plan)}
    imported = (
        next(
            (
                {**b.payload["result_import"], "publication_decision": b.payload.get("publication_decision")}
                for b in native
                if b.release == selected
                and not b.payload.get("backfill")
                and b.payload.get("result_import", {}).get("primary")
                and b.payload.get("population_hash")
                == workflow.population_identity(current_snapshot.payload)
            ),
            None,
        )
        if (
            current_snapshot := db.scalars(
                select(ReleaseIssueSnapshot)
                .where(ReleaseIssueSnapshot.release == selected)
                .order_by(ReleaseIssueSnapshot.id.desc())
                .limit(1)
            ).first()
        )
        else None
    )
    approved = published_batch(db, selected)
    if approved:
        metrics = effective_publication(db, approved)
        imported = {**approved.payload["result_import"], "publication": metrics["publication"]}
        data["metrics"] = metrics
    data["evaluation"] = imported
    from ra_api.release_tolerance import grade_counts, grade
    from app.services.release_metrics import cohort_for_issue
    published_grade = data['metrics'].get('publication') or {}
    if published_grade.get('issue_count'):
        data['quality_grade'] = {**grade_counts(published_grade['issue_count'],
            published_grade['issue_count']-published_grade['valid_issue_count']), 'basis':'results'}
    elif imported and (execution := next((b for b in native if b.release == selected and not b.payload.get('backfill') and b.payload.get('result_import',{}).get('task_key') == imported.get('task_key')),None)) and execution.payload.get('issue_tolerance'):
        frozen = execution.payload['issue_tolerance']
        invalid = {str(s['issue_id']) for s in execution.payload['scenarios'] if str(s['scenario_id']) not in execution.payload.get('results',{})}
        invalid.update(str(f['issue_id']) for f in frozen['preparation_failures'])
        data['quality_grade'] = {**grade(frozen['eligible_issue_ids'],invalid), 'basis':'results'}
    elif current_snapshot and current_snapshot.payload.get('population_complete') and not current_snapshot.payload.get('mapping_error'):
        source = current_snapshot.payload
        eligible = {str(i['issue_id']) for i in source['issues'] if cohort_for_issue(i)}
        mapped = {str(s['issue_id']) for s in source['scenarios'] if s.get('issue_id')}
        if eligible:
            data['quality_grade'] = {**grade(eligible, eligible-mapped), 'basis':'preparation'}

    from app.services.label_cycle import public_state
    data["label_cycle"] = public_state(db, selected)
    from app.services.release_anomalies import collection_anomalies
    data["collection_anomalies"] = collection_anomalies(db, selected, data.get("collection"), native)
    return {
        "versions": [
            {
                "release": key,
                "is_current": key == current["current_version"],
                "cycle_status": periods.get(key, {}).get("status"),
                "collection_status": collections.get(key, {}).get("collection_status"),
                "has_job": any(b.release == key for b in native)
                or bool(versions.get(key, {}).get("sim_job_id")),
            }
            for key in sorted(keys, reverse=True)
        ],
        "selected": data,
        "mode": current["mode"],
        "driver_ready": current["driver_ready"],
        "scheduler_enabled": current["scheduler_enabled"],
        "current_status": current["status"],
        "refreshing": bool(refresh_ids),
        "refresh_job_ids": refresh_ids,
    }
