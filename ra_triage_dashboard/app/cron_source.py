"""Bounded read-only adapter for the independent Cron Observatory.

The browser uses the Workbench's existing origin/SSO path. No scheduler is
imported, executed or restarted here; only three fixed loopback GETs are made.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
import time
from pathlib import Path
from typing import Any
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .timed_cache import TimedSingleFlightCache
from .cron_media_source import media_snapshot
from .cron_timing import add_main_timings

MAX_RESPONSE_BYTES = 2_000_000
SOURCE_PATHS = {
    "overview": "/api/overview",
    "history": "/api/history",
    "sidecar": "/api/manual-sidecar",
}
_cache: TimedSingleFlightCache[str, dict] = TimedSingleFlightCache(
    ttl_seconds=5, max_entries=1,
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _number(value: Any) -> int | float | None:
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _text(value: Any, limit: int = 160) -> str:
    return str(value)[:limit] if isinstance(value, str) else ""


def _rows(value: Any, limit: int = 100) -> list[dict]:
    return [row for row in value[:limit] if isinstance(row, dict)] if isinstance(value, list) else []


def _project(row: dict, numbers: str, texts: str = "", flags: str = "") -> dict:
    return {
        **{key: _number(row.get(key)) for key in numbers.split()},
        **{key: _text(row.get(key)) for key in texts.split()},
        **{key: row.get(key) is True for key in flags.split()},
    }


def _case_failures(rows: Any) -> list[dict]:
    # Never forward exception text, bags/paths, request bodies or raw logs.
    return [
        {"issue_id": row["issue_id"], "code": _text(row.get("code"), 80)}
        for row in _rows(rows, 500)
        if re.fullmatch(r"[A-Za-z0-9_-]{3,128}", str(row.get("issue_id", "")))
    ]


def _overview(payload: Any) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValueError("invalid overview")
    daily = payload["daily"]
    runs = []
    for row in _rows(daily.get("runs")):
        run = _project(
            row,
            "total finished succeeded percent failure_count updated_at started_at "
            "elapsed_seconds selected inferred skipped coverage published verified",
            "id target_date_cst state health stage", "target_is_weekend",
        )
        run["skipped_cases"] = _case_failures(row.get("skipped_cases"))
        run["failure_details"] = _case_failures(row.get("failure_details"))
        run["evidence_error"] = bool(row.get("errors"))
        runs.append(run)
    return {
        **_project(payload, "collected_at", flags="stale collector_error"),
        "daily": {
            **_project(daily, "heartbeat_at first_run_at next_run_at stall_seconds", "health target_date timezone"),
            "runs": runs,
            # Messages are constructed by the monitor, but file errors can
            # contain paths. The UI translates these stable kinds instead.
            "alerts": [_project(row, "", "kind severity") for row in _rows(daily.get("alerts"))],
            "launches": [_project(row, "returncode", "date_cst target_date_cst started_at finished_at state") for row in _rows(daily.get("launches"))],
            "recoveries": [_project(row, "returncode attempt", "date_cst target_date_cst started_at finished_at state") for row in _rows(daily.get("recoveries"))],
        },
        "jobs": [_project(row, "log_updated_at log_age_seconds", "id name schedule evidence") for row in _rows(payload.get("jobs"), 300)],
    }


def _history(payload: Any) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError("invalid history")
    return [_project(row, "at severity observations") for row in _rows(payload, 48)]


def _sidecar(payload: Any) -> dict:
    if not isinstance(payload, dict) or "state" not in payload:
        raise ValueError("invalid sidecar")
    result = _project(
        payload, "total imported media_verified failure_count updated_at", "state",
        "controller_error stale daily_enabled frontend_ready",
    )
    result["main_pipeline_affected"] = False
    for key in ("camera", "bev_pilot", "bev_backfill"):
        row = payload.get(key) if isinstance(payload.get(key), dict) else {}
        result[key] = _project(row, "total completed failed remaining", "status")
    return result


def _fetch(source: str) -> Any:
    # No browser-supplied URL/path, environment proxy or redirect is accepted.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(
        "http://127.0.0.1:8791" + SOURCE_PATHS[source],
        headers={"Accept": "application/json"}, method="GET",
    )
    with opener.open(request, timeout=2) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_RESPONSE_BYTES:
            raise ValueError("oversized monitor response")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("oversized monitor response")
    return json.loads(raw)


def _snapshot(ra_root: Path | None = None) -> dict:
    result: dict = {"observed_at": time.time(), "refresh_seconds": 30, "sources": {}}
    projectors = {"overview": _overview, "history": _history, "sidecar": _sidecar}
    # A missing sidecar/history must not hide the main pipeline, or vice versa.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {key: pool.submit(_fetch, key) for key in SOURCE_PATHS}
        for key, future in futures.items():
            try:
                result[key] = projectors[key](future.result())
                result["sources"][key] = "ready"
            except (OSError, ValueError, TypeError):
                result[key] = None
                result["sources"][key] = "unavailable"
    if result.get("overview") is not None:
        add_main_timings(result["overview"], ra_root)
    if ra_root is not None:
        try:
            result["media_daily"] = media_snapshot(ra_root)
            result["sources"]["media_daily"] = "ready"
        except (OSError, ValueError, TypeError, AttributeError):
            result["media_daily"] = None
            result["sources"]["media_daily"] = "unavailable"
    if ra_root is not None:
        try:
            from .cron_closeup_source import closeup_status
            result["closeup"] = closeup_status(ra_root)
        except (OSError, ValueError, TypeError, KeyError):
            result["closeup"] = {"state": "unavailable", "stale": True}
        try:
            from .cron_version_source import version_status
            result['incremental'] = version_status(ra_root)
        except (OSError,ValueError,TypeError,KeyError):
            result['incremental'] = {'enabled':True,'stale':True,'states':{},'datasets':[],'media':{}}
    return result


def cron_snapshot(ra_root: Path | None = None) -> dict:
    return _cache.get_or_load(str(ra_root), lambda: _snapshot(ra_root))
