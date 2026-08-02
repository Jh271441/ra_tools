from __future__ import annotations

import unittest
from pathlib import Path


APP_JS = (
    Path(__file__).resolve().parents[1] / "static" / "app.js"
).read_text(encoding="utf-8")
STYLES_CSS = (
    Path(__file__).resolve().parents[1] / "static" / "styles.css"
).read_text(encoding="utf-8")


class FrontendContractTest(unittest.TestCase):
    def test_frontend_uses_one_base_path_boundary(self) -> None:
        self.assertIn('meta[name="ra-triage-base"]', APP_JS)
        self.assertIn("const CONFIGURED_BASE_PATH = normalizeClientBasePath(", APP_JS)
        self.assertIn("window.__RA_TRIAGE_BASE__ ?? CONFIGURED_BASE_PATH", APP_JS)
        self.assertIn("function withBase(path)", APP_JS)
        self.assertIn("function stripBasePath(pathname)", APP_JS)
        self.assertIn("removeBasePath(value, CONFIGURED_BASE_PATH)", APP_JS)
        self.assertIn("fetch(withBase(path)", APP_JS)
        self.assertIn("function normalizeApiPayloadUrls(value)", APP_JS)
        self.assertIn('key === "url" || key.endsWith("_url")', APP_JS)
        self.assertIn("stripBasePath(window.location.pathname)", APP_JS)

    def test_gallery_card_does_not_nest_controls_under_button_role(self) -> None:
        self.assertIn('class="issue-card-open"', APP_JS)
        self.assertIn('data-open-issue="${escapeHtml(item.issue_id)}"', APP_JS)
        self.assertIn('querySelectorAll("[data-open-issue]")', APP_JS)
        self.assertNotIn(
            'data-issue-id="${escapeHtml(item.issue_id)}" role="button"',
            APP_JS,
        )

    def test_batch_gateway_aligns_to_form_and_catalog_scrolls(self) -> None:
        self.assertIn(".batch-page-grid { align-items: stretch; }", STYLES_CSS)
        self.assertIn(".batch-page-grid > .tool-form { align-self: start; }", STYLES_CSS)
        self.assertIn("height: auto; min-height: 0", STYLES_CSS)
        self.assertIn("contain: size; overflow: hidden", STYLES_CSS)
        self.assertIn("contain: none; overflow: visible", STYLES_CSS)
        self.assertIn("grid-template-rows: auto auto auto auto minmax(0, 1fr) auto", STYLES_CSS)
        self.assertIn("overscroll-behavior: contain; scrollbar-gutter: stable", STYLES_CSS)


if __name__ == "__main__":
    unittest.main()
