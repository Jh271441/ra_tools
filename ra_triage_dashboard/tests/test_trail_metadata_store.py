from __future__ import annotations

import asyncio
import json
import multiprocessing
import stat
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from ra_triage_dashboard.app.trail_metadata_store import TrailMetadataStore


def _metadata():
    return {
        "issue_id": "cn31842459", "trip_id": "car_trip", "ra_id": "recording",
        "ra_start_timestamp": 1778504337830, "ra_end_timestamp": 1778504346478,
        "ra_event": [{"event": "start", "timestamp": 1778504337830},
                     {"event": "exit", "timestamp": 1778504346478}],
        "dashboard_should_exclude": True,
    }


def _process_read(root, start, output, calls):
    start.wait(5)

    def read(**_kwargs):
        with calls.get_lock():
            calls.value += 1
        time.sleep(0.05)
        return _metadata()

    output.put(TrailMetadataStore(Path(root)).get_or_fetch(
        ra_root=Path("/tmp/ra-source"), view_id=2410, issue_id="cn31842459", reader=read,
    )["metadata"]["trip_id"])


class TrailMetadataStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "snapshots"
        self.reader = Mock(return_value=_metadata())

    def read(self, **options):
        return TrailMetadataStore(self.root).get_or_fetch(**{
            "ra_root": Path("/tmp/ra-source"), "issue_id": "cn31842459",
            "view_id": 2410, "reader": self.reader, **options,
        })

    def test_complete_snapshot_survives_restart_and_a_year_without_trail(self):
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1000):
            first = self.read()
        first["metadata"]["ra_event"][0]["event"] = "mutated"
        self.reader.side_effect = AssertionError("Trail must not be queried")
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1000 + 365 * 86400):
            restored = self.read()
        self.assertEqual(self.reader.call_count, 1)
        self.assertEqual(restored["metadata_source"], "snapshot")
        self.assertEqual(restored["metadata"]["ra_event"][0]["event"], "start")
        self.assertNotIn("dashboard_should_exclude", restored["metadata"])
        self.assertEqual(restored["status"], "ready")
        self.reader.assert_called_once_with(ra_root=Path("/tmp/ra-source"), issue_id="cn31842459", view_id=2410, cache_seconds=0)

    def test_explicit_refresh_replaces_snapshot_and_failure_retains_last_success(self):
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1000):
            self.read()
        changed = {**_metadata(), "ra_id": "new-recording"}
        self.reader.return_value = changed
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1001):
            self.assertEqual(self.read(refresh=True)["metadata"]["ra_id"], "new-recording")
        self.reader.side_effect = RuntimeError("Trail unavailable")
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1002):
            failed = self.read(refresh=True)
        self.assertEqual(failed["metadata"]["ra_id"], "new-recording")
        self.assertEqual(failed["refresh_status"], "unavailable")
        self.assertEqual(failed["metadata_fetched_at"], "1970-01-01T00:16:41+00:00")
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=999999):
            self.assertEqual(self.read()["metadata"]["ra_id"], "new-recording")
        self.assertEqual(self.reader.call_count, 3)

    def test_partial_and_empty_snapshots_retry_after_their_backoff(self):
        self.reader.return_value = {}
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1000):
            self.assertEqual(self.read()["status"], "unavailable")
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1029):
            self.read()
        self.assertEqual(self.reader.call_count, 1)
        self.reader.return_value = {"trip_id": "car_trip"}
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1030):
            self.assertEqual(self.read()["metadata"]["trip_id"], "car_trip")
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1329):
            self.read()
        self.assertEqual(self.reader.call_count, 2)
        self.reader.return_value = _metadata()
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1330):
            self.read()
        self.assertEqual(self.reader.call_count, 3)

    def test_store_allowlist_private_files_and_source_view_isolation(self):
        self.reader.return_value = {**_metadata(), "unrelated_secret_field": "must-not-persist"}
        self.read()
        saved = next(self.root.glob("*.json"))
        self.assertNotIn("must-not-persist", saved.read_text())
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.read(view_id=2411)
        self.read(ra_root=Path("/tmp/other-source"))
        self.assertEqual(self.reader.call_count, 3)
        self.assertEqual(len(list(self.root.glob("*.json"))), 3)

    def test_corrupt_wrong_identity_oversize_and_symlink_snapshots_are_not_served(self):
        self.read()
        saved = next(self.root.glob("*.json"))
        original = saved.read_text()
        for invalid in ("{broken", "x" * (129 * 1024), json.dumps({**json.loads(original), "identity": "another"})):
            saved.write_text(invalid)
            self.assertEqual(self.read()["metadata"]["ra_id"], "recording")
        target = self.root / "outside.json"
        target.write_text(original)
        saved.unlink()
        saved.symlink_to(target)
        self.read()
        self.assertFalse(saved.is_symlink())
        self.assertEqual(target.read_text(), original)
        self.assertEqual(self.reader.call_count, 5)

    def test_incomplete_refresh_cannot_discard_unchanged_complete_events(self):
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1000):
            self.read()
        self.reader.return_value = {"issue_id": "another-case", "trip_id": "wrong"}
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1001):
            result = self.read(refresh=True)
        self.assertEqual(result["metadata"]["trip_id"], "car_trip")
        self.assertEqual(result["refresh_status"], "unavailable")
        self.reader.return_value = {"trip_id": "new-but-partial"}
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1002):
            result = self.read(refresh=True)
        self.assertEqual(result["metadata"]["trip_id"], "car_trip")
        self.assertEqual(result["refresh_status"], "unavailable")

    def test_atomic_write_failure_preserves_previous_receipt(self):
        self.read()
        saved = next(self.root.glob("*.json"))
        original = saved.read_bytes()
        with patch("ra_triage_dashboard.app.trail_metadata_store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.read(refresh=True)
        self.assertEqual(saved.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".trail-*")), [])

    def test_resolved_simulation_version_is_persisted_and_only_refreshed_explicitly(self):
        self.reader.return_value = {**_metadata(), "te_task_id_disabe_ra": "4515392300000101"}
        resolver = Mock(return_value=1)
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=1000):
            self.assertEqual(self.read(resolver=resolver)["metadata"]["te_task_version_disabe_ra"], 1)
        with patch("ra_triage_dashboard.app.trail_metadata_store.time.time", return_value=2000):
            self.assertEqual(self.read(resolver=resolver)["metadata"]["te_task_version_disabe_ra"], 1)
        self.assertEqual(resolver.call_count, 1)

    def test_separate_processes_share_one_trail_lookup(self):
        ctx = multiprocessing.get_context("spawn")
        start, output, calls = ctx.Event(), ctx.Queue(), ctx.Value("i", 0)
        processes = [ctx.Process(target=_process_read, args=(str(self.root), start, output, calls)) for _ in range(4)]
        try:
            for process in processes:
                process.start()
            start.set()
            self.assertEqual([output.get(timeout=10) for _ in processes], ["car_trip"] * 4)
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(calls.value, 1)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            output.close()


