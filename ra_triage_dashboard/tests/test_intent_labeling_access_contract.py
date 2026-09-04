from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROUTER = (ROOT / "app" / "routers" / "core.py").read_text(encoding="utf-8")
INTENT_ROUTER = (ROOT / "app" / "routers" / "intent_labeling.py").read_text(
    encoding="utf-8"
)


class IntentLabelingAccessContractTest(unittest.TestCase):
    def test_intent_capabilities_separate_view_annotation_management_and_reveal(self) -> None:
        page_start = CORE_ROUTER.index('@router.get("/intent-labeling"')
        page_block = CORE_ROUTER[page_start : page_start + 650]
        self.assertIn("intent_labeling_page(request: Request)", page_block)
        self.assertIn("_intent_identity, request", page_block)

        experiments_start = CORE_ROUTER.index('@router.get("/intent-experiments"')
        experiments_block = CORE_ROUTER[experiments_start : experiments_start + 650]
        self.assertIn("intent_experiments_page(request: Request)", experiments_block)
        self.assertIn("_intent_identity, request", experiments_block)

        self.assertIn("async def _require_intent_writer(request: Request)", INTENT_ROUTER)
        self.assertIn("async def _require_intent_manager(request: Request)", INTENT_ROUTER)
        self.assertIn("_intent_identity, request", INTENT_ROUTER)
        self.assertIn(
            "router = APIRouter(dependencies=[Depends(_require_intent_viewer)])",
            INTENT_ROUTER,
        )
        self.assertGreaterEqual(INTENT_ROUTER.count("Depends(_require_intent_manager)"), 2)
        self.assertIn("Depends(_require_intent_writer)", INTENT_ROUTER)
        self.assertIn('@router.delete(', INTENT_ROUTER)
        self.assertIn('expected_revision_id: int = Query(gt=0)', INTENT_ROUTER)
        self.assertIn('"/api/intent-experiments"', INTENT_ROUTER)
        self.assertIn('"/api/intent-experiments/{experiment_id}/close"', INTENT_ROUTER)
        self.assertIn('"/api/intent-experiments/name-suggestion"', INTENT_ROUTER)
        self.assertIn('@router.get("/api/intent-cases")', INTENT_ROUTER)
        self.assertIn("_intent_summary_payload_multi", INTENT_ROUTER)
        self.assertIn('"/api/intent-datasets/{dataset_id}/cases/{case_id}/labels/{username}"', INTENT_ROUTER)
        self.assertIn("Depends(_require_intent_admin)", INTENT_ROUTER)
        self.assertGreaterEqual(INTENT_ROUTER.count("await asyncio.to_thread(_admin_identity, request)"), 2)
        self.assertIn('async def _require_intent_admin(request: Request)', INTENT_ROUTER)
        self.assertIn('"/api/intent-datasets/{dataset_id}/export"', INTENT_ROUTER)
        self.assertIn('await asyncio.to_thread(_admin_identity, request)', INTENT_ROUTER)
        self.assertIn('cases/{case_id}/comments"', INTENT_ROUTER)
        self.assertIn('"answers_revealed": answers_revealed', INTENT_ROUTER)
        self.assertIn("public_intent_contributors(", INTENT_ROUTER)
        self.assertIn("search_intent_comments(", INTENT_ROUTER)
        self.assertIn("q: str = \"\"", INTENT_ROUTER)
        self.assertIn("list_intent_case_assignees", INTENT_ROUTER)
        self.assertNotIn("if item[\"revealed\"]:", INTENT_ROUTER)
        self.assertIn("if reveal_answers:", INTENT_ROUTER)
        self.assertIn("await asyncio.to_thread(_admin_identity, request)", INTENT_ROUTER)


if __name__ == "__main__":
    unittest.main()
