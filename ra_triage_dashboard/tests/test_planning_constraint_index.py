from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response

from ra_triage_dashboard.app import planning_constraints as service
from ra_triage_dashboard.app.planning_constraint_index import (
    INDEX_NAME, InvalidPlanningTime, query_offset, read_saved_window,
)
from ra_triage_dashboard.app.routers import cases as routes
from ra_triage_dashboard.scripts.index_planning_constraints import build_index

ANCHOR = 1700000000000
ISSUE = "cn10000001"
TRIP = "trip-unit-1"


def saved_result(root, *, failed=False):
    """Synthetic saved facts: Object0, no-constraint, unresolved and a real hole."""
    member = {"issue_id": ISSUE, "version": "1016", "datasets": ["release-20261016-odd2"]}
    membership = {"issues": [member], "extractor_version": service.VERSION,
                  "source": service.SOURCE, "membership_sha256": "a" * 64}
    (root / "membership.json").write_text(json.dumps(membership))
    frames = [
        {"timestamp_ms": ANCHOR - 100, "planning_timestamp_ms": ANCHOR - 175,
         "status": "ready", "constraint_id": "raw-<id>", "object_id": 0,
         "raw": "Non gap align. Dominant constraint: raw-<id>, Object id: 0. Earliest search brake time ix: -1"},
        {"timestamp_ms": ANCHOR + 100, "planning_timestamp_ms": ANCHOR + 25,
         "status": "no_constraint", "constraint_id": None, "object_id": -1,
         "raw": "Non gap align. No dominant constraint. Earliest search brake time ix: -1"},
        {"timestamp_ms": ANCHOR + 200, "planning_timestamp_ms": ANCHOR + 125,
         "status": "unresolved", "constraint_id": None, "raw": ""},
    ]
    result = {**member, "anchor_ms": ANCHOR, "trip_id": TRIP, "duration_ms": 40000,
              "event_time_sec": 20, "start_offset_ms": -20000, "end_offset_ms": 20000,
              "capture": {"trip_id": TRIP, "timestamp_ms": ANCHOR}, "frames": frames,
              "frame_count": 3, "frame_statuses": dict(Counter(f["status"] for f in frames)),
              "t0": frames[0], "gaps_ms": [[-20000, -100], [50, 100], [350, 20000]],
              "extraction_status": "failed" if failed else "partial_source",
              "errors": [{"bucket": -3, "error": "worker_exit_1"}] if failed else []}
    dest = root / "cases" / ISSUE / "result.json"
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps(result))
    return result, dest


class PlanningIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.result, self.result_path = saved_result(self.source)
        self.data = self.root / "data"
        self.index = self.data / "planning_constraints" / INDEX_NAME
        self.report = build_index([self.source], self.index)

    def test_issue_time_lookup_preserves_exact_raw_and_causal_statuses(self):
        with patch.object(service.threading, "Thread") as worker:
            value = service.read_window(self.data, ISSUE, TRIP, ANCHOR, 0)
            self.assertEqual(value["read_source"], "historical_index")
            self.assertEqual(value["matched_frame"], self.result["frames"][0])
            self.assertEqual(value["matched_frame"]["object_id"], 0)
            self.assertEqual(value["source_result_sha256"], hashlib.sha256(self.result_path.read_bytes()).hexdigest())
            self.assertIsNone(read_saved_window(self.data, ISSUE, timestamp_ms=ANCHOR + 99)["matched_frame"])
            self.assertEqual(read_saved_window(self.data, ISSUE, timestamp_ms=ANCHOR + 100)["matched_frame"]["status"], "no_constraint")
            self.assertEqual(read_saved_window(self.data, ISSUE, timestamp_ms=ANCHOR + 200)["matched_frame"]["status"], "unresolved")
            self.assertIsNone(read_saved_window(self.data, ISSUE, timestamp_ms=ANCHOR + 351)["matched_frame"])
            worker.assert_not_called()
        self.assertEqual(self.report["issues"], 1)
        self.assertEqual(self.report["frames"], 3)

    def test_failed_source_holes_do_not_trigger_a_bag_retry(self):
        self.result["errors"] = [{"bucket": -3, "error": "worker_exit_1"}]
        self.result["extraction_status"] = "failed"
        self.result_path.write_text(json.dumps(self.result))
        build_index([self.source], self.index)
        with patch.object(service.threading, "Thread") as worker:
            empty = service.read_window(self.data, ISSUE, TRIP, ANCHOR, -19900)
            self.assertEqual(empty["status"], "ready")
            self.assertEqual(empty["source_status"], "failed")
            self.assertEqual(empty["source_gaps_ms"], self.result["gaps_ms"])
            self.assertEqual(empty["frames"], [])
            self.assertIsNone(empty["matched_frame"])
            worker.assert_not_called()

    def test_identity_mismatch_and_unrecorded_window_are_misses(self):
        self.assertIsNone(read_saved_window(self.data, "cn9999", 0))
        self.assertIsNone(read_saved_window(self.data, ISSUE, 0, trip_id="different"))
        self.assertIsNone(read_saved_window(self.data, ISSUE, 0, anchor_ms=ANCHOR + 1))
        self.assertIsNone(read_saved_window(self.data, ISSUE, 30000))
        self.assertEqual(read_saved_window(self.data, ISSUE, -1)["bucket"], -1)
        for offset, stamp in [(60001, None), (None, ANCHOR - 60001), (0, ANCHOR), (None, 0)]:
            with self.assertRaises(InvalidPlanningTime):
                read_saved_window(self.data, ISSUE, offset, stamp)
        self.assertEqual(query_offset(ANCHOR, None, ANCHOR - 123), -123)

    def test_all_player_buckets_reuse_saved_coverage_including_clip_start(self):
        with patch.object(service.threading, "Thread") as worker:
            for bucket in [-3, -2, -1, 0, 1, 2]:
                response = service.read_window(self.data, ISSUE, TRIP, ANCHOR, bucket * 8000)
                self.assertEqual(response["read_source"], "historical_index")
                self.assertEqual(response["status"], "ready")
                self.assertEqual(response["bucket"], bucket)
            worker.assert_not_called()
        self.assertIsNone(read_saved_window(self.data, ISSUE, timestamp_ms=ANCHOR + 20000)["matched_frame"])

    def test_bad_import_keeps_previous_snapshot_and_missing_source_fails(self):
        before = self.index.read_bytes()
        for change in [
            lambda r: r.update(trip_id="wrong"),
            lambda r: r.update(t0=None),
            lambda r: r["frames"].append(r["frames"][0]),
            lambda r: r.update(gaps_ms=[]),
        ]:
            modified = json.loads(json.dumps(self.result))
            change(modified)
            self.result_path.write_text(json.dumps(modified))
            with self.assertRaises(ValueError):
                build_index([self.source], self.index)
            self.assertEqual(self.index.read_bytes(), before)
        self.result_path.unlink()
        with self.assertRaises(ValueError):
            build_index([self.source], self.index)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(list(self.index.parent.glob(".planning-index-*")), [])

    def test_membership_version_checksum_and_conflicts_fail_closed(self):
        with self.assertRaises(ValueError):
            build_index([self.source], self.index, "0" * 64)
        manifest_path = self.source / "membership.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["extractor_version"] = "older"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            build_index([self.source], self.index)
        manifest["extractor_version"] = service.VERSION
        manifest_path.write_text(json.dumps(manifest))
        other = self.root / "other"
        other.mkdir()
        result, path = saved_result(other)
        result["frames"][0]["raw"] += " different"
        result["t0"] = result["frames"][0]
        path.write_text(json.dumps(result))
        with self.assertRaises(ValueError):
            build_index([self.source, other], self.index)

    def test_read_only_snapshot_and_damage_never_start_worker(self):
        original = self.index.stat()
        self.assertEqual(read_saved_window(self.data, ISSUE, 0)["status"], "ready")
        self.assertEqual(self.index.stat().st_mtime_ns, original.st_mtime_ns)
        self.assertEqual(list(self.index.parent.iterdir()), [self.index])
        with sqlite3.connect(self.index) as db:
            db.execute("UPDATE configuration SET extractor_version='older'")
        with patch.object(service.threading, "Thread") as worker:
            self.assertEqual(service.read_window(self.data, ISSUE, TRIP, ANCHOR, 0)["status"], "unavailable")
            worker.assert_not_called()
        self.index.write_bytes(b"not SQLite")
        self.assertEqual(read_saved_window(self.data, ISSUE, 0)["reason"], "index_unavailable")


class PlanningIndexRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_saved_registry_text_is_independent_of_media_and_model_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            result, _ = saved_result(source)
            build_index([source], root / "planning_constraints" / INDEX_NAME)
            with patch.object(routes, "settings", SimpleNamespace(data_dir=root)), patch.object(
                routes.database, "get_media_issue", return_value={"reference_media": True, "baseline_scope": ""}
            ), patch.object(routes, "media_for_issue") as media, patch.object(service, "read_window") as cold:
                response = Response()
                facts = await routes.get_planning_constraints(ISSUE, response, timestamp_ms=ANCHOR)
                self.assertEqual(facts["matched_frame"], result["t0"])
                self.assertEqual(facts["query_timestamp_ms"], ANCHOR)
                self.assertEqual(response.headers["cache-control"], "no-store")
                media.assert_not_called()
                cold.assert_not_called()
                for kwargs in [{"offset_ms": 0, "timestamp_ms": ANCHOR}, {"timestamp_ms": ANCHOR + 60001}]:
                    with self.assertRaises(HTTPException) as error:
                        await routes.get_planning_constraints(ISSUE, response, **kwargs)
                    self.assertEqual(error.exception.status_code, 400)
            with patch.object(routes.database, "get_media_issue", return_value=None):
                with self.assertRaises(HTTPException) as error:
                    await routes.get_planning_constraints(ISSUE, Response())
                self.assertEqual(error.exception.status_code, 404)

    async def test_unknown_issue_uses_existing_bounded_cold_path_with_absolute_time(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = SimpleNamespace(get_assets=lambda iid: {"capture": {"trip_id": TRIP, "timestamp_ms": ANCHOR}})
            with patch.object(routes, "settings", SimpleNamespace(data_dir=Path(temp))), patch.object(
                routes.database, "get_media_issue", return_value={"baseline_scope": "scope"}
            ), patch.object(routes, "media_for_issue", return_value=provider), patch.object(
                service, "read_window", return_value={"status": "loading", "frames": []}
            ) as cold:
                facts = await routes.get_planning_constraints(ISSUE, Response(), timestamp_ms=ANCHOR - 100)
                self.assertEqual(facts["status"], "loading")
                self.assertEqual(cold.call_args.args, (Path(temp), ISSUE, TRIP, ANCHOR, -100))


if __name__ == "__main__":
    unittest.main()