class TrailMetadataApiTest(unittest.TestCase):
    @staticmethod
    def get(app, url):
        """Exercise FastAPI HTTP routing using the existing dependency-free pattern."""
        target, messages = urlsplit(url), []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        asyncio.run(app({
            "type": "http", "asgi": {"version": "3.0"},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": target.path, "raw_path": target.path.encode(),
            "root_path": "", "query_string": target.query.encode(),
            "headers": [(b"host", b"test")],
            "server": ("test", 80), "client": ("127.0.0.1", 12345),
        }, receive, send))
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return SimpleNamespace(
            status_code=next(m["status"] for m in messages if m["type"] == "http.response.start"),
            json=lambda: json.loads(body),
        )

    def test_http_reentry_and_restart_reuse_disk_explicit_refresh_updates_it(self):
        from fastapi import FastAPI
        from ra_triage_dashboard.app.routers import cases

        app = FastAPI()
        app.include_router(cases.router)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            cases, "settings", SimpleNamespace(
                data_dir=Path(directory), trail_detail_metadata_enabled=True,
                ra_auto_triage_root=Path("/tmp/ra-source"), trail_view_id=2410,
            )
        ), patch.object(cases.database, "get_issue", return_value={"issue_id": "cn31842459"}), patch.object(
            cases, "read_trail_issue_metadata", return_value=_metadata()
        ) as read:
            route = "/api/cases/cn31842459/trail-metadata"
            first = self.get(app, route)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["metadata_source"], "trail")
            # A new app/store instance and HTTP request use the same disk snapshot.
            restarted = FastAPI()
            restarted.include_router(cases.router)
            second = self.get(restarted, route)
            self.assertEqual(second.json()["metadata_source"], "snapshot")
            self.assertEqual(read.call_count, 1)
            read.return_value = {**_metadata(), "ra_id": "updated"}
            forced = self.get(restarted, route + "?refresh=true")
            self.assertEqual(read.call_count, 2)
            self.assertEqual(forced.json()["external_links"]["ra_task_id"], "updated")
            self.assertEqual(self.get(restarted, route).json()["external_links"]["ra_task_id"], "updated")
            self.assertEqual(read.call_count, 2)

    def test_disabled_lookup_and_unknown_issue_never_create_snapshot(self):
        from fastapi import FastAPI
        from ra_triage_dashboard.app.routers import cases

        app = FastAPI()
        app.include_router(cases.router)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            cases, "settings", SimpleNamespace(data_dir=Path(directory), trail_detail_metadata_enabled=False)
        ), patch.object(cases.database, "get_issue", return_value={"issue_id": "cn1"}) as issue, patch.object(
            cases, "read_trail_issue_metadata"
        ) as read:
            self.assertEqual(self.get(app, "/api/cases/cn1/trail-metadata").json()["status"], "disabled")
            issue.return_value = None
            self.assertEqual(self.get(app, "/api/cases/cn1/trail-metadata").status_code, 404)
            read.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])
