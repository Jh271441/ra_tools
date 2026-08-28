from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # Local macOS Python may omit the test-only httpx.
    TestClient = None

from auto_triage_bot.main import create_app
from auto_triage_bot.settings import Settings


@unittest.skipIf(TestClient is None, "httpx test dependency is not installed")
class BotApiTest(unittest.TestCase):
    def test_authenticated_challenge_and_botuser_message_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            secret_path = data_dir / "webhook_secret"
            secret_path.write_bytes(b"test-secret")
            secret_path.chmod(0o600)
            config = replace(
                Settings.from_env(),
                enabled=True,
                allowed_users=frozenset({"alice"}),
                data_dir=data_dir,
                webhook_secret_file=secret_path,
                delivery_mode="loopback",
                model_id="",
            )
            app = create_app(config)
            with TestClient(app) as client:
                self.assertEqual(client.get("/dchat/smoke").status_code, 404)
                challenge = json.dumps({"challenge": "verify-me"}).encode()
                response = client.post(
                    "/dchat",
                    content=challenge,
                    headers={
                        "Content-Type": "application/json",
                        "X-DChat-Signature": hmac.new(
                            b"test-secret", challenge, hashlib.sha256
                        ).hexdigest(),
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"challenge": "verify-me"})

                event = json.dumps(
                    {
                        "event_id": "evt-api-1",
                        "sender": {"username": "alice"},
                        "message": {"text": "帮助"},
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                headers = {
                    "Content-Type": "application/json",
                    "X-DChat-Signature": hmac.new(
                        b"test-secret", event, hashlib.sha256
                    ).hexdigest(),
                }
                accepted = client.post("/dchat", content=event, headers=headers)
                duplicate = client.post("/dchat", content=event, headers=headers)
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(
                    accepted.json(), {"text": "收到，正在处理，结果会私聊发送给你。"}
                )
                self.assertEqual(
                    duplicate.json(), {"text": "这个问题正在处理，完成后会私聊发送给你。"}
                )

                deadline = time.monotonic() + 2
                row = None
                while time.monotonic() < deadline:
                    row = app.state.bot_store.get("evt-api-1")
                    if row and row["status"] == "completed":
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(row)
                self.assertEqual(row["status"], "completed")
                self.assertIn("我可以解释", row["answer"])

                completed_duplicate = client.post(
                    "/dchat", content=event, headers=headers
                )
                self.assertEqual(completed_duplicate.status_code, 200)
                self.assertIn("我可以解释", completed_duplicate.json()["text"])

    def test_disabled_and_bad_signature_fail_closed(self) -> None:
        config = Settings.from_env()
        app = create_app(config)
        with TestClient(app) as client:
            self.assertEqual(client.post("/dchat", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
