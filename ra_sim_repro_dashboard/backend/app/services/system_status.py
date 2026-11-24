from __future__ import annotations

import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import DATA_DIR, config_hash, load_versions_config, mock_data_disabled, settings
from app.models import (
    Issue,
    RefreshJob,
    ReleaseSimulationBatch,
    ReleaseWorkflowState,
    Scenario,
    ScenarioVersionResult,
    Version,
)
from app.repositories import state_store


REFRESH_QUEUE_NAME = "ra_dashboard_refresh"
_STARTED_AT = datetime.now(timezone.utc)
_ACTIVE_BATCH_STATUSES = ("queued", "submitting", "submission_uncertain", "running", "verifying")


def _safe_db_label(db: Session) -> str:
    try:
        return f"{db.get_bind().dialect.name} (configured)"
    except Exception:
        return "database (configured)"


def _check_database(db: Session) -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "database",
        "status": "error",
        "latency_ms": None,
        "detail": _safe_db_label(db),
        "extra": {},
    }
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["status"] = "ok"
        counts: dict[str, int] = {}
        for label, model in (
            ("versions", Version),
            ("issues", Issue),
            ("scenarios", Scenario),
            ("results", ScenarioVersionResult),
            ("workflow_states", ReleaseWorkflowState),
            ("simulation_batches", ReleaseSimulationBatch),
        ):
            counts[label] = int(db.execute(select(func.count()).select_from(model)).scalar_one())
        check["extra"] = {"dialect": db.get_bind().dialect.name, **counts}
    except Exception as exc:
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["error"] = f"database_check_failed ({type(exc).__name__})"
        db.rollback()
    return check


def _check_redis() -> tuple[dict[str, Any], Any]:
    check: dict[str, Any] = {
        "key": "redis",
        "status": "error",
        "latency_ms": None,
        "detail": "redis (configured)",
        "extra": {},
    }
    if not settings.enable_rq:
        check["status"] = "skipped"
        check["detail"] = "redis (ENABLE_RQ=0)"
        return check, None
    client = None
    started = time.perf_counter()
    try:
        import redis

        client = redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["status"] = "ok"
    except Exception as exc:
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["error"] = f"redis_unavailable ({type(exc).__name__})"
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        return check, None
    try:
        info = client.info(section="server")
        memory = client.info(section="memory")
        clients = client.info(section="clients")
        check["extra"] = {
            "redis_version": info.get("redis_version", ""),
            "uptime_days": round(info.get("uptime_in_seconds", 0) / 86400, 1),
            "used_memory": memory.get("used_memory_human", ""),
            "connected_clients": clients.get("connected_clients", 0),
        }
    except Exception as exc:
        check["error"] = f"redis_info_unavailable ({type(exc).__name__})"
    return check, client


def _check_queue(redis_client: Any) -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "queue",
        "status": "skipped",
        "latency_ms": None,
        "detail": REFRESH_QUEUE_NAME,
        "extra": {"pending_jobs": 0, "workers": 0, "failed_jobs": 0},
    }
    if not settings.enable_rq:
        check["detail"] = f"{REFRESH_QUEUE_NAME} (ENABLE_RQ=0, retired v1 queue)"
        return check
    if redis_client is None:
        check["status"] = "error"
        check["error"] = "Redis unavailable"
        return check
    started = time.perf_counter()
    try:
        from rq import Queue, Worker

        queue = Queue(REFRESH_QUEUE_NAME, connection=redis_client)
        workers = Worker.all(queue=queue)
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["extra"] = {
            "pending_jobs": queue.count,
            "workers": len(workers),
            "failed_jobs": queue.failed_job_registry.count,
        }
        check["status"] = "ok" if workers else "warn"
        if not workers:
            check["error"] = "No RQ worker is listening on this queue"
    except Exception as exc:
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["status"] = "error"
        check["error"] = f"queue_check_failed ({type(exc).__name__})"
    return check


def _check_versions_config() -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "versions_config",
        "status": "error",
        "latency_ms": None,
        "detail": settings.versions_config.name,
        "extra": {},
    }
    started = time.perf_counter()
    try:
        payload = load_versions_config()
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        versions = payload.get("versions", {}) or {}
        current = str(payload.get("current_version") or "")
        check["extra"] = {
            "config_hash": config_hash(payload),
            "current_version": current,
            "version_count": len(versions),
            "compare_count": len(payload.get("compare_versions", []) or []),
        }
        if not settings.versions_config.exists():
            check["status"] = "warn"
            check["error"] = "versions.yaml missing; using fallback/example config"
        elif not current or not versions:
            check["status"] = "warn"
            check["error"] = "Config loaded but current_version/versions is empty"
        else:
            check["status"] = "ok"
    except Exception as exc:
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["error"] = f"versions_config_failed ({type(exc).__name__})"
    return check


