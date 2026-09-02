from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROUTER = (ROOT / "app" / "routers" / "core.py").read_text(encoding="utf-8")
INTENT_ROUTER = (ROOT / "app" / "routers" / "intent_labeling.py").read_text(
    encoding="utf-8"
)


class IntentLabelingAccessContractTest(unittest.TestCase):
    def test_page_and_all_intent_apis_require_server_verified_admin(self) -> None:
        page_start = CORE_ROUTER.index('@router.get("/intent-labeling"')
        page_block = CORE_ROUTER[page_start : page_start + 650]
        self.assertIn("intent_labeling_page(request: Request)", page_block)
        self.assertIn("_admin_identity, request", page_block)

        self.assertIn("async def _require_intent_admin(request: Request)", INTENT_ROUTER)
        self.assertIn("_admin_identity, request", INTENT_ROUTER)
        self.assertIn(
            "router = APIRouter(dependencies=[Depends(_require_intent_admin)])",
            INTENT_ROUTER,
        )
        self.assertIn('@router.post("/api/intent-experiments")', INTENT_ROUTER)
        self.assertIn('@router.post("/api/intent-experiments/{experiment_id}/close")', INTENT_ROUTER)


if __name__ == "__main__":
    unittest.main()
