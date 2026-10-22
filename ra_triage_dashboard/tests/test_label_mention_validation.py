import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from fastapi import HTTPException
from ra_triage_dashboard.app.support.label_mentions import prepare_label_mentions


class LabelMentionValidationTest(unittest.TestCase):
    def test_unknown_directory_user_rejected_and_disabled_delivery_not_queued(self):
        db = Mock(); db.enabled_mention_recipients.return_value = ["bob"]
        settings = SimpleNamespace(dchat_notifications_enabled=True)
        def prepare(text, verified=True):
            return asyncio.run(prepare_label_mentions(db, settings, text, "alice", verified))
        self.assertEqual(prepare("@bob @bob"), ["bob"])
        with self.assertRaises(HTTPException) as exc:
            prepare("@unknown")
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(prepare("@bob", verified=False), [])
        settings.dchat_notifications_enabled = False
        self.assertEqual(prepare("@bob"), [])
