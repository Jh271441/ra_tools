from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "configure_dchat_credentials.py"
)
SPEC = importlib.util.spec_from_file_location("configure_dchat_credentials", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfigureDChatCredentialsTest(unittest.TestCase):
    def test_writes_valid_owner_only_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "dchat_credentials.json"
            MODULE.write_credentials(
                target,
                client_id="formal-app",
                client_secret="formal-secret",
                bot_id="612718",
            )
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {
                    "client_id": "formal-app",
                    "client_secret": "formal-secret",
                    "bot_id": "612718",
                },
            )
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_rejects_missing_or_non_numeric_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "dchat_credentials.json"
            with self.assertRaisesRegex(ValueError, "Client ID"):
                MODULE.write_credentials(
                    target, client_id="", client_secret="secret", bot_id="1"
                )
            with self.assertRaisesRegex(ValueError, "Client Secret"):
                MODULE.write_credentials(
                    target, client_id="app", client_secret="", bot_id="1"
                )
            with self.assertRaisesRegex(ValueError, "纯数字"):
                MODULE.write_credentials(
                    target,
                    client_id="app",
                    client_secret="secret",
                    bot_id="bot-1",
                )


if __name__ == "__main__":
    unittest.main()