def _check_mock_data() -> dict[str, Any]:
    if mock_data_disabled():
        return {
            "key": "mock_data",
            "status": "skipped",
            "latency_ms": None,
            "detail": "Mock data disabled",
            "extra": {},
        }
    check: dict[str, Any] = {
        "key": "mock_data",
        "status": "warn",
        "latency_ms": None,
        "detail": settings.mock_data_dir.name,
        "extra": {},
    }
    try:
        if settings.mock_data_dir.is_dir():
            files = sorted(settings.mock_data_dir.glob("*.json"))
            check["status"] = "ok" if files else "warn"
            check["extra"] = {"json_files": len(files)}
            if not files:
                check["error"] = "Mock data directory is empty"
        else:
            check["error"] = "Mock data directory does not exist"
    except Exception as exc:
        check["status"] = "error"
        check["error"] = f"mock_data_check_failed ({type(exc).__name__})"
    return check


def _check_last_refresh(db: Session) -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "last_refresh",
        "status": "skipped",
        "latency_ms": None,
        "detail": "legacy v1 archive",
        "extra": {"job_status": "idle"},
    }
    try:
        job = (
            db.execute(select(RefreshJob).order_by(RefreshJob.created_at.desc()).limit(1))
            .scalars()
            .first()
        )
        if job is None:
            return check
        check["detail"] = job.job_id
        check["extra"] = {
            "job_status": job.status,
            "progress": job.progress,
            "created_at": f"{job.created_at.isoformat()}Z" if job.created_at else "",
            "finished_at": f"{job.finished_at.isoformat()}Z" if job.finished_at else "",
        }
        if job.status == "completed":
            check["status"] = "ok"
        elif job.status == "failed":
            check["status"] = "warn"
            check["error"] = "Legacy v1 refresh failed"
        else:
            check["status"] = "warn"
            check["error"] = f"Legacy v1 refresh is {job.status}"
    except Exception as exc:
        check["status"] = "error"
        check["error"] = f"last_refresh_check_failed ({type(exc).__name__})"
    return check


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _check_release_workflow(db: Session, now: datetime) -> dict[str, Any]:
    enabled = os.getenv("RELEASE_WORKFLOW_ENABLED") == "1"
    check: dict[str, Any] = {
        "key": "release_workflow",
        "status": "ok" if enabled else "skipped",
        "latency_ms": None,
        "detail": f"runner={os.getenv('RELEASE_WORKFLOW_RUNNER', 'api')}",
        "extra": {
            "enabled": enabled,
            "active_batches": 0,
            "submitting_batches": 0,
            "uncertain_batches": 0,
        },
    }
    try:
        active = db.scalars(
            select(ReleaseSimulationBatch).where(
                ReleaseSimulationBatch.status.in_(_ACTIVE_BATCH_STATUSES)
            )
        ).all()
        submitting = sum(b.status == "submitting" for b in active)
        uncertain = sum(b.status == "submission_uncertain" for b in active)
        poll_row = db.get(ReleaseWorkflowState, "source_poll")
        monitor_row = db.get(ReleaseWorkflowState, "release_monitor")
        last_poll = _parse_iso((poll_row.payload if poll_row else {}).get("started_at"))
        last_monitor = _parse_iso((monitor_row.payload if monitor_row else {}).get("checked_at"))
        poll_age_s = int((now - last_poll).total_seconds()) if last_poll else None
        check["extra"].update(
            active_batches=len(active),
            submitting_batches=submitting,
            uncertain_batches=uncertain,
            last_poll_at=last_poll.isoformat() if last_poll else "",
            last_monitor_at=last_monitor.isoformat() if last_monitor else "",
            poll_age_seconds=poll_age_s,
        )
        if uncertain:
            check["status"] = "error"
            check["error"] = f"{uncertain} batch(es) in submission_uncertain"
        elif enabled and poll_age_s is not None and poll_age_s > 3 * 3600:
            check["status"] = "warn"
            check["error"] = f"Release poll stale ({poll_age_s}s ago)"
    except Exception as exc:
        check["status"] = "error"
        check["error"] = f"release_workflow_check_failed ({type(exc).__name__})"
        db.rollback()
    return check


