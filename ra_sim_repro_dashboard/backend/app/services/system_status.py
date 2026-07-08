from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Issue, RefreshJob, Scenario, ScenarioVersionResult, Version


REFRESH_QUEUE_NAME = "ra_dashboard_refresh"
_STARTED_AT = datetime.now(timezone.utc)


def _safe_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return url


def _redis_safe_url(url: str) -> str:
    # redis://:password@host:port/db -> hide password
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username or ''}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
        return url
    except Exception:
        return url


def _check_database(db: Session) -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "database",
        "status": "error",
        "latency_ms": None,
        "detail": _safe_url(settings.database_url),
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
        ):
            counts[label] = int(db.execute(select(func.count()).select_from(model)).scalar_one())
        check["extra"] = {"dialect": db.get_bind().dialect.name, **counts}
    except Exception as exc:
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        check["error"] = str(exc)
    return check


def _check_redis() -> tuple[dict[str, Any], Any]:
    check: dict[str, Any] = {
        "key": "redis",
        "status": "error",
        "latency_ms": None,
        "detail": _redis_safe_url(settings.redis_url),
        "extra": {},
    }
    if not settings.enable_rq:
        # Redis is unused in this mode; avoid paying the connect timeout on every poll.
        check["status"] = "skipped"
        check["detail"] = f"{check['detail']} (ENABLE_RQ=0)"
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
        check["error"] = str(exc)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        return check, None
    # Connectivity is confirmed; INFO is enrichment only and must not flip the
    # status or drop the client that the queue check still needs.
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
        check["error"] = f"INFO unavailable: {exc}"
    return check, client


def _check_queue(redis_client: Any) -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "queue",
        "status": "skipped",
        "latency_ms": None,
        "detail": REFRESH_QUEUE_NAME,
        "extra": {},
    }
    if not settings.enable_rq:
        check["detail"] = f"{REFRESH_QUEUE_NAME} (ENABLE_RQ=0, using FastAPI background tasks)"
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
        check["error"] = str(exc)
    return check


def _check_versions_config() -> dict[str, Any]:
    from app.config import config_hash, load_versions_config

    check: dict[str, Any] = {
        "key": "versions_config",
        "status": "error",
        "latency_ms": None,
        "detail": str(settings.versions_config),
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
        check["error"] = str(exc)
    return check


def _check_mock_data() -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "mock_data",
        "status": "warn",
        "latency_ms": None,
        "detail": str(settings.mock_data_dir),
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
        check["error"] = str(exc)
    return check


def _check_last_refresh(db: Session) -> dict[str, Any]:
    check: dict[str, Any] = {
        "key": "last_refresh",
        "status": "warn",
        "latency_ms": None,
        "detail": "",
        "extra": {},
    }
    try:
        job = db.execute(
            select(RefreshJob).order_by(RefreshJob.created_at.desc()).limit(1)
        ).scalars().first()
        if job is None:
            check["error"] = "No refresh job has run yet"
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
            check["status"] = "error"
            check["error"] = job.error or job.message or "Refresh job failed"
        else:
            check["status"] = "warn"
            check["error"] = f"Refresh job is {job.status}"
    except Exception as exc:
        check["status"] = "error"
        check["error"] = str(exc)
    return check


def collect_system_status(db: Session) -> dict[str, Any]:
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
    ]
    statuses = {item["status"] for item in checks}
    if "error" in statuses:
        overall = "error"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"
    now = datetime.now(timezone.utc)
    return {
        "overall": overall,
        "generated_at": now,
        "app_started_at": _STARTED_AT,
        "uptime_seconds": int((now - _STARTED_AT).total_seconds()),
        "enable_rq": settings.enable_rq,
        "checks": checks,
    }
