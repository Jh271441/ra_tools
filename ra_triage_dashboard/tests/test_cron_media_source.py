from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from ra_triage_dashboard.app.cron_media_source import media_snapshot


class CronDailyMediaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.report = self.root / "reports/manual_sidecar_20261019"
        self.work = self.report / "daily/2026-10-18"
        self.replacement = self.report / "full-replacement-20261020"
        self.write(self.report / "heartbeat.json", {"checked_at": time.time(), "recovery_policy": {"orion_retry_count": 1, "browser_cache": "private-path"}})
        self.write(self.report / "daily-enabled.json", {"enabled": True})
        self.write(self.work / "status.json", {"state": "complete", "selected": 1, "bev": {"completed": 1, "failed": 0, "total": 1}})
        self.write(self.work / "media-source.json", [{"issue_id": "cn123"}])
        self.write(self.work / "superseded-by-full-run.json", {"run_id": "full-run"})

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def canonical(self):
        self.write(self.replacement / "complete.json", {"new": [{"day": "2026-10-18", "name": "full", "count": 2, "run_id": "full-run", "assignment": {"run_id": "full-run", "assigned": {"a": 1, "b": 1}, "overlap": 0}}]})
        self.write(self.replacement / "full.json", {"results": [{"issue_id": "cn123"}, {"issue_id": "cn456"}]})
        self.write(self.replacement / "full-receipt.json", {"run_id": "full-run", "count": 2})

    def publish(self, folder, issue):
        self.write(folder / "media-publication" / (issue + ".json"), {"issue_id": issue, "state": "verified", "bev_probe": {"width": 1}, "camera_probe": {"width": 1}, "verified_at": time.time()})

    def test_superseded_cohort_cannot_become_full_run_count(self):
        self.assertEqual(media_snapshot(self.root)["runs"], [])
        self.canonical()
        self.publish(self.work, "cn123")
        row = media_snapshot(self.root)["runs"][0]
        self.assertEqual((row["selected"], row["imported"], row["assigned"]), (2, 2, 2))
        self.assertEqual(row["verified"], 1)
        self.assertEqual(row["state"], "collecting")
        supplement = self.report / "daily/2026-10-18-supplement-20261020"
        self.publish(supplement, "cn456")
        self.publish(self.report, "cn123")  # Same publication in two queues counts once.
        row = media_snapshot(self.root)["runs"][0]
        self.assertEqual((row["state"], row["verified"], row["camera_verified"]), ("complete", 2, 2))
        self.assertEqual(row["original_orion_total"], 1)

    def test_wrong_identity_duplicate_members_or_escape_do_not_count(self):
        self.canonical()
        self.publish(self.work, "cn123")
        self.write(self.work / "media-publication/cn456.json", {"issue_id": "cn999", "state": "verified", "bev_probe": {"width": 1}, "camera_probe": {"width": 1}})
        self.assertEqual(media_snapshot(self.root)["runs"][0]["verified"], 1)
        self.write(self.replacement / "full.json", {"results": [{"issue_id": "cn123"}, {"issue_id": "cn123"}]})
        with self.assertRaises(ValueError):
            media_snapshot(self.root)
        self.canonical()
        self.write(self.replacement / "complete.json", {"new": [{"day": "2026-10-18", "name": "../../escape", "count": 2}]})
        with self.assertRaises(ValueError):
            media_snapshot(self.root)

    def test_empty_day_and_controller_freshness_are_independent(self):
        (self.work / "superseded-by-full-run.json").unlink()
        self.write(self.work / "status.json", {"state": "empty"})
        self.write(self.work / "media-source.json", [])
        result = media_snapshot(self.root)
        self.assertEqual((result["runs"][0]["state"], result["runs"][0]["selected"]), ("empty", 0))
        self.assertFalse(result["stale"])
        self.assertNotIn("private-path", json.dumps(result))
        self.write(self.report / "heartbeat.json", {"checked_at": time.time() - 301})
        self.assertTrue(media_snapshot(self.root)["stale"])
