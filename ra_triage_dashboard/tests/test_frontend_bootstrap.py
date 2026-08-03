from __future__ import annotations

import unittest
from pathlib import Path


APP_JS = (
    Path(__file__).resolve().parents[1] / "static" / "app.js"
).read_text(encoding="utf-8")


class FrontendBootstrapTest(unittest.TestCase):
    def test_bootstrap_handles_dynamically_loaded_app_script(self) -> None:
        self.assertIn('document.readyState === "loading"', APP_JS)
        self.assertIn(
            'window.addEventListener("DOMContentLoaded", bootstrap, { once: true })',
            APP_JS,
        )
        self.assertIn("else {\n  bootstrap();\n}", APP_JS)

    def test_initial_route_owns_its_heavy_requests(self) -> None:
        self.assertIn("loadPageData = true", APP_JS)
        self.assertEqual(APP_JS.count("loadPageData: false"), 2)
        self.assertIn("const initialPageRequests = [loadOverview()]", APP_JS)
        self.assertIn('initialRoute.page === "review"', APP_JS)
        self.assertIn('initialRoute.page === "status"', APP_JS)
        self.assertIn('initialRoute.page === "prediction"', APP_JS)

    def test_optional_lca_and_deep_link_support_data_do_not_block_first_content(self) -> None:
        session_start = APP_JS.index("async function loadSession()")
        session_end = APP_JS.index("\nfunction renderConfig()", session_start)
        session_body = APP_JS[session_start:session_end]
        self.assertIn("void browserLcaUsername().then", session_body)
        self.assertNotIn("await browserLcaUsername()", session_body)
        self.assertIn("let initialDetailRequest = null", APP_JS)
        self.assertIn(
            "initialDetailRequest = selectCase(initialRoute.issue, { updateRoute: false })",
            APP_JS,
        )
        self.assertIn("void Promise.all(initialPageRequests).catch", APP_JS)
        self.assertIn("await initialDetailRequest", APP_JS)
        self.assertIn('issue: initialRoute.issue', APP_JS)


if __name__ == "__main__":
    unittest.main()
