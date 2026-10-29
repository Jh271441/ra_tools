import json
from pathlib import Path
import tempfile
import time
import unittest

from ra_triage_dashboard.app.cron_closeup_source import closeup_status


class CloseupStatusTest(unittest.TestCase):
    def test_status_projects_counts_without_private_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029/progress.json"
            self.assertIsNone(closeup_status(root / "ra_auto_triage"))
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(state="collecting", checked_at=time.time(), pid=123, cwd="/private/source", batch="/private/log", total=4461, verified=3, states={"verified":3, "queued":4458}, versions={"1009":{"queued":1480}}, source_members={"1009":{"published:ready":1480}})))
            result = closeup_status(root / "ra_auto_triage")
            self.assertEqual(result["verified"], 3)
            self.assertFalse(result["stale"])
            self.assertNotIn("private", json.dumps(result))
            path.write_text(json.dumps(dict(state="unrecognized", checked_at=0, total=-1, verified="3", versions={}, source_members={})))
            result = closeup_status(root / "ra_auto_triage")
            self.assertTrue(result["stale"])
            self.assertIsNone(result["total"])
            self.assertIsNone(result["verified"])
