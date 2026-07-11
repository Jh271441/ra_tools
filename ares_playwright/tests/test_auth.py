import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ares_playwright.auth import (
    APP_ERROR_TEXT,
    validate_saved_login_state,
    validate_state_file_structure,
)
from ares_playwright.models import AuthStatus


class ValidateStateFileStructureTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, value):
        self.state_file.write_text(json.dumps(value), encoding="utf-8")

    def test_missing_file_is_invalid(self):
        result = validate_state_file_structure(self.state_file)
        self.assertEqual(result.status, AuthStatus.INVALID)

    def test_invalid_json_is_invalid(self):
        self.state_file.write_text("{", encoding="utf-8")
        result = validate_state_file_structure(self.state_file)
        self.assertEqual(result.status, AuthStatus.INVALID)
        self.assertIn("解析失败", result.reason)

    def test_wrong_field_type_is_invalid(self):
        self.write_json({"cookies": {}, "origins": []})
        result = validate_state_file_structure(self.state_file)
        self.assertEqual(result.status, AuthStatus.INVALID)
        self.assertIn("cookies", result.reason)

    def test_empty_state_is_invalid(self):
        self.write_json({"cookies": [], "origins": []})
        result = validate_state_file_structure(self.state_file)
        self.assertEqual(result.status, AuthStatus.INVALID)

    def test_cookie_state_has_valid_structure(self):
        self.write_json(
            {
                "cookies": [
                    {
                        "name": "session",
                        "value": "redacted",
                        "domain": ".example.test",
                        "path": "/",
                    }
                ],
                "origins": [],
            }
        )
        result = validate_state_file_structure(self.state_file)
        self.assertEqual(result.status, AuthStatus.VALID)

    def make_browser(self, final_url, body_text="", title="Ares Studio"):
        self.write_json({"cookies": [{"name": "session"}], "origins": []})
        page = MagicMock()
        page.url = final_url
        page.frames = []
        page.title.return_value = title
        page.locator.return_value.inner_text.return_value = body_text
        context = MagicMock()
        context.new_page.return_value = page
        browser = MagicMock()
        browser.new_context.return_value = context
        return browser, context

    def test_real_validation_uses_fresh_context_and_accepts_app_error(self):
        browser, context = self.make_browser(
            "https://voyager.intra.xiaojukeji.com/static/ares-studio/",
            body_text="Service not registered, please register service first",
        )

        result = validate_saved_login_state(browser, self.state_file)

        self.assertEqual(result.status, AuthStatus.VALID)
        self.assertEqual(result.app_error, APP_ERROR_TEXT)
        browser.new_context.assert_called_once_with(
            storage_state=str(self.state_file),
            ignore_https_errors=True,
            no_viewport=True,
        )
        context.close.assert_called_once()

    def test_real_validation_rejects_login_redirect(self):
        browser, context = self.make_browser(
            "https://me.xiaojukeji.com/login"
        )

        result = validate_saved_login_state(browser, self.state_file)

        self.assertEqual(result.status, AuthStatus.INVALID)
        self.assertIn("重定向", result.reason)
        context.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