def _check_label_sidecar(db: Session, now: datetime) -> dict[str, Any]:
    enabled = os.getenv("LABEL_REFRESH_ENABLED") == "1"
    check: dict[str, Any] = {
        "key": "label_sidecar",
        "status": "ok" if enabled else "skipped",
        "latency_ms": None,
        "detail": "enabled" if enabled else "disabled",
        "extra": {"enabled": enabled, "tracked_releases": 0, "stale_releases": 0},
    }
    if not enabled:
        return check
    try:
        rows = db.scalars(
            select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("label_cycle:"))
        ).all()
        stale = 0
        latest_check: datetime | None = None
        for row in rows:
            checked = _parse_iso((row.payload or {}).get("checked_at"))
            if checked:
                if latest_check is None or checked > latest_check:
                    latest_check = checked
                if (now - checked).total_seconds() > 3 * 3600:
                    stale += 1
        check["extra"].update(
            tracked_releases=len(rows),
            stale_releases=stale,
            last_checked_at=latest_check.isoformat() if latest_check else "",
        )
        if stale:
            check["status"] = "warn"
            check["error"] = f"{stale} label cycle(s) stale (>3h)"
    except Exception as exc:
        check["status"] = "error"
        check["error"] = f"label_sidecar_check_failed ({type(exc).__name__})"
        db.rollback()
    return check


def _check_evaluation_worker(db: Session) -> dict[str, Any]:
    enabled = os.getenv("EVALUATION_WORKER_ENABLED", "1") == "1"
    cron_enabled = enabled and os.getenv("EVALUATION_CRON_ENABLED") == "1"
    check: dict[str, Any] = {
        "key": "evaluation_worker",
        "status": "ok" if enabled else "skipped",
        "latency_ms": None,
        "detail": f"runner={os.getenv('EVALUATION_WORKER_RUNNER', 'api')} cron={'on' if cron_enabled else 'off'}",
        "extra": {
            "enabled": enabled,
            "cron_enabled": cron_enabled,
            "active_executions": 0,
            "active_starts": 0,
        },
    }
    try:
        active_exec = state_store.count_active_executions(db)
        active_starts = int(
            db.scalar(
                select(func.count())
                .select_from(ReleaseWorkflowState)
                .where(
                    ReleaseWorkflowState.key.startswith("evstart:"),
                    ReleaseWorkflowState.payload["status"].as_string() == "preparing",
                )
            )
            or 0
        )
        check["extra"].update(active_executions=active_exec, active_starts=active_starts)
    except Exception as exc:
        check["status"] = "error"
        check["error"] = f"evaluation_worker_check_failed ({type(exc).__name__})"
        db.rollback()
    return check


def _check_shuyi_session(now: datetime) -> dict[str, Any]:
    default_state = DATA_DIR / "private" / "shuyi_storage_state.json"
    path = Path(os.getenv("AUTO_TRIAGE_SHUYI_STORAGE_STATE", str(default_state)))
    check: dict[str, Any] = {
        "key": "shuyi_session",
        "status": "skipped",
        "latency_ms": None,
        "detail": path.name,
        "extra": {"exists": False},
    }
    try:
        if not path.exists():
            check["status"] = "warn"
            check["error"] = "Shuyi storage state file not found"
            return check
        st = path.stat()
        age_hours = round((now.timestamp() - st.st_mtime) / 3600, 1)
        group_other = bool(stat.S_IMODE(st.st_mode) & 0o077)
        check["extra"] = {"exists": True, "age_hours": age_hours, "permissions_ok": not group_other}
        if group_other:
            check["status"] = "warn"
            check["error"] = "Shuyi storage state should be chmod 0600"
        else:
            check["status"] = "ok"
    except Exception as exc:
        check["status"] = "error"
        check["error"] = f"shuyi_session_check_failed ({type(exc).__name__})"
    return check


def collect_system_status(db: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    database = _check_database(db)
    redis_check, redis_client = _check_redis()
    queue = _check_queue(redis_client)
    if redis_client is not None:
        try:
            redis_client.close()
        except Exception:
            pass
    checks = [
        database,
        redis_check,
        queue,
        _check_versions_config(),
        _check_mock_data(),
        _check_last_refresh(db),
        _check_release_workflow(db, now),
        _check_label_sidecar(db, now),
        _check_evaluation_worker(db),
        _check_shuyi_session(now),
    ]
    statuses = {item["status"] for item in checks}
    if "error" in statuses:
        overall = "error"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"
    return {
        "overall": overall,
        "generated_at": now,
        "app_started_at": _STARTED_AT,
        "uptime_seconds": int((now - _STARTED_AT).total_seconds()),
        "enable_rq": settings.enable_rq,
        "checks": checks,
    }
