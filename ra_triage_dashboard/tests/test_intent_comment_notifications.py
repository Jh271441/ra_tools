from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from starlette.requests import Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.dchat import (
    DChatSendResult,
    build_intent_comment_notification_text,
    build_intent_comment_url,
)
from ra_triage_dashboard.app.review_notification_dispatcher import (
    ReviewNotificationDispatcher,
)
from ra_triage_dashboard.app.routers import intent_labeling as intent_router


def json_request(payload: dict[str, object]) -> Request:
    content = json.dumps(payload).encode("utf-8")
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": content, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/intent-datasets/test-v1/cases/case-1/comments",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


class IntentCommentNotificationTest(unittest.TestCase):
    def make_database(self, directory: str) -> Database:
        database = Database(Path(directory) / "triage.sqlite3")
        database.init()
        database.upsert_issues(
            [{"issue_id": "issue-1", "gt_label": "误触发"}],
            source="test",
            replace_gt=True,
        )
        database.set_mention_user(
            username="bob",
            display_name="Bob",
            enabled=True,
            actor="admin",
        )
        return database

    def router_patches(self, database: Database, dispatcher: Mock):
        return patch.multiple(
            intent_router,
            database=database,
            review_notification_dispatcher=dispatcher,
            settings=SimpleNamespace(dchat_notifications_enabled=True),
            intent_dataset_registry=SimpleNamespace(
                has_case=lambda _dataset_id, _case_id: True
            ),
            _action_actor=lambda _request: ("alice", "kylin_ticket", True),
        )

    def test_intent_mention_is_validated_persisted_and_queued(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            dispatcher = Mock()
            with self.router_patches(database, dispatcher):
                result = asyncio.run(
                    intent_router.post_intent_comment(
                        json_request({"body": "@bob 请确认这帧"}),
                        "test-v1",
                        "case-1",
                    )
                )

            self.assertEqual(result["comment"]["mentions"], ["bob"])
            self.assertEqual(result["notification"]["queued"], ["bob"])
            self.assertEqual(result["notification"]["status"], "queued")
            dispatcher.wake.assert_called_once_with()
            self.assertEqual(
                database.list_intent_comments("test-v1", "case-1")[0]["mentions"],
                ["bob"],
            )
            self.assertEqual(
                database.intent_comment_notification_status()["pending"], 1
            )

    def test_intent_reply_notifies_parent_without_visible_mention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            parent = database.create_intent_comment(
                dataset_id="test-v1",
                case_id="case-1",
                body="请看这帧",
                author="bob",
                author_source="sso",
                author_verified=True,
            )
            dispatcher = Mock()
            with self.router_patches(database, dispatcher):
                result = asyncio.run(
                    intent_router.post_intent_comment(
                        json_request(
                            {
                                "body": "我已经处理好了",
                                "reply_to_id": parent["id"],
                            }
                        ),
                        "test-v1",
                        "case-1",
                    )
                )

            self.assertEqual(result["comment"]["mentions"], [])
            self.assertEqual(result["notification"]["queued"], ["bob"])
            self.assertEqual(database.intent_comment_notification_status()["pending"], 1)
            dispatcher.wake.assert_called_once_with()

    def test_intent_mention_outside_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            with self.router_patches(database, Mock()):
                with self.assertRaisesRegex(HTTPException, "不在可 @"):
                    asyncio.run(
                        intent_router.post_intent_comment(
                            json_request({"body": "@unknown 请确认"}),
                            "test-v1",
                            "case-1",
                        )
                    )
            self.assertEqual(database.list_intent_comments("test-v1", "case-1"), [])

    def test_intent_notification_dispatches_through_loopback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.create_intent_comment(
                dataset_id="test-v1",
                case_id="case-1",
                body="@bob 请确认",
                author="alice",
                author_source="sso",
                author_verified=True,
                mentions=["bob"],
                notification_recipients=["bob"],
            )
            settings = SimpleNamespace(
                dchat_delivery_mode="loopback",
                kylin_sso_return_url="https://auto-triage.intra.xiaojukeji.com/manual/review",
                dchat_max_attempts=3,
            )
            async def dispatch() -> tuple[bool, bool]:
                dispatcher = ReviewNotificationDispatcher(settings, database)
                return dispatcher._dispatch_one(), dispatcher._dispatch_one()

            sent_texts: list[str] = []

            def fake_send(_username: str, text: str) -> DChatSendResult:
                sent_texts.append(text)
                return DChatSendResult("trace", "message")

            with patch(
                "ra_triage_dashboard.app.review_notification_dispatcher.DChatLoopbackClient.send_to_username",
                side_effect=fake_send,
            ):
                first, second = asyncio.run(dispatch())
            self.assertTrue(first)
            self.assertEqual(database.intent_comment_notification_status()["sent"], 1)
            self.assertIn("@Bob", sent_texts[0])
            self.assertFalse(second)

    def test_intent_notification_has_a_precise_deep_link_and_context(self) -> None:
        url = build_intent_comment_url(
            "https://auto-triage.intra.xiaojukeji.com/manual/review",
            dataset_id="test-v1",
            case_id="case 1",
            comment_id=7,
        )
        self.assertEqual(
            url,
            "https://auto-triage.intra.xiaojukeji.com/manual/intent-labeling?"
            "dataset=test-v1&case=case+1&comments=1&comment=7",
        )
        text = build_intent_comment_notification_text(
            dataset_id="test-v1",
            case_id="case-1",
            author="Alice",
            body="@Bob 请确认",
            review_url=url,
        )
        self.assertIn("意图 Case", text)
        self.assertIn("查看意图讨论", text)

    def test_review_and_issue_comment_notifications_resolve_mentioned_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.create_review_comment(
                issue_id="issue-1",
                body="@bob 请看评论",
                author="alice",
                author_verified=True,
                mentions=["bob"],
                notification_recipients=["bob"],
            )
            database.create_annotation(
                issue_id="issue-1",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="@bob 请看 Review",
                author="alice",
                author_verified=True,
                mentions=["bob"],
                notification_recipients=["bob"],
            )
            settings = SimpleNamespace(
                dchat_delivery_mode="loopback",
                kylin_sso_return_url="https://auto-triage.intra.xiaojukeji.com/manual/review",
                dchat_max_attempts=3,
            )
            sent_texts: list[str] = []

            def fake_send(_username: str, text: str) -> DChatSendResult:
                sent_texts.append(text)
                return DChatSendResult("trace", "message")

            async def dispatch() -> tuple[bool, bool]:
                dispatcher = ReviewNotificationDispatcher(settings, database)
                return dispatcher._dispatch_one(), dispatcher._dispatch_one()

            with patch(
                "ra_triage_dashboard.app.review_notification_dispatcher.DChatLoopbackClient.send_to_username",
                side_effect=fake_send,
            ):
                first, second = asyncio.run(dispatch())

            self.assertTrue(first)
            self.assertTrue(second)
            self.assertEqual(len(sent_texts), 2)
            self.assertTrue(all("@Bob" in text for text in sent_texts))


if __name__ == "__main__":
    unittest.main()
