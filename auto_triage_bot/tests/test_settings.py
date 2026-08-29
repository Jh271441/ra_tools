from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from auto_triage_bot.settings import Settings


class SettingsTest(unittest.TestCase):
    def test_enabled_requires_explicit_audience(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUTOTRIAGE_BOT_ENABLED": "true",
                "AUTOTRIAGE_BOT_ALLOWED_USERS": "",
                "AUTOTRIAGE_BOT_ALLOW_ALL_USERS": "false",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                Settings.from_env()

    def test_allowlist_is_normalized(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUTOTRIAGE_BOT_ENABLED": "true",
                "AUTOTRIAGE_BOT_ALLOWED_USERS": "Alice,bob",
                "AUTOTRIAGE_BOT_ALLOW_ALL_USERS": "false",
            },
            clear=False,
        ):
            settings = Settings.from_env()
        self.assertFalse(settings.smoke_enabled)
        self.assertEqual(settings.base_path, "/dchat")
        self.assertTrue(settings.user_allowed("ALICE"))
        self.assertFalse(settings.user_allowed("mallory"))

    def test_base_path_must_be_a_non_root_prefix(self) -> None:
        for value in ("", "/", "dchat", "/dchat/../manual"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"AUTOTRIAGE_BOT_BASE_PATH": value}, clear=False
            ):
                with self.assertRaises(RuntimeError):
                    Settings.from_env()

    def test_relay_url_is_fixed_to_worker_gateway(self) -> None:
        with patch.dict(
            os.environ,
            {"AUTOTRIAGE_BOT_RELAY_URL": "https://example.com/dchat-worker"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                Settings.from_env()

        with patch.dict(
            os.environ,
            {
                "AUTOTRIAGE_BOT_RELAY_URL": (
                    "https://ra-model.intra.xiaojukeji.com/dchat-worker"
                )
            },
            clear=False,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.worker_base_path, "/dchat-worker")


if __name__ == "__main__":
    unittest.main()
