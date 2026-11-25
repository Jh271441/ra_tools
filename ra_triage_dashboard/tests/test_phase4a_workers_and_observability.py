"""Phase 4A: Worker leases, standalone worker daemon, observability /metrics, and migration 064 gate."""
from __future__ import annotations

import asyncio
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.core.observability import ObservabilityRegistry, normalize_route_group
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.main import app
from ra_triage_dashboard.app.workers.leases import WorkerLeaseManager
from ra_triage_dashboard.scripts.deploy_cloud import validate_additive_migration_sql


async def _asgi_get(
    target_app,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> tuple[int, dict[str, str], bytes]:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": (client_host, 54321),
        "server": ("127.0.0.1", 8785),
    }
    status_code = 500
    resp_headers: dict[str, str] = {}
    body_chunks: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
            for k, v in message.get("headers", []):
                resp_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    await target_app(scope, receive, send)
    return status_code, resp_headers, b"".join(body_chunks)


class Phase4AWorkersAndObservabilityTest(unittest.TestCase):
    def test_worker_lease_mutual_exclusion_renewal_expiry_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "leases.db")
            db.init()
            try:
                mgr_a = WorkerLeaseManager(db, owner_id="worker-a")
                mgr_b = WorkerLeaseManager(db, owner_id="worker-b")
                t0 = dt.datetime(2026, 11, 25, 2, 0, 0, tzinfo=dt.timezone.utc)

                # Worker A acquires cleanly
                self.assertTrue(mgr_a.try_acquire_or_renew("gt-sync", ttl_seconds=60, now=t0))
                # Worker B is rejected while active
                self.assertFalse(
                    mgr_b.try_acquire_or_renew(
                        "gt-sync", ttl_seconds=60, now=t0 + dt.timedelta(seconds=30)
                    )
                )
                # Worker A renews cleanly
                self.assertTrue(
                    mgr_a.try_acquire_or_renew(
                        "gt-sync", ttl_seconds=60, now=t0 + dt.timedelta(seconds=45)
                    )
                )
                active = mgr_a.list_active_leases(now=t0 + dt.timedelta(seconds=50))
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0]["owner_id"], "worker-a")

                # Worker B cannot release Worker A's lease
                self.assertFalse(mgr_b.release("gt-sync"))

                # After expiry (t0 + 110s > t0 + 45 + 60), Worker B takes over cleanly
                self.assertTrue(
                    mgr_b.try_acquire_or_renew(
                        "gt-sync", ttl_seconds=60, now=t0 + dt.timedelta(seconds=110)
                    )
                )
                # Explicit release frees the lease immediately
                self.assertTrue(mgr_b.release("gt-sync"))
                self.assertEqual(
                    mgr_a.list_active_leases(now=t0 + dt.timedelta(seconds=115)), []
                )
            finally:
                db.close()

    def test_migration_064_passes_strict_additive_validator(self) -> None:
        mig_path = (
            Path(__file__).resolve().parents[1]
            / "migrations/postgres/064_worker_leases_and_intent_reallocation.sql"
        )
        content = mig_path.read_text(encoding="utf-8")
        # Must not raise DeployError
        validate_additive_migration_sql(
            "ra_triage_dashboard/migrations/postgres/064_worker_leases_and_intent_reallocation.sql",
            content,
        )

    def test_observability_registry_and_loopback_metrics_endpoint(self) -> None:
        reg = ObservabilityRegistry()
        self.assertEqual(normalize_route_group("/api/cases/cn37631883/comments"), "/api/cases/:id/comments")
        reg.record_http_request(method="GET", path="/api/status", status_code=200, duration_ms=12.5)
        reg.record_http_request(method="POST", path="/api/cases/cn123/review", status_code=200, duration_ms=650.0)
        text = reg.render_prometheus(db_pool_stats={"pool_size": 10}, active_leases=2)
        self.assertIn("ra_triage_http_requests_total", text)
        self.assertIn("ra_triage_http_slow_requests_total 1", text)
        self.assertIn("ra_triage_worker_leases_active 2", text)
        self.assertIn('ra_triage_db_pool_stat{metric="pool_size"} 10', text)

        status_ok, hdrs_ok, body_ok = asyncio.run(_asgi_get(app, "/metrics"))
        self.assertEqual(status_ok, 200)
        self.assertIn("ra_triage_process_uptime_seconds", body_ok.decode("utf-8"))
        self.assertIn("x-request-id", hdrs_ok)

        # Proxy-forwarded external requests must be rejected (403)
        status_fwd, _, _ = asyncio.run(
            _asgi_get(app, "/metrics", headers={"X-Forwarded-For": "10.1.2.3"})
        )
        self.assertEqual(status_fwd, 403)

        # Non-loopback direct client must also be rejected (403)
        status_ext, _, _ = asyncio.run(
            _asgi_get(app, "/metrics", client_host="10.20.30.40")
        )
        self.assertEqual(status_ext, 403)


if __name__ == "__main__":
    unittest.main()
