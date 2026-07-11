import unittest
from unittest.mock import MagicMock, patch

from ares_playwright.cli import main, parse_args
from ares_playwright.models import AuthStatus, StateValidationResult


class HeadlessCliTest(unittest.TestCase):
    def test_headless_defaults_to_false(self):
        self.assertFalse(parse_args([]).headless)

    def test_headless_flag_is_parsed(self):
        self.assertTrue(parse_args(["--headless"]).headless)

    def test_no_proxy_flag_is_parsed(self):
        self.assertTrue(parse_args(["--no-proxy"]).no_proxy)

    @patch("ares_playwright.cli.launch_browser")
    @patch("ares_playwright.cli.sync_playwright")
    @patch("ares_playwright.cli._validate")
    def test_headless_is_forwarded_to_browser(
        self, validate, sync_playwright, launch
    ):
        playwright = MagicMock()
        sync_playwright.return_value.__enter__.return_value = playwright
        browser = launch.return_value
        validate.return_value = StateValidationResult(
            AuthStatus.VALID, "test state"
        )

        main(["--mode", "validate-state", "--headless", "--no-proxy"])

        launch.assert_called_once_with(
            playwright,
            "/usr/bin/google-chrome",
            headless=True,
            no_proxy=True,
        )
        browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
