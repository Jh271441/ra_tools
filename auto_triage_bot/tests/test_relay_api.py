from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    TestClient = None

from auto_triage_bot.relay_main import create_relay_app
from auto_triage_bot.settings import Settings


@unittest.skipIf(TestClient is None, "httpx test dependency is not installed")
class RelayApiTest(unittest.TestCase):
    def test_callback_pull_and_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            webhook = data_dir / "webhook_secret"
            worker = data_dir / "relay_worker_secret"
            webhook.write_text("webhook-token", encoding="utf-8")
            worker.write_text("worker-token", encoding="utf-8")
            webhook.chmod(0o600)
            worker.chmod(0o600)
            config = replace(
                Settings.from_env(),
                enabled=True,
                allowed_users=frozenset({"alice"}),
                data_dir=data_dir,
                webhook_auth_mode="token",
                webhook_secret_file=webhook,
                relay_worker_secret_file=worker,
                relay_worker_id="worker-1",
            )
            app = create_relay_app(config)
            with TestClient(app) as client:
                event = {
                    "event_id": "evt-relay-api",
                    "sender": {"username": "alice"},
                    "message": {"text": "帮助"},
                }
                accepted = client.post(
                    "/",
                    content=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                    headers={"Authorization": "Bearer webhook-token"},
                )
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(
                    client.post("/pull", json={"worker_id": "worker-1"}).status_code,
                    401,
                )
                pulled = client.post(
                    "/pull",
                    json={"worker_id": "worker-1"},
                    headers={"Authorization": "Bearer worker-token"},
                )
                self.assertEqual(pulled.status_code, 200)
                item = pulled.json()
                self.assertEqual(item["event_id"], "evt-relay-api")
                acked = client.post(
                    "/ack",
                    json={
                        "event_id": item["event_id"],
                        "lease_token": item["lease_token"],
                        "delivery_id": "delivery-1",
                    },
                    headers={"Authorization": "Bearer worker-token"},
                )
                self.assertEqual(acked.status_code, 200)
                empty = client.post(
                    "/pull",
                    json={"worker_id": "worker-1"},
                    headers={"Authorization": "Bearer worker-token"},
                )
                self.assertEqual(empty.status_code, 204)


if __name__ == "__main__":
    unittest.main()
