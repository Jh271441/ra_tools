import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ares_playwright.browser import launch_browser


class LaunchBrowserTest(unittest.TestCase):
    def test_no_proxy_adds_chrome_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            chrome = Path(directory) / "chrome"
            chrome.touch()
            playwright = MagicMock()

            launch_browser(
                playwright, str(chrome), headless=True, no_proxy=True
            )

        _, kwargs = playwright.chromium.launch.call_args
        self.assertTrue(kwargs["headless"])
        self.assertIn("--no-proxy-server", kwargs["args"])


if __name__ == "__main__":
    unittest.main()
