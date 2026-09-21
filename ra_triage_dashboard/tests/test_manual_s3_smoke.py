from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_manual_s3_smoke.py"
SPEC = importlib.util.spec_from_file_location("build_manual_s3_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class ManualS3SmokeSafetyTest(unittest.TestCase):
    def test_target_gate_rejects_production_names_and_remote_hosts(self) -> None:
        for name in ("ra_triage", "production", "dashboard", "dashboard_smoke_20260921", "prod_manual_s3"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                smoke.require_safe_target(name, "")
        with self.assertRaises(RuntimeError):
            smoke.require_safe_target("manual_s3_smoke", "10.0.0.8")

    def test_target_gate_accepts_local_smoke_names(self) -> None:
        for name in ("manual_s3_smoke", "manual_s3_smoke_20260921"):
            for host in ("", "127.0.0.1", "::1", "localhost"):
                with self.subTest(name=name, host=host):
                    smoke.require_safe_target(name, host)

    def test_database_url_file_must_be_owned_and_exactly_0600(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "database-url"
            path.write_text("postgresql://localhost/test", encoding="utf-8")
            os.chmod(path, 0o640)
            with self.assertRaises(RuntimeError):
                smoke.read_url_file(path)
            os.chmod(path, 0o600)
            self.assertEqual(smoke.read_url_file(path), "postgresql://localhost/test")

    def test_gt_snapshot_facts_are_deleted_before_issue_pruning(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(
            source.index('connection.execute("DELETE FROM gt_snapshot_items")'),
            source.index('f"DELETE FROM issues WHERE issue_id NOT IN ({placeholders})"'),
        )

    def test_sampling_rank_is_stable_and_scope_specific(self) -> None:
        first = smoke.stable_rank("seed", "scope-a", "cn1")
        self.assertEqual(first, smoke.stable_rank("seed", "scope-a", "cn1"))
        self.assertNotEqual(first, smoke.stable_rank("seed", "scope-b", "cn1"))
        self.assertNotEqual(first, smoke.stable_rank("seed-2", "scope-a", "cn1"))

    def test_synthetic_stale_pin_builds_an_auditable_smoke_only_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "smoke.sqlite3")
            database.init()
            self.addCleanup(database.close)
            database.upsert_issues(
                [{"issue_id": "cn1", "gt_label": "误触发"}],
                source="test", replace_gt=True, baseline_scope="scope",
            )
            seeded = smoke.seed_synthetic_stale_label_state(database, "cn1")
            state = database.project_issue_label_states(
                "scope", ["cn1"], include_sources=False
            )["cn1"]
            self.assertTrue(seeded["synthetic"])
            self.assertEqual(seeded["state"], "stale")
            self.assertEqual(state["state"], "stale")
            self.assertEqual(len(seeded["source_revision_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
