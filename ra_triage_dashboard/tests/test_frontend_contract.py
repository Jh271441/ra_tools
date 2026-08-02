from __future__ import annotations

import unittest
from pathlib import Path


APP_JS = (
    Path(__file__).resolve().parents[1] / "static" / "app.js"
).read_text(encoding="utf-8")


class FrontendContractTest(unittest.TestCase):
    def test_gallery_card_does_not_nest_controls_under_button_role(self) -> None:
        self.assertIn('class="issue-card-open"', APP_JS)
        self.assertIn('data-open-issue="${escapeHtml(item.issue_id)}"', APP_JS)
        self.assertIn('querySelectorAll("[data-open-issue]")', APP_JS)
        self.assertNotIn(
            'data-issue-id="${escapeHtml(item.issue_id)}" role="button"',
            APP_JS,
        )


if __name__ == "__main__":
    unittest.main()
