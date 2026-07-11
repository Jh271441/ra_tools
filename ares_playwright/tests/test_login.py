import unittest
from unittest.mock import MagicMock, PropertyMock

from ares_playwright.login import _find_login_frame


class FindLoginFrameTest(unittest.TestCase):
    def test_waits_for_async_redirect_before_treating_target_as_logged_in(self):
        page = MagicMock()
        type(page).url = PropertyMock(
            side_effect=[
                "https://voyager.intra.xiaojukeji.com/static/ares-studio/",
                "https://me.xiaojukeji.com/project/stargate-auth/html/login.html",
            ]
        )
        frame = MagicMock()
        password = frame.locator.return_value
        password.count.side_effect = [0, 1]
        page.frames = [frame]

        result = _find_login_frame(
            page, timeout_ms=1_000, target_stable_ms=8_000
        )

        self.assertIs(result, frame)
        page.wait_for_timeout.assert_called_once_with(500)

    def test_accepts_target_after_it_remains_stable(self):
        page = MagicMock()
        page.url = (
            "https://voyager.intra.xiaojukeji.com/static/ares-studio/"
        )
        frame = MagicMock()
        frame.locator.return_value.count.return_value = 0
        page.frames = [frame]

        result = _find_login_frame(
            page, timeout_ms=1_000, target_stable_ms=0
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
