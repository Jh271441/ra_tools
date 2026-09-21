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
from ra_triage_dashboard.app.routers.case_comments import (
    create_review_comment,
    create_review_comment_with_attachments,
)


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
        run, _ = database.import_model_run(
            name="comment test run",
            source_name="comment-test.json",
            source_sha256="d" * 64,
            metadata={},
            rows=[{"issue_id": "cn1", "model_label": "误触发"}],
        )
        self.model_run_id = str(run["id"])
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

    def test_gallery_filters_cases_by_discussion_state_and_selected_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.upsert_issues(
                [
                    {"issue_id": "cn2", "gt_label": "正确触发"},
                    {"issue_id": "cn3", "gt_label": "无需协助"},
                ],
                source="test",
                replace_gt=True,
            )
            run, _ = database.import_model_run(
                name="discussion-run",
                source_name="discussion.json",
                source_sha256="d" * 64,
                metadata={},
                rows=[{"issue_id": "cn1", "model_label": "误触发"}],
            )
            database.create_review_comment(
                issue_id="cn1",
                model_run_id=run["id"],
                body="Run A 讨论",
                author="alice",
            )
            database.create_review_comment(
                issue_id="cn2", body="未绑定讨论", author="bob"
            )

            any_run = database.list_cases(comment_state="with", page_size=20)
            run_a = database.list_cases(
                model_run_id=run["id"], comment_state="with", page_size=20
            )
            without_run_a = database.list_cases(
                model_run_id=run["id"], comment_state="without", page_size=20
            )

            self.assertEqual(
                [item["issue_id"] for item in any_run["items"]], ["cn1", "cn2"]
            )
            self.assertEqual(
                [item["issue_id"] for item in run_a["items"]], ["cn1"]
            )
            self.assertEqual(
                [item["issue_id"] for item in without_run_a["items"]],
                ["cn2", "cn3"],
            )
            with self.assertRaisesRegex(ValueError, "unsupported comment_state"):
                database.list_cases(comment_state="broken")

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
                issue_id="cn1", model_run_id=self.model_run_id,
                body="请确认这个问题", author="alice"
            )
            dispatcher = Mock()
            with patch(
                "ra_triage_dashboard.app.routers.case_comments.database", database
            ), patch(
                "ra_triage_dashboard.app.routers.case_comments._action_actor",
                return_value=("bob", "kylin_ticket", True),
            ), patch(
                "ra_triage_dashboard.app.routers.case_comments.settings",
                SimpleNamespace(dchat_notifications_enabled=True),
            ), patch(
                "ra_triage_dashboard.app.routers.case_comments.review_notification_dispatcher",
                dispatcher,
            ):
                result = asyncio.run(
                    create_review_comment(
                        "cn1",
                        json_request(
                            {
                                "model_run_id": self.model_run_id,
                                "body": "我已经处理好了",
                                "reply_to_id": parent["id"],
                            }
                        ),
                    )
                )
            self.assertEqual(result["notification"]["queued"], ["alice"])
            self.assertEqual(result["comment"]["reply_to_author"], "alice")
            dispatcher.wake.assert_called_once_with()

    def test_mention_directory_exposes_human_display_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.set_mention_user(
                username="jasperchen",
                display_name="陈俊豪",
                enabled=True,
                actor="admin",
            )
            item = next(
                entry for entry in database.list_mention_users()
                if entry["username"] == "jasperchen"
            )
            self.assertEqual(item["display_name"], "陈俊豪")
            self.assertEqual(
                database.mention_display_names(["jasperchen"]),
                {"jasperchen": "陈俊豪"},
            )

    def test_bootstrap_directory_includes_liangxianghui_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            database.set_access_user(
                username="liangxianghui", role="writer", actor="admin"
            )
            database.bootstrap_mention_users()
            item = next(
                entry
                for entry in database.list_mention_users()
                if entry["username"] == "liangxianghui"
            )
            self.assertEqual(item["display_name"], "梁祥辉")

    def test_comment_attachments_are_scoped_to_the_created_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            comment = database.create_review_comment(
                issue_id="cn1",
                body="![现场图](attachment:image-1)",
                author="alice",
                attachments=[
                    {
                        "id": "image-1",
                        "original_name": "scene.png",
                        "stored_name": "im/image-1.png",
                        "media_type": "image/png",
                        "size_bytes": 16,
                        "width": 10,
                        "height": 8,
                        "sha256": "a" * 64,
                    }
                ],
            )
            self.assertEqual(comment["attachments"][0]["id"], "image-1")
            listed = database.list_review_comments(issue_id="cn1")
            self.assertEqual(listed[0]["attachments"][0]["stored_name"], "im/image-1.png")
            self.assertEqual(database.get_comment_attachment("image-1")["comment_id"], comment["id"])
            self.assertEqual(database.image_attachment_storage_bytes(), 16)

    def test_multipart_comment_replaces_image_tokens_without_review_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            dispatcher = Mock()
            stored = {
                "id": "image-1",
                "original_name": "scene.png",
                "stored_name": "im/image-1.png",
                "media_type": "image/png",
                "size_bytes": 16,
                "width": 10,
                "height": 8,
                "sha256": "a" * 64,
            }
            request = json_request({"model_run_id": self.model_run_id})
            with patch(
                "ra_triage_dashboard.app.routers.case_comments.database", database
            ), patch(
                "ra_triage_dashboard.app.routers.case_comments._action_actor",
                return_value=("alice", "kylin_ticket", True),
            ), patch(
                "ra_triage_dashboard.app.routers.case_comments.settings",
                SimpleNamespace(dchat_notifications_enabled=False),
            ), patch(
                "ra_triage_dashboard.app.routers.case_comments.review_notification_dispatcher",
                dispatcher,
            ), patch(
                "ra_triage_dashboard.app.routers.case_comments._store_comment_attachments",
                return_value=([stored], [Path(directory) / "image-1.png"]),
            ):
                result = asyncio.run(
                    create_review_comment_with_attachments(
                        "cn1",
                        request,
                        payload=json.dumps(
                            {
                                "model_run_id": self.model_run_id,
                                "body": "![现场图](attachment:pending-1)",
                                "attachment_tokens": ["pending-1"],
                            }
                        ),
                        attachments=[Mock()],
                    )
                )
            self.assertEqual(
                result["comment"]["body"], "![现场图](attachment:image-1)"
            )
            self.assertEqual(
                result["comment"]["attachments"][0]["url"],
                "/api/comment-attachments/image-1",
            )
            self.assertEqual(database.get_case("cn1")["annotations"], [])


if __name__ == "__main__":
    unittest.main()
