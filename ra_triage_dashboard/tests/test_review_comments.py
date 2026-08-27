from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from starlette.requests import Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers.cases import create_review_comment


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
            "path": "/api/cases/cn1/comments",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


class ReviewCommentsTest(unittest.TestCase):
    def make_database(self, directory: str) -> Database:
        database = Database(Path(directory) / "triage.sqlite3")
        database.init()
        database.upsert_issues(
            [{"issue_id": "cn1", "gt_label": "误触发"}],
            source="test",
            replace_gt=True,
        )
        return database

    def test_comment_thread_is_append_only_and_does_not_version_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.create_annotation(
                issue_id="cn1",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="原始判错原因",
                author="alice",
            )
            before = database.get_case("cn1")["annotations"]
            first = database.create_review_comment(
                issue_id="cn1",
                body="@bob 请看一下",
                author="alice",
                author_verified=True,
                mentions=["bob"],
                notification_recipients=["bob"],
            )
            after = database.get_case("cn1")["annotations"]
            self.assertEqual(len(after), len(before))
            self.assertEqual(first["body"], "@bob 请看一下")
            self.assertEqual(database.review_comment_count(issue_id="cn1"), 1)
            self.assertEqual(database.comment_notification_status()["pending"], 1)

    def test_reply_keeps_parent_context_and_thread_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            parent = database.create_review_comment(
                issue_id="cn1", body="第一条", author="alice"
            )
            reply = database.create_review_comment(
                issue_id="cn1",
                body="@alice 已处理",
                author="bob",
                mentions=["alice"],
                reply_to_id=parent["id"],
            )
            self.assertEqual(reply["reply_to_id"], parent["id"])
            self.assertEqual(reply["reply_to_author"], "alice")
            self.assertEqual(
                [item["id"] for item in database.list_review_comments(issue_id="cn1")],
                [parent["id"], reply["id"]],
            )
            database.upsert_issues(
                [{"issue_id": "cn2", "gt_label": "正确触发"}],
                source="test",
                replace_gt=True,
            )
            with self.assertRaisesRegex(ValueError, "当前 Issue"):
                database.create_review_comment(
                    issue_id="cn2",
                    body="跨线程回复",
                    author="bob",
                    reply_to_id=parent["id"],
                )

    def test_comment_outbox_can_be_claimed_and_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.create_review_comment(
                issue_id="cn1",
                body="@bob 请确认",
                author="alice",
                mentions=["bob"],
                notification_recipients=["bob"],
            )
            claimed = database.claim_comment_notification(
                now="9999-12-31T00:00:00+00:00"
            )
            self.assertEqual(claimed["recipient"], "bob")
            self.assertEqual(claimed["body"], "@bob 请确认")
            database.complete_comment_notification(
                claimed["id"], trace_id="trace", message_unique_id="message"
            )
            self.assertEqual(database.comment_notification_status()["sent"], 1)

    def test_reply_api_notifies_parent_even_without_visible_mention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.set_mention_user(username="alice", enabled=True, actor="admin")
            parent = database.create_review_comment(
                issue_id="cn1", body="请确认这个问题", author="alice"
            )
            dispatcher = Mock()
            with patch(
                "ra_triage_dashboard.app.routers.cases.database", database
            ), patch(
                "ra_triage_dashboard.app.routers.cases._action_actor",
                return_value=("bob", "kylin_ticket", True),
            ), patch(
                "ra_triage_dashboard.app.routers.cases.settings",
                SimpleNamespace(dchat_notifications_enabled=True),
            ), patch(
                "ra_triage_dashboard.app.routers.cases.review_notification_dispatcher",
                dispatcher,
            ):
                result = asyncio.run(
                    create_review_comment(
                        "cn1",
                        json_request(
                            {
                                "body": "我已经处理好了",
                                "reply_to_id": parent["id"],
                            }
                        ),
                    )
                )
            self.assertEqual(result["notification"]["queued"], ["alice"])
            self.assertEqual(result["comment"]["reply_to_author"], "alice")
            dispatcher.wake.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
