from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

from auto_triage_bot.settings import Settings
from auto_triage_bot.thin_server import create_server, template_reply


class ThinServerTest(unittest.TestCase):
    def test_templates_are_deterministic(self) -> None:
        self.assertIn("鲁班直连测试版", template_reply("hello"))
        self.assertIn("只验证 DChat", template_reply("帮助"))
        self.assertIn("鲁班直连验证成功", template_reply("任意问题"))

    def test_authenticated_callback_replies_without_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            webhook = data_dir / "webhook_secret"
            webhook.write_text("webhook-token", encoding="utf-8")
            webhook.chmod(0o600)
            config = replace(
                Settings.from_env(),
                enabled=True,
                allowed_users=frozenset({"alice"}),
                data_dir=data_dir,
                webhook_auth_mode="token",
                webhook_secret_file=webhook,
                base_path="/dchat-thin",
            )
            try:
                server = create_server(config, host="127.0.0.1", port=0)
            except PermissionError:
                self.skipTest("test sandbox does not permit binding a loopback port")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                with urllib.request.urlopen(base_url + "/health", timeout=2) as response:
                    health = json.loads(response.read().decode("utf-8"))
                self.assertEqual(health["role"], "luban_direct_template")
                self.assertFalse(health["cloud_server"])

                payload = json.dumps(
                    {
                        "event_id": "evt-thin-1",
                        "sender": {"username": "alice"},
                        "message": {"text": "hello"},
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                request = urllib.request.Request(
                    base_url + "/",
                    data=payload,
                    method="POST",
                    headers={
                        "X-Auto-Triage-Signature": "webhook-token",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    accepted = json.loads(response.read().decode("utf-8"))
                self.assertIn("固定模板回复成功", accepted["text"])

                # The thin server intentionally has no relay worker API.
                pull = urllib.request.Request(
                    base_url + "/pull",
                    data=b"{}",
                    method="POST",
                    headers={
                        "Authorization": "Bearer unused",
                        "Content-Type": "application/json",
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(pull, timeout=2)
                self.assertEqual(rejected.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
