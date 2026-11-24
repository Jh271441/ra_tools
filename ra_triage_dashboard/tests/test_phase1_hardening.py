"""Regression tests for Phase 1 DB concurrency, lock granularity, caching, and SSO single-flight."""
from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.responses import Response

from ra_triage_dashboard.app.auth import KylinSSOValidator
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.shared import _postgres_sql
from ra_triage_dashboard.app.routers import core as core_router
from ra_triage_dashboard.app.support import external_links


class Phase1ConcurrencyAndDbTest(unittest.TestCase):
    def test_write_lock_serializes_sqlite_but_is_noop_on_postgresql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "lock-mode.sqlite")
            try:
                # SQLite mode: second thread blocks while first holds _write_lock.
                entered = threading.Event()
                release = threading.Event()
                second_acquired = threading.Event()

                def _hold():
                    with db._write_lock:
                        entered.set()
                        release.wait(timeout=3.0)

                def _try_acquire():
                    with db._write_lock:
                        second_acquired.set()

                t1 = threading.Thread(target=_hold, daemon=True)
                t1.start()
                self.assertTrue(entered.wait(timeout=2.0))
                t2 = threading.Thread(target=_try_acquire, daemon=True)
                t2.start()
                self.assertFalse(second_acquired.wait(timeout=0.1))
                release.set()
                t1.join(timeout=2.0)
                t2.join(timeout=2.0)
                self.assertTrue(second_acquired.is_set())

                # PostgreSQL mode: _write_lock is a zero-contention no-op.
                db.backend = "postgresql"
                entered.clear()
                release.clear()
                second_acquired.clear()

                t3 = threading.Thread(target=_hold, daemon=True)
                t3.start()
                self.assertTrue(entered.wait(timeout=2.0))
                t4 = threading.Thread(target=_try_acquire, daemon=True)
                t4.start()
                self.assertTrue(second_acquired.wait(timeout=1.0))
                release.set()
                t3.join(timeout=2.0)
                t4.join(timeout=2.0)
            finally:
                db.close()

    def test_lock_task_work_uses_shared_vs_exclusive_advisory_lock_on_postgres(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "advisory.sqlite")
            try:
                db.backend = "postgresql"
                executed: list[tuple[str, tuple[object, ...]]] = []

                class _Conn:
                    in_transaction = True

                    def execute(self, sql, params=()):
                        executed.append((sql, tuple(params)))

                db._lock_task_work_shared(_Conn())
                db._lock_task_work(_Conn())
                self.assertIn("pg_advisory_xact_lock_shared", executed[0][0])
                self.assertIn("pg_advisory_xact_lock(", executed[1][0])
                self.assertEqual(executed[0][1], ("campaign-work-allocation-v1",))
                self.assertEqual(executed[1][1], ("campaign-work-allocation-v1",))
            finally:
                db.close()

    def test_postgres_sql_is_lru_cached(self) -> None:
        _postgres_sql.cache_clear()
        sql = "SELECT * FROM issues WHERE issue_id = ? AND scenario LIKE ?"
        first = _postgres_sql(sql)
        second = _postgres_sql(sql)
        self.assertEqual(first, second)
        self.assertIn("ILIKE %s", first)
        info = _postgres_sql.cache_info()
        self.assertGreaterEqual(info.hits, 1)

    def test_ensure_postgres_pool_is_thread_safe_single_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "pool.sqlite")
            db.backend = "postgresql"
            db.database_url = "postgresql://localhost/unused"
            created = {"count": 0}
            barrier = threading.Barrier(4)

            def _fake_pool(**kwargs):
                time.sleep(0.05)
                created["count"] += 1
                return SimpleNamespace(close=lambda: None, kwargs=kwargs)

            with patch.object(db, "_postgres_dependencies", return_value=(None, object(), _fake_pool)):
                def _worker():
                    barrier.wait()
                    db._ensure_postgres_pool()

                threads = [threading.Thread(target=_worker) for _ in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=3.0)
            self.assertEqual(created["count"], 1)
            db.close()

    def test_apply_postgres_migrations_uses_advisory_lock_and_wraps_non_transactional_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mig_dir = Path(tmp) / "migrations"
            mig_dir.mkdir()
            (mig_dir / "001_begin.sql").write_text("BEGIN;\nCREATE TABLE t1(id int);\nCOMMIT;\n", encoding="utf-8")
            (mig_dir / "002_plain.sql").write_text("CREATE TABLE t2(id int);\n", encoding="utf-8")
            db = Database("postgresql://localhost/unused", postgres_migrations_dir=mig_dir)

            events: list[str] = []

            class _Txn:
                def __enter__(self):
                    events.append("txn_enter")
                    return self

                def __exit__(self, *args):
                    events.append("txn_exit")
                    return False

            class _FakeConn:
                def __enter__(self): return self
                def __exit__(self, *args): return False

                def transaction(self):
                    return _Txn()

                def execute(self, sql, params=()):
                    events.append(sql.strip().splitlines()[0][:55])
                    if "SELECT version FROM dashboard_schema_migrations" in sql:
                        return SimpleNamespace(fetchall=lambda: [])
                    return SimpleNamespace(fetchall=lambda: [])

            fake_psycopg = SimpleNamespace(connect=lambda *a, **kw: _FakeConn())
            with patch.object(db, "_postgres_dependencies", return_value=(fake_psycopg, object(), object())):
                db._apply_postgres_migrations()

            self.assertTrue(any("pg_advisory_lock(" in e for e in events))
            self.assertTrue(any("pg_advisory_unlock(" in e for e in events))
            self.assertEqual(events.count("txn_enter"), 1)
            self.assertEqual(events.count("txn_exit"), 1)

    def test_campaign_progress_cache_hits_and_invalidates_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "progress-cache.sqlite")
            db.init()
            try:
                db.set_access_user(username="alice", role="writer", actor="admin")
                db.set_access_user(username="bob", role="writer", actor="admin")
                ids = ["cn1001", "cn1002", "cn1003", "cn1004"]
                db.upsert_issues(
                    [{"issue_id": iid, "gt_label": "误触发"} for iid in ids],
                    source="test", replace_gt=True, baseline_scope="scope1",
                )
                db.apply_gt_sync_snapshot(
                    scope="scope1",
                    rows=[{"issue_id": iid, "gt_label": "误触发"} for iid in ids],
                    source_name="Trail", source_view_id=1000, source_field="gt",
                    trigger="test", requested_by="tester", requested_by_source="test",
                    requested_by_verified=True, expected_issue_ids=ids,
                )
                ws = db.create_review_workset(baseline_scope="scope1", issue_ids=ids, created_by="alice")
                cid = db.create_campaign(
                    spec={
                        "purpose": "labeling",
                        "workset_id": ws["id"],
                        "overlap_ratio": 0,
                        "members": [{"issue_id": iid, "assignees": ["alice", "bob"][idx % 2 : idx % 2 + 1]} for idx, iid in enumerate(ids)],
                    },
                    actor="alice",
                )["campaign"]["id"]

                first = db.list_campaigns(lifecycle="active", page=1, page_size=20)
                self.assertEqual(len(db._campaign_progress_cache), 1)
                second = db.list_campaigns(lifecycle="active", page=1, page_size=20)
                self.assertEqual(first["items"][0]["progress"], second["items"][0]["progress"])

                # Batched reallocation writes must advance revision and invalidate cached progress.
                current = db.get_campaign_allocation(cid)
                preview = db.preview_campaign_allocation(
                    campaign_id=cid,
                    assignees=[{"name": "alice", "review_percent": 75}, {"name": "bob", "review_percent": 25}],
                    reviewers_per_issue=1,
                    overlap_ratio=0,
                    expected_revision=current["expected_revision"],
                )
                updated = db.update_campaign_allocation(
                    campaign_id=cid,
                    assignees=[{"name": "alice", "review_percent": 75}, {"name": "bob", "review_percent": 25}],
                    reviewers_per_issue=1,
                    overlap_ratio=0,
                    expected_revision=current["expected_revision"],
                    idempotency_key="phase1-batch-1",
                    actor="alice",
                    actor_source="test",
                    actor_verified=True,
                    preview_token=preview["preview_token"],
                )
                self.assertTrue(updated["changed"])
                third = db.list_campaigns(lifecycle="active", page=1, page_size=20)
                self.assertEqual(third["items"][0]["workload"][0]["assigned_slots"], 3)

                # Closing a campaign must immediately reflect closed lifecycle in progress even
                # when dashboard_change_revision does not bump (as on PostgreSQL issue_work_splits).
                with patch.object(db, "_campaign_progress_watermark", return_value=(1, 0, "", 0, 0, 4, 1, 0, 0, 0, 0, 0, 0, 0, "")):
                    before_close = db.get_campaign(cid)
                    self.assertEqual(before_close["progress"]["lifecycle"], "active")
                    closed = db.close_campaign(
                        campaign_id=cid,
                        expected_revision=int(before_close["campaign"]["config_revision"]),
                        idempotency_key="phase1-close-1",
                        actor="alice",
                        actor_source="kylin_ticket",
                        actor_verified=True,
                    )
                    self.assertEqual(closed["campaign"]["campaign"]["lifecycle"], "closed")
                    self.assertEqual(closed["campaign"]["progress"]["lifecycle"], "closed")
            finally:
                db.close()

    def test_init_serializes_postgres_bootstrap_with_advisory_xact_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "init-lock.sqlite")
            db.backend = "postgresql"
            executed: list[tuple[str, tuple[object, ...]]] = []

            class _FakeConn:
                def execute(self, sql, params=()):
                    executed.append((sql, tuple(params)))
                    return SimpleNamespace(fetchall=lambda: [], fetchone=lambda: None)

            from contextlib import contextmanager

            @contextmanager
            def _fake_connect():
                yield _FakeConn()

            with (
                patch.object(db, "_apply_postgres_migrations"),
                patch.object(db, "connect", side_effect=_fake_connect),
                patch("ra_triage_dashboard.app.db_parts.core.initialize_schema"),
                patch("ra_triage_dashboard.app.db_parts.core.initialize_change_tracking"),
                patch("ra_triage_dashboard.app.db_parts.core.initialize_campaign_compat"),
                patch("ra_triage_dashboard.app.db_parts.core.initialize_columns"),
                patch("ra_triage_dashboard.app.db_parts.core.initialize_recovery"),
                patch("ra_triage_dashboard.app.db_parts.core.initialize_human_labels"),
            ):
                db.init()
            self.assertTrue(
                any(
                    "pg_advisory_xact_lock" in sql
                    and params == ("dashboard-schema-migrations-v1",)
                    for sql, params in executed
                )
            )
            db.close()


