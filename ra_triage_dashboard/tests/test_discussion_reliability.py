"""Historical evidence and retry receipts; disposable data, no DChat sends."""
import asyncio
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ra_triage_dashboard.app.comment_submission import comment_request_fingerprint, CommentSubmissionConflictError
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import case_comments
from ra_triage_dashboard.app.routers.case_comments import _public_review_comment
from test_comment_mutations import fixture  # noqa: F401 - shared disposable ASGI fixture


def image(key="historical-image"):
    return {"id": key, "original_name": "evidence.png", "stored_name": key + ".png",
            "media_type": "image/png", "size_bytes": 100, "width": 1200, "height": 800,
            "sha256": "a" * 64}


def label(db, *, previous=None, key="historical-image"):
    return db.create_label_revision(issue_id="cn1", expected_output="误触发", tags=[], evidence_gaps=[],
        rationale="Historical rationale @bob", is_excluded=False, author="alice", author_source="test-sso",
        author_verified=True, expected_previous_revision_id=previous, attachments=[image(key)], mention_recipients=["bob"])


def test_label_comment_shows_exact_historical_images_without_copying_files(fixture):
    db, client = fixture
    first = label(db)
    second = label(db, previous=first["id"], key="newer-image")
    before = db.change_revision()
    result = client.get("/api/cases/cn1/discussion").json()
    roots = {comment["id"]: comment for comment in result["comments"]}
    for revision, key in [(first, "historical-image"), (second, "newer-image")]:
        comment = roots[revision["notification"]["comment_id"]]
        assert [item["id"] for item in comment["attachments"]] == [key]
        assert comment["attachments"][0]["url"].endswith("/api/labeling/attachments/" + key)
        assert "stored_name" not in comment["attachments"][0]
    assert db.change_revision() == before
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM comment_attachments").fetchone()["n"] == 0


@pytest.mark.parametrize("field,value", [("author", "bob"), ("author_source", "other"),
    ("created_at", "2099-01-01T00:00:00+00:00"), ("body", "changed"),
    ("baseline_scope", "other"), ("issue_id", "cn2"), ("author_verified", False)])
def test_label_image_binding_rejects_spoofed_revision_references(fixture, field, value):
    db, _ = fixture
    revision = label(db)
    root = db.get_review_comment(revision["notification"]["comment_id"])
    assert root["attachments"]
    with db.connect() as conn:
        conn.execute(f"UPDATE review_comments SET {field}=? WHERE id=?", (value, root["id"]))
    assert db.get_review_comment(root["id"])["attachments"] == []


def submission(db, *, key="request-0001", text="Reply @bob", author="alice", attachments=()):
    return db.create_review_comment(issue_id="cn1", body=text, author=author, author_source="test-sso",
        author_verified=True, unified_issue_discussion=True, notification_recipients=["bob"],
        client_request_id=key, request_fingerprint=comment_request_fingerprint(text, None, attachments),
        attachments=list(attachments))


def test_same_request_after_reconnect_creates_one_comment_and_one_outbox(fixture):
    db, _ = fixture
    first = submission(db)
    before = db.change_revision()
    retry = submission(db)
    assert retry["id"] == first["id"] and retry["_replayed"]
    assert db.change_revision() == before
    assert db.issue_discussion_count("cn1") == 1
    assert db.comment_notification_status()["pending"] == 1
    assert db.get_comment_submission(issue_id="cn1", author="alice", request_id="request-0001")["id"] == first["id"]
    assert db.get_comment_submission(issue_id="cn1", author="bob", request_id="request-0001") is None
    with pytest.raises(CommentSubmissionConflictError):
        submission(db, text="Changed content")
    assert submission(db, author="bob")["id"] != first["id"]


def test_concurrent_workers_share_the_same_persisted_receipt(fixture):
    db, _ = fixture
    other = Database(db.path)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda worker: submission(worker), [db, other]))
        assert len({item["id"] for item in results}) == 1
        assert db.issue_discussion_count("cn1") == 1
        assert db.comment_notification_status()["pending"] == 1
    finally:
        other.close()


def test_retry_receipt_survives_edit_and_delete_without_resurrection(fixture):
    db, _ = fixture
    first = submission(db)
    db.mutate_comment(kind="review", comment_id=first["id"], issue_id="cn1", actor="alice",
        actor_source="test-sso", actor_verified=True, is_admin=False, expected_version=1, delete=True)
    retry = submission(db)
    assert retry["id"] == first["id"] and retry["deleted"] and not retry["body"]
    assert db.issue_discussion_count("cn1") == 1


