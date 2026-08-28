from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ra_triage_dashboard.app.dchat import DChatSendResult

from auto_triage_bot.service import RemoteBotWorker


def _settings(directory: str) -> SimpleNamespace:
    return SimpleNamespace(
        dashboard_base_url="http://127.0.0.1:8785",
        dashboard_timeout_seconds=1.0,
        model_id="",
        model_api_key_file=Path(directory) / "model-key",
        model_chat_url="http://127.0.0.1:9999/v1/chat/completions",
        model_timeout_seconds=1.0,
        model_temperature=0.2,
        max_answer_chars=2800,
        dashboard_review_url="https://auto-triage.intra.xiaojukeji.com/manual/review",
        relay_url="http://127.0.0.1/dchat-worker",
        relay_worker_secret_file=Path(directory) / "worker-secret",
        relay_worker_id="worker-1",
        dchat_timeout_seconds=1.0,
        relay_poll_seconds=0.2,
        delivery_mode="loopback",
        dchat_base_url="https://oapi-dichat.intra.xiaojukeji.com",
        dchat_credentials_file=Path(directory) / "dchat.json",
    )


class _Relay:
    def __init__(self) -> None:
        self.acked: list[tuple[str, str]] = []
        self.nacked: list[tuple[str, bool]] = []

    def ack(self, item, *, delivery_id):  # noqa: ANN001, ANN201
        self.acked.append((item["event_id"], delivery_id))

    def nack(self, item, *, error, terminal):  # noqa: ANN001, ANN201
        self.nacked.append((item["event_id"], terminal))


class RemoteWorkerTest(unittest.TestCase):
    def test_successful_delivery_is_acked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = RemoteBotWorker(settings=_settings(directory))
            relay = _Relay()
            worker.relay = relay
            worker.answer_service.answer = lambda _: "answer"
            worker._send = lambda *_: DChatSendResult("trace", "delivery")
            asyncio.run(
                worker._process(
                    {
                        "event_id": "evt-1",
                        "sender": "alice",
                        "question": "help",
                        "lease_token": "lease",
                    }
                )
            )
            self.assertEqual(relay.acked, [("evt-1", "delivery")])
            self.assertEqual(relay.nacked, [])


if __name__ == "__main__":
    unittest.main()
