from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_manual_s3_smoke.py"
SPEC = importlib.util.spec_from_file_location("build_manual_s3_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class ManualS3SmokeSafetyTest(unittest.TestCase):
    def test_target_gate_rejects_production_names_and_remote_hosts(self) -> None:
        for name in ("ra_triage", "production", "dashboard"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                smoke.require_safe_target(name, "")
        with self.assertRaises(RuntimeError):
            smoke.require_safe_target("manual_s3_smoke", "10.0.0.8")

    def test_target_gate_accepts_local_smoke_names(self) -> None:
        for name in ("manual_s3_smoke", "dashboard_smoke_20260921"):
            for host in ("", "127.0.0.1", "::1", "localhost"):
                with self.subTest(name=name, host=host):
                    smoke.require_safe_target(name, host)

    def test_sampling_rank_is_stable_and_scope_specific(self) -> None:
        first = smoke.stable_rank("seed", "scope-a", "cn1")
        self.assertEqual(first, smoke.stable_rank("seed", "scope-a", "cn1"))
        self.assertNotEqual(first, smoke.stable_rank("seed", "scope-b", "cn1"))
        self.assertNotEqual(first, smoke.stable_rank("seed-2", "scope-a", "cn1"))


if __name__ == "__main__":
    unittest.main()