def test_api_receipt_requires_same_verified_actor_and_rejects_conflicts(fixture):
    db, client = fixture
    dispatcher = Mock()
    headers = {"idempotency-key": "request-api-0001"}
    with patch.object(case_comments, "settings", SimpleNamespace(dchat_notifications_enabled=True)), \
         patch.object(case_comments, "review_notification_dispatcher", dispatcher):
        first = client.request("POST", "/api/cases/cn1/discussion", json={"body": "Hello"}, headers=headers)
        assert first.status_code == 200, first.text
        retry = client.request("POST", "/api/cases/cn1/discussion", json={"body": "Hello"}, headers=headers)
        assert retry.status_code == 200 and retry.json()["idempotent_replay"]
        assert first.json()["comment"]["id"] == retry.json()["comment"]["id"]
        changed = client.request("POST", "/api/cases/cn1/discussion", json={"body": "different"}, headers=headers)
        assert changed.status_code == 409
    path = "/api/cases/cn1/discussion-submissions/request-api-0001"
    assert client.get(path).json()["comment"]["id"] == first.json()["comment"]["id"]
    assert client.get(path, headers={"x-test-actor": "bob"}).status_code == 404
    assert client.get(path, headers={"x-test-verified": "0"}).status_code == 403
    assert client.get(path.replace("cn1", "cn2")).status_code == 404
    assert client.get(path.replace("request-api-0001", "bad")).status_code == 400
    assert db.issue_discussion_count("cn1") == 1


def test_upload_replay_uses_content_hash_and_removes_only_uncommitted_duplicate_files(fixture, tmp_path):
    db, _ = fixture
    from starlette.requests import Request
    request = Request({"type": "http", "method": "POST", "path": "/api/cases/cn1/discussion-with-attachments",
        "headers": [(b"idempotency-key", b"request-image-0001")]})
    paths = [tmp_path / "first.png", tmp_path / "retry.png"]
    for path in paths:
        path.write_bytes(b"synthetic-image")
    records = [image("first-image"), image("retry-image")]
    async def store(_):
        index = store.calls
        store.calls += 1
        return [records[index]], [paths[index]]
    store.calls = 0
    with patch.object(case_comments, "_store_comment_attachments", side_effect=store), \
         patch.object(case_comments, "settings", SimpleNamespace(dchat_notifications_enabled=False)):
        payload = json.dumps({"body": "![image](attachment:pending-image)", "attachment_tokens": ["pending-image"]})
        first = asyncio.run(case_comments._create_comment_with_attachments("cn1", request, payload, [object()], issue_discussion=True))
        retry = asyncio.run(case_comments._create_comment_with_attachments("cn1", request, payload, [object()], issue_discussion=True))
    assert first["comment"]["id"] == retry["comment"]["id"] and retry["idempotent_replay"]
    assert paths[0].exists() and not paths[1].exists()
    assert [item["id"] for item in retry["comment"]["attachments"]] == ["first-image"]


@pytest.mark.skipif(not os.getenv("DASHBOARD_TEST_POSTGRES_URL", "").startswith("postgresql://"), reason="requires an empty disposable PostgreSQL database")
def test_postgres_submission_lock_and_historical_image_binding():
    options = {"postgres_migrations_dir": Path(__file__).resolve().parents[1] / "migrations" / "postgres", "pool_size": 2}
    db = Database(os.environ["DASHBOARD_TEST_POSTGRES_URL"], **options)
    other = Database(os.environ["DASHBOARD_TEST_POSTGRES_URL"], **options)
    try:
        db.init()
        db.upsert_issues([{"issue_id": "cn1"}], source="disposable-test", baseline_scope="scope", replace_gt=False)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda worker: submission(worker), [db, other]))
        assert len({item["id"] for item in results}) == 1
        assert db.issue_discussion_count("cn1") == 1
        with db.connect() as conn:
            assert conn.execute("SELECT count(*) n FROM comment_notifications WHERE comment_id=?", (results[0]["id"],)).fetchone()["n"] == 1
        # PostgreSQL attachment IDs use uuid; SQLite fixtures also permit text.
        attachment_id = "e6d949b4-799e-4e55-86d3-5bb80f7343c9"
        revision = label(db, key=attachment_id)
        root = db.get_review_comment(revision["notification"]["comment_id"])
        assert [item["id"] for item in root["attachments"]] == [attachment_id]
        assert _public_review_comment(root)["attachments"][0]["url"].endswith("/api/labeling/attachments/" + attachment_id)
    finally:
        db.close()
        other.close()
