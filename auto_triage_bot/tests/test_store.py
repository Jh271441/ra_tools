from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from auto_triage_bot.events import IncomingEvent
from auto_triage_bot.store import EventStore


class EventStoreTest(unittest.TestCase):
    def test_dedup_claim_complete_and_recover(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.sqlite3")
            store.init()
            event = IncomingEvent(event_id="evt-1", sender="alice", text="hello")
            self.assertTrue(store.enqueue(event))
            self.assertFalse(store.enqueue(event))
            claimed = store.claim_next()
            self.assertEqual(claimed["event_id"], "evt-1")
            self.assertEqual(claimed["attempt_count"], 1)

            recovered = EventStore(store.path)
            recovered.init()
            claimed_again = recovered.claim_next()
            self.assertEqual(claimed_again["attempt_count"], 2)
            recovered.complete("evt-1", answer="done", delivery_id="delivery")
            row = recovered.get("evt-1")
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["delivery_id"], "delivery")

    def test_permanent_failure_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.sqlite3")
            store.init()
            store.enqueue(IncomingEvent(event_id="evt-2", sender="alice", text="hello"))
            store.claim_next()
            store.fail("evt-2", error="bad recipient", attempts=1, terminal=True)
            self.assertEqual(store.get("evt-2")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
