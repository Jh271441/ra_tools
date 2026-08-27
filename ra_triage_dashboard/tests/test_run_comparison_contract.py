from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROUTER = (ROOT / "app" / "routers" / "core.py").read_text(encoding="utf-8")
RUNS_ROUTER = (ROOT / "app" / "routers" / "runs.py").read_text(encoding="utf-8")


class RunComparisonRouteContractTest(unittest.TestCase):
    def test_page_and_api_both_require_server_verified_admin(self) -> None:
        page_start = CORE_ROUTER.index('@router.get("/run-comparison"')
        page_block = CORE_ROUTER[page_start : page_start + 500]
        self.assertIn("_admin_identity, request", page_block)

        api_start = RUNS_ROUTER.index('@router.get("/api/model-run-comparison"')
        api_block = RUNS_ROUTER[api_start : api_start + 1400]
        self.assertIn("_admin_identity, request", api_block)
        self.assertIn("database.compare_model_runs", api_block)
        self.assertIn("resolve_request_baseline_scopes", api_block)


if __name__ == "__main__":
    unittest.main()
