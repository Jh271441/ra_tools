from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app.simulation_links import read_verified_disable_ra_simulation
from ra_triage_dashboard.app.routers import cases


class SimulationLinksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.path = self.data_dir / "disable_ra_simulations" / "links.json"
        self.path.parent.mkdir()
        self.record = {
            "task_id": "5123456700000001",
            "task_version": 0,
            "source_task_id": "4523469300000031",
            "status": "completed",
            "configuration_matches_source": True,
            "output_bag_count": 2,
            "verified_at": "2026-11-01T03:00:00+08:00",
        }

    def write(self, record=None):
        self.path.write_text(json.dumps({
            "schema_version": 1,
            "links": {"cn35667619": self.record if record is None else record},
        }))

    def read(self, source="4523469300000031"):
        return read_verified_disable_ra_simulation(
            self.data_dir, "cn35667619", source_task_id=source
        )

    def test_verified_link_survives_unavailable_trail_but_not_new_source(self):
        self.write()
        self.assertEqual(self.read()["task_id"], self.record["task_id"])
        self.assertEqual(self.read(None)["task_id"], self.record["task_id"])
        self.assertIsNone(self.read("4523469300000043"))

    def test_pending_failed_or_unverified_output_cannot_replace_existing_link(self):
        for changes in [
            {"status": "running"}, {"status": "failed"},
            {"configuration_matches_source": False},
            {"output_bag_count": 0}, {"output_bag_count": True},
            {"task_id": "https://example.com"}, {"task_version": True},
            {"task_version": -1}, {"source_task_id": ""},
            {"verified_at": "2026-11-01T03:00:00"},
        ]:
            with self.subTest(changes=changes):
                self.write({**self.record, **changes})
                self.assertIsNone(self.read())

    def test_missing_malformed_oversized_or_unknown_manifest_falls_back(self):
        self.assertIsNone(self.read())
        for raw in [b"{", b"[]", b'\xff', b" " * (1024 * 1024 + 1),
                    b'{"schema_version":true,"links":{}}',
                    b'{"schema_version":2,"links":{}}']:
            with self.subTest(size=len(raw)):
                self.path.write_bytes(raw)
                self.assertIsNone(self.read())


class SimulationLinkRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_verified_result_overrides_only_link_and_skips_old_lookup(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            path = data_dir / "disable_ra_simulations" / "links.json"
            path.parent.mkdir()
            record = {
                "task_id": "5123456700000001", "task_version": 0,
                "source_task_id": "4523469300000031", "status": "completed",
                "configuration_matches_source": True, "output_bag_count": 1,
                "verified_at": "2026-11-01T03:00:00+08:00",
            }
            path.write_text(json.dumps({"schema_version": 1, "links": {"cn35667619": record}}))
            original = {"te_task_id_disabe_ra": "4523469300000031", "ra_id": "ra-original"}
            before = copy.deepcopy(original)
            with patch.object(cases.database, "get_issue", return_value={"issue_id": "cn35667619", "extra": {}}), patch.object(cases, "settings", SimpleNamespace(
                data_dir=data_dir, trail_detail_metadata_enabled=True,
                ra_auto_triage_root="/tmp/unused", trail_view_id=2410,
                trail_detail_metadata_cache_seconds=0,
            )), patch.object(cases, "read_trail_issue_metadata", return_value=original), patch.object(cases, "resolve_disable_ra_simulation_version") as resolve:
                payload = await cases.get_case_trail_metadata("cn35667619")
            links = payload["external_links"]
            self.assertEqual(links["disable_ra_simulation_task_id"], record["task_id"])
            self.assertEqual(links["disable_ra_simulation_original_task_id"], record["source_task_id"])
            self.assertEqual(links["disable_ra_simulation_source"], "manual")
            self.assertIn("task_id=5123456700000001&task_version=0", links["disable_ra_simulation_url"])
            self.assertEqual(links["ra_task_id"], "ra-original")
            self.assertEqual(original, before)
            resolve.assert_not_called()
