"""Lightweight zero-dependency Prometheus metrics & structured request logging."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger("ra_triage_dashboard.access")

_DURATION_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
_ID_SEGMENT_RE = re.compile(
    r"/(?:cn\d+|run-[A-Za-z0-9_-]+|split-[A-Za-z0-9_-]+|campaign-[A-Za-z0-9_-]+|exp-[A-Za-z0-9_-]+|\d+)(?=/|$)"
)


def normalize_route_group(path: str) -> str:
    """Collapse high-cardinality ID segments so Prometheus labels stay bounded."""
    if not path:
        return "/"
    if path.startswith("/static/"):
        return "/static/*"
    normalized = _ID_SEGMENT_RE.sub("/:id", path)
    parts = [p for p in normalized.split("/") if p]
    if len(parts) > 4:
        return "/" + "/".join(parts[:4]) + "/*"
    return normalized


class ObservabilityRegistry:
    """Thread-safe in-process HTTP/DB/worker observability counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._request_counts: dict[tuple[str, str, str], int] = {}
        self._duration_buckets: dict[float, int] = {b: 0 for b in _DURATION_BUCKETS}
        self._duration_count = 0
        self._duration_sum = 0.0
        self._slow_requests_total = 0

    def record_http_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        request_id: str = "",
        slow_threshold_ms: float = 500.0,
    ) -> None:
        route_group = normalize_route_group(path)
        status_class = f"{max(0, int(status_code)) // 100}xx"
        duration_s = max(0.0, float(duration_ms) / 1000.0)
        is_slow = path.startswith("/api/") and duration_ms >= slow_threshold_ms

        with self._lock:
            key = (method.upper(), route_group, status_class)
            self._request_counts[key] = self._request_counts.get(key, 0) + 1
            self._duration_count += 1
            self._duration_sum += duration_s
            for bound in _DURATION_BUCKETS:
                if duration_s <= bound:
                    self._duration_buckets[bound] += 1
            if is_slow:
                self._slow_requests_total += 1

        if os.getenv("DASHBOARD_JSON_LOGS", "").strip().lower() in {"1", "true", "yes"}:
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": method,
                        "path": path,
                        "route_group": route_group,
                        "status": status_code,
                        "duration_ms": round(duration_ms, 2),
                        "slow": is_slow,
                    },
                    ensure_ascii=False,
                )
            )

    def render_prometheus(
        self,
        *,
        db_pool_stats: dict[str, Any] | None = None,
        active_leases: int | None = None,
    ) -> str:
        """Render standard Prometheus 0.0.4 text exposition format."""
        lines: list[str] = []
        uptime = max(0.0, time.monotonic() - self._started_at)

        with self._lock:
            counts_snapshot = sorted(self._request_counts.items())
            buckets_snapshot = dict(self._duration_buckets)
            dur_count = self._duration_count
            dur_sum = self._duration_sum
            slow_total = self._slow_requests_total

        lines.append("# HELP ra_triage_process_uptime_seconds Process uptime in seconds.")
        lines.append("# TYPE ra_triage_process_uptime_seconds gauge")
        lines.append(f"ra_triage_process_uptime_seconds {uptime:.3f}")

        lines.append("# HELP ra_triage_http_requests_total Total HTTP requests by method, route group, and status class.")
        lines.append("# TYPE ra_triage_http_requests_total counter")
        for (method, route_group, status_class), count in counts_snapshot:
            escaped_route = route_group.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(
                f'ra_triage_http_requests_total{{method="{method}",route="{escaped_route}",status="{status_class}"}} {count}'
            )

        lines.append("# HELP ra_triage_http_slow_requests_total Total slow API requests (>=500ms).")
        lines.append("# TYPE ra_triage_http_slow_requests_total counter")
        lines.append(f"ra_triage_http_slow_requests_total {slow_total}")

        lines.append("# HELP ra_triage_http_request_duration_seconds HTTP request duration histogram.")
        lines.append("# TYPE ra_triage_http_request_duration_seconds histogram")
        for bound in _DURATION_BUCKETS:
            lines.append(
                f'ra_triage_http_request_duration_seconds_bucket{{le="{bound}"}} {buckets_snapshot[bound]}'
            )
        lines.append(f'ra_triage_http_request_duration_seconds_bucket{{le="+Inf"}} {dur_count}')
        lines.append(f"ra_triage_http_request_duration_seconds_sum {dur_sum:.6f}")
        lines.append(f"ra_triage_http_request_duration_seconds_count {dur_count}")

        if db_pool_stats:
            lines.append("# HELP ra_triage_db_pool_stat PostgreSQL connection pool metrics.")
            lines.append("# TYPE ra_triage_db_pool_stat gauge")
            for k, v in sorted(db_pool_stats.items()):
                if isinstance(v, (int, float)):
                    lines.append(f'ra_triage_db_pool_stat{{metric="{k}"}} {v}')

        if active_leases is not None:
            lines.append("# HELP ra_triage_worker_leases_active Active background worker leases.")
            lines.append("# TYPE ra_triage_worker_leases_active gauge")
            lines.append(f"ra_triage_worker_leases_active {int(active_leases)}")

        return "\n".join(lines) + "\n"


metrics_registry = ObservabilityRegistry()
