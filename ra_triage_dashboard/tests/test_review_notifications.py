from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.dchat import (
    DChatClient,
    DChatLoopbackClient,
    build_comment_notification_text,
    build_review_url,
    dchat_credentials_status,
    validate_dchat_base_url,
)
from ra_triage_dashboard.app.support.annotations import _create_annotation_record
from ra_triage_dashboard.app.review_mentions import (
    extract_review_mentions,
    mentions_for_display,
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
            ["alice", "bob"],
        )
        self.assertEqual(
            mentions_for_display(
                "@jasperchen 请和 @{caoliwen_i} 确认",
                {"jasperchen": "陈俊豪", "caoliwen_i": "曹立文"},
            ),
            "@陈俊豪 请和 @曹立文 确认",
        )

    def test_verified_author_can_notify_themself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn1", "gt_label": "误触发"}],
                source="test",
                replace_gt=True,
            )
            database.set_mention_user(username="alice", enabled=True, actor="alice")
            with patch("ra_triage_dashboard.app.support.annotations.database", database), patch(
                "ra_triage_dashboard.app.support.catalogs.database", database
            ), patch(
                "ra_triage_dashboard.app.support.annotations._action_actor",
                return_value=("alice", "kylin_ticket", True),
            ), patch(
                "ra_triage_dashboard.app.support.annotations.settings",
                SimpleNamespace(dchat_notifications_enabled=True),
            ):
                annotation = _create_annotation_record(
                    issue_id="cn1",
                    request=make_request(),
                    body={"expected_output": "误触发", "note": "@alice 稍后继续处理"},
                )
            self.assertEqual(annotation["notification"]["queued"], ["alice"])
            self.assertEqual(database.review_notification_status()["pending"], 1)

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
            database.set_mention_user(username="bob", enabled=True, actor="alice")
            with patch("ra_triage_dashboard.app.support.annotations.database", database), patch(
                "ra_triage_dashboard.app.support.catalogs.database", database
            ), patch(
                "ra_triage_dashboard.app.support.annotations._action_actor",
                return_value=("alice", "kylin_ticket", True),
            ), patch(
                "ra_triage_dashboard.app.support.annotations.settings",
                SimpleNamespace(dchat_notifications_enabled=True),
            ):
                annotation = _create_annotation_record(
                    issue_id="cn1",
                    request=make_request(),
                    body={"expected_output": "误触发", "note": "@bob 请确认"},
                )
            self.assertEqual(annotation["notification"]["status"], "queued")
            self.assertEqual(annotation["notification"]["queued"], ["bob"])

    def test_verified_identity_rejects_recipient_outside_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn1", "gt_label": "误触发"}],
                source="test",
                replace_gt=True,
            )
            with patch("ra_triage_dashboard.app.support.annotations.database", database), patch(
                "ra_triage_dashboard.app.support.catalogs.database", database
            ), patch(
                "ra_triage_dashboard.app.support.annotations._action_actor",
                return_value=("alice", "kylin_ticket", True),
            ), patch(
                "ra_triage_dashboard.app.support.annotations.settings",
                SimpleNamespace(dchat_notifications_enabled=True),
            ):
                with self.assertRaisesRegex(HTTPException, "不在可 @"):
                    _create_annotation_record(
                        issue_id="cn1",
                        request=make_request(),
                        body={"expected_output": "误触发", "note": "@unknown 请确认"},
                    )

    def test_dchat_endpoint_and_review_url_are_fixed_and_encoded(self) -> None:
        self.assertEqual(
            validate_dchat_base_url("https://oapi-dichat.intra.xiaojukeji.com/"),
            "https://oapi-dichat.intra.xiaojukeji.com",
        )
        with self.assertRaises(RuntimeError):
            validate_dchat_base_url("https://example.com")

    def test_comment_deep_link_opens_exact_thread(self) -> None:
        self.assertEqual(
            build_review_url(
                "https://auto-triage.intra.xiaojukeji.com/manual/review",
                issue_id="cn1",
                model_run_id="run one",
                open_comments=True,
                comment_id=42,
            ),
            "https://auto-triage.intra.xiaojukeji.com/manual/review?issue=cn1&run=run+one&comments=1&comment=42",
        )
        self.assertEqual(
            build_review_url(
                "https://auto-triage.intra.xiaojukeji.com/manual/review",
                issue_id="cn 1",
                model_run_id="run/1",
            ),
            "https://auto-triage.intra.xiaojukeji.com/manual/review?issue=cn+1&run=run%2F1",
        )

    def test_comment_notification_replaces_internal_image_tokens(self) -> None:
        text = build_comment_notification_text(
            issue_id="cn1",
            author="陈俊豪",
            body="请查看 ![现场截图](attachment:7f7c5e1a-1234) 后确认。",
            review_url="https://example.test/review?issue=cn1&comments=1&comment=7",
        )
        self.assertIn("图片", text)
        self.assertNotIn("attachment", text)

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

    def test_cancellation_during_inflight_dchat_send_waits_before_lease_handoff_no_duplicate(self) -> None:
        import asyncio
        import contextlib
        import threading
        from ra_triage_dashboard.app.review_notification_dispatcher import ReviewNotificationDispatcher
        from ra_triage_dashboard.app.workers.leases import WorkerLeaseManager, run_with_lease

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues([{"issue_id": "cn1", "gt_label": "误触发"}], source="test", replace_gt=True)
            database.create_annotation(
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
            settings = SimpleNamespace(
                dchat_delivery_mode="loopback",
                dchat_poll_seconds=0.05,
                dchat_max_attempts=5,
                kylin_sso_return_url="https://example.test/manual",
            )
            dispatcher_a = ReviewNotificationDispatcher(settings, database)
            dispatcher_b = ReviewNotificationDispatcher(settings, database)
            leases_a = WorkerLeaseManager(database, owner_id="slot-a")
            leases_b = WorkerLeaseManager(database, owner_id="slot-b")

            send_started = threading.Event()
            release_send = threading.Event()
            sent_calls: list[tuple[str, str]] = []

            def paused_send(self_client, recipient: str, text: str):
                sent_calls.append((recipient, text))
                send_started.set()
                assert release_send.wait(timeout=5)
                return SimpleNamespace(trace_id="trace-1", message_unique_id="msg-1")

            async def _scenario() -> None:
                with patch.object(DChatLoopbackClient, "send_to_username", paused_send):
                    task_a = asyncio.create_task(
                        run_with_lease(
                            leases_a,
                            "review-dchat-notifications",
                            dispatcher_a.run,
                            ttl_seconds=10.0,
                            retry_seconds=0.03,
                            renew_interval=0.2,
                        )
                    )
                    for _ in range(100):
                        if send_started.is_set():
                            break
                        await asyncio.sleep(0.02)
                    self.assertTrue(send_started.is_set())

                    task_b = asyncio.create_task(
                        run_with_lease(
                            leases_b,
                            "review-dchat-notifications",
                            dispatcher_b.run,
                            ttl_seconds=10.0,
                            retry_seconds=0.03,
                            renew_interval=0.2,
                        )
                    )

                    # Cancel slot A mid-DChat send (simulating slot shutdown).
                    task_a.cancel()
                    await asyncio.sleep(0.15)
                    # Slot A must still be waiting for the in-flight send + DB commit
                    # before releasing its lease, so slot B cannot reclaim and re-send.
                    self.assertFalse(task_a.done())
                    self.assertEqual(len(sent_calls), 1)

                    release_send.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(task_a, timeout=3.0)

                    # Give slot B multiple polling intervals after taking over the lease.
                    await asyncio.sleep(0.25)
                    task_b.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.wait_for(task_b, timeout=3.0)

            asyncio.run(_scenario())
            self.assertEqual(len(sent_calls), 1)
            status = database.review_notification_status()
            self.assertEqual(status["sent"], 1)
            self.assertEqual(status["pending"], 0)
            self.assertEqual(status["sending"], 0)


if __name__ == "__main__":
    unittest.main()