class Phase1SsoAndCachesTest(unittest.TestCase):
    def test_kylin_sso_single_flight_deduplicates_concurrent_misses(self) -> None:
        validator = KylinSSOValidator()
        calls = {"count": 0}
        entered = threading.Event()
        release = threading.Event()

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _size):
                return json.dumps({"errno": 0, "data": {"username": "alice"}}).encode("utf-8")

        def _slow_urlopen(_req, timeout=0):
            calls["count"] += 1
            entered.set()
            release.wait(timeout=3.0)
            return _FakeResp()

        settings = SimpleNamespace(
            kylin_sso_enabled=True,
            kylin_sso_app_id="2103794",
            kylin_sso_check_url="https://mis.diditaxi.com.cn/check",
            kylin_sso_timeout_seconds=1.0,
            kylin_sso_cache_seconds=60,
        )
        results: list[bool] = []

        def _worker():
            results.append(validator.validate("ticket-xyz", "alice", settings))

        with patch("ra_triage_dashboard.app.auth.urlrequest.urlopen", side_effect=_slow_urlopen):
            t1 = threading.Thread(target=_worker)
            t2 = threading.Thread(target=_worker)
            t1.start()
            self.assertTrue(entered.wait(timeout=2.0))
            t2.start()
            time.sleep(0.05)
            release.set()
            t1.join(timeout=3.0)
            t2.join(timeout=3.0)

        self.assertEqual(calls["count"], 1)
        self.assertEqual(results, [True, True])

    def test_disable_ra_version_cache_enforces_lru_bound(self) -> None:
        with external_links._disable_ra_version_cache_lock:
            external_links._disable_ra_version_cache.clear()
        with patch.object(external_links, "_DISABLE_RA_VERSION_CACHE_MAX", 3), patch.object(
            external_links, "urlopen", side_effect=OSError("offline")
        ):
            for tid in ("1001", "1002", "1003", "1004"):
                external_links.resolve_disable_ra_simulation_version(tid, cache_seconds=60)
            with external_links._disable_ra_version_cache_lock:
                self.assertEqual(len(external_links._disable_ra_version_cache), 3)
                self.assertNotIn("1001", external_links._disable_ra_version_cache)
                external_links._disable_ra_version_cache.clear()

    def test_api_status_caches_fs_probes_and_supports_force_refresh(self) -> None:
        core_router._status_fs_cache.clear()
        probe_calls = {"count": 0}

        def _fake_probes():
            probe_calls["count"] += 1
            return {
                "backup_state": {"ok": True},
                "volume_state": {"ok": True},
                "indexed_issues": 42,
                "filesystem": {"ra_auto_triage_root_available": True},
                "media_ready": {},
            }

        with (
            patch.object(core_router, "_collect_status_fs_probes", side_effect=_fake_probes),
            patch.object(core_router.database, "runtime_status", return_value={"ok": True, "backend": "sqlite"}),
            patch.object(core_router.database, "legacy_read_policies", return_value=[]),
            patch.object(core_router.database, "review_notification_status", return_value={"pending": 0}),
            patch.object(core_router.database, "comment_notification_status", return_value={"pending": 0}),
            patch.object(core_router.database, "intent_comment_notification_status", return_value={"pending": 0}),
            patch.object(core_router, "gt_sync_status", return_value={"status": "ready"}),
            patch.object(core_router, "overall_status", return_value={"status": "healthy", "problems": []}),
        ):
            asyncio.run(core_router.status(Response()))
            asyncio.run(core_router.status(Response()))
            self.assertEqual(probe_calls["count"], 1)
            asyncio.run(core_router.status(Response(), refresh=True))
            self.assertEqual(probe_calls["count"], 2)
        core_router._status_fs_cache.clear()


if __name__ == "__main__":
    unittest.main()
