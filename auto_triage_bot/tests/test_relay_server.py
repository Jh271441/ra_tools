from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from dataclasses import replace
from pathlib import Path

from auto_triage_bot.relay_client import RelayClient
from auto_triage_bot.relay_server import create_server
from auto_triage_bot.settings import Settings


class RelayServerTest(unittest.TestCase):
    def test_stdlib_callback_pull_ack(self) -> None:
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
            try:
                server = create_server(config, host="127.0.0.1", port=0)
            except PermissionError:
                self.skipTest("test sandbox does not permit binding a loopback port")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                payload = json.dumps(
                    {
                        "event_id": "evt-stdlib-1",
                        "sender": {"username": "alice"},
                        "message": {"text": "帮助"},
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                request = urllib.request.Request(
                    base_url + "/",
                    data=payload,
                    method="POST",
                    headers={
                        "Authorization": "Bearer webhook-token",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    accepted = json.loads(response.read().decode("utf-8"))
                self.assertIn("正在处理", accepted["text"])

                client = RelayClient(
                    base_url=base_url,
                    secret_file=worker,
                    worker_id="worker-1",
                    timeout_seconds=2,
                )
                item = client.pull()
                self.assertEqual(item["event_id"], "evt-stdlib-1")
                client.ack(item, delivery_id="delivery-1")
                self.assertIsNone(client.pull())
                self.assertEqual(
                    server.relay_store.counts()["completed"],  # type: ignore[attr-defined]
                    1,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
