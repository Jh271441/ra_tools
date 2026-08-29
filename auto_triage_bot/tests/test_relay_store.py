from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from auto_triage_bot.events import IncomingEvent
from auto_triage_bot.relay_store import RelayStore


class RelayStoreTest(unittest.TestCase):
    def test_dedup_lease_ack_and_stale_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RelayStore(Path(directory) / "relay.sqlite3")
            store.init()
            event = IncomingEvent("evt-1", "alice", "帮助", "chat-1")
            self.assertTrue(store.enqueue(event))
            self.assertFalse(store.enqueue(event))

            item = store.claim_next(
                worker_id="worker-1", lease_seconds=120, max_attempts=5
            )
            self.assertIsNotNone(item)
            self.assertEqual(item["attempt_count"], 1)
            self.assertFalse(
                store.ack(
                    event_id="evt-1", lease_token="wrong", delivery_id="delivery"
                )
            )
            self.assertTrue(
                store.ack(
                    event_id="evt-1",
                    lease_token=item["lease_token"],
                    delivery_id="delivery",
                )
            )
            self.assertTrue(
                store.ack(
                    event_id="evt-1",
                    lease_token=item["lease_token"],
                    delivery_id="delivery",
                )
            )
            self.assertEqual(store.get("evt-1")["status"], "completed")
            self.assertNotIn(item["lease_token"], str(store.get("evt-1")))
            self.assertEqual(store.counts()["completed"], 1)

    def test_expired_lease_requeues_and_nack_can_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RelayStore(Path(directory) / "relay.sqlite3")
            store.init()
            store.enqueue(IncomingEvent("evt-2", "alice", "hello"))
            first = store.claim_next(
                worker_id="worker-1", lease_seconds=0, max_attempts=2
            )
            second = store.claim_next(
                worker_id="worker-1", lease_seconds=120, max_attempts=2
            )
            self.assertEqual(second["attempt_count"], 2)
            self.assertNotEqual(first["lease_token"], second["lease_token"])
            self.assertFalse(
                store.ack(
                    event_id="evt-2",
                    lease_token=first["lease_token"],
                    delivery_id="stale",
                )
            )
            self.assertTrue(
                store.nack(
                    event_id="evt-2",
                    lease_token=second["lease_token"],
                    error="permanent",
                    terminal=True,
                    max_attempts=2,
                )
            )
            self.assertEqual(store.get("evt-2")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
