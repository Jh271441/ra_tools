"""Persistent discovery tests use a fake upstream and temporary local storage."""
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

from ra_triage_dashboard.app.trail_import_discovery import TrailImportDiscovery


class TrailImportDiscoveryTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = TrailImportDiscovery(self.tmp.name, "source")
        self.members = [{"issue_id": f"cn{i:08}", "baseline_scope": "scope"} for i in range(101)]
        self.remote = Mock(side_effect=lambda ids: {i: {"should_exclude": True} for i in ids})

    def read(self, *, refresh=False, cache=None, members=None):
        return (cache or self.cache).read_or_start(scopes=["scope"], members=self.members if members is None else members,
                                                   read_remote=self.remote, refresh=refresh)

    def finish(self, **kwargs):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.read(**kwargs)
            if state["status"] != "running":
                return state
            time.sleep(.01)
        self.fail("background scan did not finish")

    def test_background_single_flight_and_durable_reopen(self):
        entered, release = threading.Event(), threading.Event()
        def slow(ids):
            entered.set()
            release.wait(3)
            return {i: {"should_exclude": True} for i in ids}
        self.remote.side_effect = slow
        self.assertEqual(self.read()["status"], "running")
        self.assertTrue(entered.wait(1))
        restarted = TrailImportDiscovery(self.tmp.name, "source")
        # Multiple requests/actors/worker instances and refresh clicks coalesce.
        for _ in range(5):
            self.assertEqual(self.read(cache=restarted, refresh=True)["status"], "running")
        self.assertEqual(self.remote.call_count, 1)
        release.set()
        state = self.finish(cache=restarted)
        self.assertEqual(state["status"], "ready")
        self.assertEqual(len(state["snapshot"]["items"]), 101)
        self.assertEqual(self.remote.call_count, 2)
        self.assertEqual(self.read(cache=TrailImportDiscovery(self.tmp.name, "source")), state)
        self.assertEqual(self.remote.call_count, 2)
        path = self.cache._path(["scope"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())["snapshot"]["total"], 101)

    def test_explicit_refresh_and_empty_snapshot_are_persistent(self):
        self.remote.side_effect = lambda ids: {i: {} for i in ids}
        self.read()
        first = self.finish()
        self.assertEqual(first["snapshot"]["items"], [])
        for _ in range(3): self.read()
        self.assertEqual(self.remote.call_count, 2)
        self.remote.side_effect = lambda ids: {i: {"should_exclude": True} for i in ids}
        self.read(refresh=True)
        second = self.finish()
        self.assertEqual(len(second["snapshot"]["items"]), 101)
        self.assertEqual(self.remote.call_count, 4)
        self.assertNotEqual(first["snapshot"]["checked_at"], second["snapshot"]["checked_at"])

    def test_failed_refresh_preserves_complete_snapshot_and_never_auto_retries(self):
        self.read()
        before = self.finish()["snapshot"]
        self.remote.side_effect = RuntimeError("secret upstream detail")
        self.read(refresh=True)
        failed = self.finish()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["snapshot"], before)
        self.assertNotIn("secret", failed["error"])
        calls = self.remote.call_count
        self.read()
        self.assertEqual(self.remote.call_count, calls)

    def test_partial_failure_and_interruption_never_look_complete(self):
        self.remote.side_effect = [{i["issue_id"]: {"should_exclude": True} for i in self.members[:100]}, {}]
        self.read()
        failed = self.finish()
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["snapshot"])
        self.assertEqual(failed["scanned"], 100)
        self.assertEqual(len(failed["partial"]), 100)
        # Simulate a saved in-flight record whose process no longer holds a lock.
        failed["status"] = "running"
        self.cache._save(self.cache._path(["scope"]), failed)
        self.assertEqual(self.read()["status"], "interrupted")
        self.assertEqual(self.remote.call_count, 2)

    def test_membership_change_is_visible_without_automatic_rescan(self):
        self.read()
        state = self.finish()
        self.assertFalse(self.cache.membership_changed(state, self.members))
        changed = self.members[:-1]
        self.assertTrue(self.cache.membership_changed(self.read(members=changed), changed))
        self.assertEqual(self.remote.call_count, 2)
        self.assertNotEqual(self.cache._path(["scope"]), self.cache._path(["other"]))
        self.assertNotEqual(self.cache._path(["scope"]), TrailImportDiscovery(self.tmp.name, "other-source")._path(["scope"]))
        self.assertEqual(self.cache._path(["a", "b"]), self.cache._path(["b", "a", "a"]))

    def test_zero_members_and_corruption_do_not_loop_remote_queries(self):
        self.read(members=[])
        state = self.finish(members=[])
        self.assertEqual(state["snapshot"]["total"], 0)
        self.read(members=[])
        self.remote.assert_not_called()
        self.cache._save(self.cache._path(["scope"]), {"invalid": True})
        self.assertEqual(self.read()["status"], "failed")
        self.remote.assert_not_called()
