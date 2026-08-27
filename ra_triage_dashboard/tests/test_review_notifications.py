from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.dchat import (
    DChatClient,
    DChatLoopbackClient,
    build_review_url,
    dchat_credentials_status,
    validate_dchat_base_url,
)
from ra_triage_dashboard.app.http_support import _create_annotation_record
from ra_triage_dashboard.app.review_mentions import (
    extract_review_mentions,
    notification_recipients,
)


def make_request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/cases/cn1/annotations", "headers": []})


class ReviewNotificationTest(unittest.TestCase):
    def test_mentions_support_plain_and_braced_syntax(self) -> None:
        self.assertEqual(
            extract_review_mentions("@Alice 看一下，@{bob.li} cc @alice @all a@corp.com"),
            ["alice", "bob.li"],
        )
        self.assertEqual(
            notification_recipients(["alice", "bob", "bob"], author="Alice"),
            ["bob"],
        )

    def test_mention_limit_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "最多"):
            extract_review_mentions(" ".join(f"@user{i}" for i in range(11)))

    def test_annotation_and_outbox_are_committed_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues([{"issue_id": "cn1", "gt_label": "误触发"}], source="test", replace_gt=True)
            annotation = database.create_annotation(
                issue_id="cn1",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="@bob 请确认",
                author="alice",
                author_verified=True,
                mentions=["bob"],
                notification_recipients=["bob"],
            )
            self.assertEqual(annotation["mentions"], ["bob"])
            self.assertEqual(database.review_notification_status()["pending"], 1)
            claimed = database.claim_review_notification(now="9999-12-31T00:00:00+00:00")
            self.assertEqual(claimed["recipient"], "bob")
            self.assertEqual(claimed["attempt_count"], 1)
            database.complete_review_notification(
                claimed["id"], trace_id="trace", message_unique_id="message"
            )
            self.assertEqual(database.review_notification_status()["sent"], 1)

    def test_only_verified_identity_queues_external_notification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues([{"issue_id": "cn1", "gt_label": "误触发"}], source="test", replace_gt=True)
            with patch("ra_triage_dashboard.app.http_support.database", database), patch(
                "ra_triage_dashboard.app.http_support._action_actor",
                return_value=("alice", "kylin_ticket", True),
            ), patch(
                "ra_triage_dashboard.app.http_support.settings",
                SimpleNamespace(dchat_notifications_enabled=True),
            ):
                annotation = _create_annotation_record(
                    issue_id="cn1",
                    request=make_request(),
                    body={"expected_output": "误触发", "note": "@bob 请确认"},
                )
            self.assertEqual(annotation["notification"]["status"], "queued")
            self.assertEqual(annotation["notification"]["queued"], ["bob"])

    def test_dchat_endpoint_and_review_url_are_fixed_and_encoded(self) -> None:
        self.assertEqual(
            validate_dchat_base_url("https://oapi-dichat.intra.xiaojukeji.com/"),
            "https://oapi-dichat.intra.xiaojukeji.com",
        )
        with self.assertRaises(RuntimeError):
            validate_dchat_base_url("https://example.com")
        self.assertEqual(
            build_review_url(
                "https://auto-triage.intra.xiaojukeji.com/manual/review",
                issue_id="cn 1",
                model_run_id="run/1",
            ),
            "https://auto-triage.intra.xiaojukeji.com/manual/review?issue=cn+1&run=run%2F1",
        )

    def test_loopback_returns_a_local_receipt_without_network(self) -> None:
        result = DChatLoopbackClient().send_to_username("jasperchen", "hello")
        self.assertTrue(result.trace_id.startswith("loopback-"))
        self.assertTrue(result.message_unique_id.startswith("loopback-"))

    def test_credentials_require_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dchat.json"
            path.write_text(json.dumps({"client_id": "app", "client_secret": "secret", "bot_id": "123"}))
            os.chmod(path, 0o644)
            self.assertFalse(dchat_credentials_status(path)["ready"])
            os.chmod(path, 0o600)
            self.assertTrue(dchat_credentials_status(path)["ready"])

    def test_client_uses_bot_user_basic_auth_and_username_recipient(self) -> None:
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read(_size):
                return json.dumps(
                    {"code": 0, "result": {"trace_id": "t1", "message_unique_id": "m1"}}
                ).encode()

        class Opener:
            @staticmethod
            def open(request, timeout):
                captured["request"] = request
                captured["timeout"] = timeout
                return Response()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dchat.json"
            path.write_text(json.dumps({"client_id": "app", "client_secret": "secret", "bot_id": "123"}))
            os.chmod(path, 0o600)
            with patch("ra_triage_dashboard.app.dchat.urllib.request.build_opener", return_value=Opener()):
                result = DChatClient(
                    base_url="https://oapi-dichat.intra.xiaojukeji.com",
                    credentials_file=path,
                    timeout_seconds=2,
                ).send_to_username("Bob", "hello")
        request = captured["request"]
        self.assertEqual(request.full_url, "https://oapi-dichat.intra.xiaojukeji.com/v3/message.create")
        self.assertEqual(request.get_header("X-bot-type"), "bot_user")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        payload = json.loads(request.data)
        self.assertEqual(payload["receive_id"], "bob")
        self.assertEqual(payload["receive_id_type"], "2")
        self.assertTrue(payload["markdown"])
        self.assertEqual(result.message_unique_id, "m1")


if __name__ == "__main__":
    unittest.main()
