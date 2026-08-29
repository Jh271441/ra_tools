from __future__ import annotations

import unittest

from auto_triage_bot.events import (
    challenge_value,
    extract_issue_id,
    extract_run_id,
    parse_event,
)


class EventParsingTest(unittest.TestCase):
    def test_normalized_event(self) -> None:
        event = parse_event(
            {
                "event_id": "evt-1",
                "sender": {"username": "Alice"},
                "message": {"text": "解释 issue 12345678"},
                "chat_id": "group-1",
            }
        )
        self.assertEqual(event.event_id, "evt-1")
        self.assertEqual(event.sender, "alice")
        self.assertEqual(event.text, "解释 issue 12345678")

    def test_string_data_adapter(self) -> None:
        event = parse_event(
            {
                "data": '{"eventId":"evt-2","sender_username":"bob","text":{"content":"hello 87654321"}}'
            }
        )
        self.assertEqual(event.event_id, "evt-2")
        self.assertEqual(event.sender, "bob")
        self.assertEqual(event.text, "hello 87654321")

    def test_invalid_sender_and_oversized_text_fail(self) -> None:
        with self.assertRaises(ValueError):
            parse_event({"sender": {"username": "bad user"}, "text": "hello"})
        with self.assertRaises(ValueError):
            parse_event(
                {"sender": {"username": "alice"}, "text": "x" * 20}, max_chars=10
            )

    def test_challenge_and_identifiers(self) -> None:
        self.assertEqual(challenge_value({"challenge": "abc"}), "abc")
        text = "看 https://example.intra/review?issue=12345678&run=run-abc"
        self.assertEqual(extract_issue_id(text), "12345678")
        self.assertEqual(extract_run_id(text), "run-abc")
        self.assertEqual(extract_issue_id("no issue here"), "")


if __name__ == "__main__":
    unittest.main()
