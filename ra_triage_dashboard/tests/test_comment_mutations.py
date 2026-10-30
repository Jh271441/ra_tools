from __future__ import annotations

import asyncio
import json as json_module
import os
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from ra_triage_dashboard.app.auth import SessionIdentity
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.comment_mutations import CommentConflictError
from ra_triage_dashboard.app.routers import case_comments, comment_mutations
from ra_triage_dashboard.app.support import identity


class AsgiClient:
    """Exercise the actual routes without an optional HTTP client dependency."""
    def __init__(self, app):
        self.app = app

    def request(self, method, path, *, json=None, headers=None):
        body = json_module.dumps(json).encode() if json is not None else b""
        async def invoke():
            messages = []
            consumed = False
            async def receive():
                nonlocal consumed
                if consumed:
                    return {"type": "http.disconnect"}
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            async def send(message):
                messages.append(message)
            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
                "scheme": "http", "server": ("test", 80), "client": ("127.0.0.1", 12345),
                "headers": [(b"content-type", b"application/json"), *[(k.encode(), v.encode()) for k, v in (headers or {}).items()]]}, receive, send)
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            text = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body").decode()
            return SimpleNamespace(status_code=status, text=text, json=lambda: json_module.loads(text))
        return asyncio.run(invoke())

    def patch(self, path, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)


@pytest.fixture
def fixture(tmp_path):
    db = Database(tmp_path / "comments.sqlite3")
    db.init()
    db.upsert_issues([{"issue_id": "cn1"}, {"issue_id": "cn2"}], source="test", baseline_scope="scope", replace_gt=False)
    for name, role, permission in [("alice", "writer", "annotate"), ("bob", "writer", "annotate"), ("admin", "admin", "manage"), ("viewer", "writer", "view")]:
        db.set_access_user(username=name, role=role, intent_permission=permission, actor="fixture")
    app = FastAPI()
    app.include_router(comment_mutations.router)
    app.include_router(case_comments.router)
    def resolve(request, settings):
        name = request.headers.get("x-test-actor", "alice")
        return SessionIdentity(username=name, source="test-sso", verified=request.headers.get("x-test-verified", "1") == "1")
    with ExitStack() as stack:
        stack.enter_context(patch.object(identity, "request_identity", resolve))
        stack.enter_context(patch.object(identity, "database", db))
        stack.enter_context(patch.object(comment_mutations, "database", db))
        stack.enter_context(patch.object(case_comments, "database", db))
        stack.enter_context(patch.object(comment_mutations, "intent_dataset_registry", SimpleNamespace(has_case=lambda ds, case: ds == "intent1" and case == "cn1")))
        yield db, AsgiClient(app)
    db.close()


def create(db, kind="review", *, body="original", author="alice", verified=True, parent=None, recipients=None):
    if kind == "intent":
        return db.create_intent_comment(dataset_id="intent1", case_id="cn1", body=body,
            author=author, author_source="test-sso", author_verified=verified,
            reply_to_id=parent, notification_recipients=recipients)
    return db.create_review_comment(issue_id="cn1", body=body, author=author,
        author_source="test-sso", author_verified=verified, discussion_channel="case",
        baseline_scope="scope", require_existing_model_run=False, reply_to_id=parent,
        notification_recipients=recipients)


def url(comment, kind="review"):
    prefix = "/api/cases/cn1" if kind == "review" else "/api/intent-datasets/intent1/cases/cn1"
    return f"{prefix}/comments/{comment['id']}"


@pytest.mark.parametrize("kind", ["review", "intent"])
def test_edit_delete_history_parent_and_notifications(fixture, kind):
    db, client = fixture
    parent = create(db, kind, recipients=["bob"])
    reply = create(db, kind, body="reply remains", author="bob", parent=parent["id"])
    before = db.change_revision()
    response = client.patch(url(parent, kind), json={"expected_version": 1, "body": "edited @bob"})
    assert response.status_code == 200, response.text
    edited = response.json()["comment"]
    assert edited["body"] == "edited @bob" and edited["version"] == 2 and edited["edited_at"]
    assert edited["author"] == "alice" and response.json()["notification"]["queued"] == []
    assert db.change_revision() > before
    stale = client.patch(url(parent, kind), json={"expected_version": 1, "body": "lost update"})
    assert stale.status_code == 409
    assert client.request("DELETE", url(parent, kind), json={"expected_version": 2}).status_code == 200
    comments = db.list_review_comments(issue_id="cn1", discussion_channel="case", baseline_scope="scope") if kind == "review" else db.list_intent_comments("intent1", "cn1")
    deleted = next(x for x in comments if x["id"] == parent["id"])
    child = next(x for x in comments if x["id"] == reply["id"])
    assert deleted["deleted"] and deleted["body"] == "" and deleted["mentions"] == [] and deleted["version"] == 3
    assert child["body"] == "reply remains" and child["reply_to_body"] == "" and child["reply_to_deleted"]
    history = client.get(url(parent, kind) + "/history").json()["items"]
    assert [(x["action"], x["body_before"], x["body_after"]) for x in history] == [("edit", "original", "edited @bob"), ("delete", "edited @bob", "")]
    assert all(x["actor"] == "alice" and x["actor_verified"] for x in history)
    outbox = "comment_notifications" if kind == "review" else "intent_comment_notifications"
    with db.connect() as conn:
        notices = conn.execute(f"SELECT recipient, status FROM {outbox} WHERE comment_id = ?", (parent["id"],)).fetchall()
    assert [(x["recipient"], x["status"]) for x in notices] == [("bob", "failed")]
    assert client.request("DELETE", url(parent, kind), json={"expected_version": 3}).status_code == 409
    with pytest.raises(ValueError):
        create(db, kind, body="reply to deleted", parent=parent["id"])


@pytest.mark.parametrize("kind", ["review", "intent"])
def test_author_admin_and_verified_identity_are_enforced(fixture, kind):
    db, client = fixture
    comment = create(db, kind)
    payload = {"expected_version": 1, "body": "changed", "author": "alice", "is_admin": True}
    assert client.patch(url(comment, kind), json=payload, headers={"x-test-actor": "bob"}).status_code == 403
    assert client.get(url(comment, kind) + "/history", headers={"x-test-actor": "bob"}).status_code == 403
    assert client.patch(url(comment, kind), json=payload, headers={"x-test-verified": "0"}).status_code == 403
    result = client.patch(url(comment, kind), json=payload, headers={"x-test-actor": "admin"})
    assert result.status_code == 200 and result.json()["comment"]["author"] == "alice"
    audit = client.get(url(comment, kind) + "/history").json()["items"]
    assert audit[0]["actor"] == "admin"
    legacy = create(db, kind, verified=False)
    assert client.patch(url(legacy, kind), json=payload).status_code == 403
    assert client.patch(url(legacy, kind), json=payload, headers={"x-test-actor": "admin"}).status_code == 200


def test_intent_capability_and_cross_scope_checks(fixture):
    db, client = fixture
    comment = create(db, "intent")
    payload = {"expected_version": 1, "body": "changed"}
    assert client.patch(url(comment, "intent"), json=payload, headers={"x-test-actor": "viewer"}).status_code == 403
    assert client.patch(url(comment, "intent").replace("intent1", "intent2"), json=payload).status_code == 404
    normal = create(db)
    assert client.patch(url(normal).replace("cn1", "cn2"), json=payload).status_code == 404


@pytest.mark.parametrize("body,version", [("", 1), ("x" * 3501, 1), ("valid", None), ("valid", True), ("valid", "1"), ("@unknown invalid", 1), (123, 1), (["text"], 1), ({"text": "body"}, 1)])
def test_reject_invalid_updates_without_mutation(fixture, body, version):
    db, client = fixture
    comment = create(db)
    assert client.patch(url(comment), json={"expected_version": version, "body": body}).status_code == 400
    assert db.get_review_comment(comment["id"])["body"] == "original"


def test_label_evidence_and_historical_discussion_are_read_only(fixture):
    db, client = fixture
    comment = create(db, body="Issue 标签 #42 · 标注依据 / Label rationale\nimmutable evidence")
    payload = {"expected_version": 1, "body": "changed"}
    assert client.patch(url(comment), json=payload, headers={"x-test-actor": "admin"}).status_code == 409
    assert client.request("DELETE", url(comment), json=payload, headers={"x-test-actor": "admin"}).status_code == 409
    plain = create(db)
    with db.connect() as conn:
        conn.execute("UPDATE review_comments SET discussion_channel = 'legacy' WHERE id = ?", (plain["id"],))
    assert client.patch(url(plain), json=payload).status_code == 409


def test_attachment_is_not_exposed_after_delete_and_foreign_token_is_rejected(fixture):
    db, client = fixture
    comment = db.create_review_comment(issue_id="cn1", body="![test](attachment:image-own)", author="alice", author_source="test-sso", author_verified=True,
        discussion_channel="case", baseline_scope="scope", require_existing_model_run=False,
        attachments=[dict(id="image-own",original_name="a.png",stored_name="a.png",media_type="image/png",size_bytes=1,width=1,height=1,sha256="a"*64)])
    assert db.get_comment_attachment("image-own")
    assert client.patch(url(comment), json={"expected_version": 1, "body": "![foreign](attachment:image-other)"}).status_code == 400
    assert client.request("DELETE", url(comment), json={"expected_version": 1}).json()["comment"]["attachments"] == []
    assert db.get_comment_attachment("image-own") is None
    assert client.get("/api/comment-attachments/image-own").status_code == 404


def test_compare_and_swap_keeps_one_change_under_competing_saves(fixture):
    db, _ = fixture
    comment = create(db)
    def save(text):
        try:
            db.mutate_comment(kind="review", comment_id=comment["id"], issue_id="cn1", actor="alice", actor_source="test-sso", actor_verified=True, is_admin=False, expected_version=1, body=text)
            return "saved"
        except CommentConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["first", "second"]))
    assert sorted(results) == ["conflict", "saved"]
    history = db.comment_change_history(kind="review",comment_id=comment["id"],issue_id="cn1",actor="alice",actor_verified=True,is_admin=False)
    assert len(history) == 1


def test_model_review_empty_scope_and_noop(fixture):
    db, client = fixture
    comment = db.create_review_comment(issue_id="cn1", model_run_id="fixture-run", body="model discussion",
        author="alice", author_verified=True, require_existing_model_run=False)
    response = client.patch(url(comment), json={"expected_version": 1, "body": "updated model discussion"})
    assert response.status_code == 200, response.text
    response = client.patch(url(comment), json={"expected_version": 2, "body": "updated model discussion"})
    assert response.json()["comment"]["version"] == 2
    assert len(client.get(url(comment) + "/history").json()["items"]) == 1


@pytest.mark.parametrize("kind", ["review", "intent"])
def test_recovered_inflight_notifications_do_not_deliver_changed_text(fixture, kind):
    db, client = fixture
    comment = create(db, kind, recipients=["bob"])
    claim = db.claim_comment_notification if kind == "review" else db.claim_intent_comment_notification
    recover = db.recover_comment_notifications if kind == "review" else db.recover_intent_comment_notifications
    assert claim(now="2099-01-01T00:00:00+00:00")
    assert client.patch(url(comment, kind), json={"expected_version": 1, "body": "changed @bob"}).status_code == 200
    assert recover() == 1
    assert claim(now="2099-01-01T00:00:00+00:00") is None
    outbox = "comment_notifications" if kind == "review" else "intent_comment_notifications"
    with db.connect() as conn:
        assert conn.execute(f"SELECT status FROM {outbox} WHERE comment_id = ?", (comment["id"],)).fetchone()["status"] == "failed"


@pytest.mark.skipif(not os.getenv("DASHBOARD_TEST_POSTGRES_URL", "").startswith("postgresql://"), reason="requires an empty disposable PostgreSQL database")
def test_postgres_comment_migration_and_cross_connection_cas(tmp_path):
    options = dict(postgres_migrations_dir=Path(__file__).resolve().parents[1] / "migrations" / "postgres", pool_size=3)
    db = Database(os.environ["DASHBOARD_TEST_POSTGRES_URL"], **options)
    other = Database(os.environ["DASHBOARD_TEST_POSTGRES_URL"], **options)
    try:
        legacy_dir = tmp_path / "migrations58"
        legacy_dir.mkdir()
        for migration in options["postgres_migrations_dir"].glob("*.sql"):
            if not migration.name.startswith("059_"):
                (legacy_dir / migration.name).symlink_to(migration)
        legacy = Database(os.environ["DASHBOARD_TEST_POSTGRES_URL"], postgres_migrations_dir=legacy_dir)
        try:
            legacy._apply_postgres_migrations()
            legacy_issue = "legacy_comment_pg_" + uuid4().hex
            legacy.upsert_issues([{"issue_id": legacy_issue}], source="isolated-test", baseline_scope="comment-pg", replace_gt=False)
            with legacy.connect() as conn:
                assert conn.execute("SELECT COUNT(*) AS n FROM dashboard_schema_migrations").fetchone()["n"] == 58
                old_id = conn.execute("INSERT INTO review_comments (issue_id,body,author,author_verified,discussion_channel,baseline_scope) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                    (legacy_issue,"Existing human comment","alice",True,"case","comment-pg")).fetchone()["id"]
                old_comment = dict(conn.execute("SELECT * FROM review_comments WHERE id = ?", (old_id,)).fetchone())
        finally:
            legacy.close()
        db.init()
        other.init()
        with db.connect() as conn:
            upgraded = dict(conn.execute("SELECT * FROM review_comments WHERE id = ?", (old_id,)).fetchone())
            assert {key:upgraded[key] for key in old_comment} == old_comment
            assert upgraded["version"] == 1 and upgraded["deleted_at"] is None
            assert conn.execute("SELECT COUNT(*) AS n FROM dashboard_schema_migrations").fetchone()["n"] == 59
        issue = "comment_pg_" + uuid4().hex
        db.upsert_issues([{"issue_id": issue}], source="isolated-comment-test", baseline_scope="comment-pg", replace_gt=False)
        parent = db.create_review_comment(issue_id=issue, body="original", author="alice", author_verified=True,
            discussion_channel="case", baseline_scope="comment-pg", require_existing_model_run=False, notification_recipients=["bob"])
        reply = db.create_review_comment(issue_id=issue, body="reply", author="bob", author_verified=True,
            discussion_channel="case", baseline_scope="comment-pg", require_existing_model_run=False, reply_to_id=parent["id"])
        before = db.change_revision()
        def save(pair):
            database, text = pair
            try:
                database.mutate_comment(kind="review", comment_id=parent["id"], issue_id=issue,
                    actor="alice", actor_source="test-sso", actor_verified=True, is_admin=False, expected_version=1, body=text)
                return "saved"
            except CommentConflictError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(save, [(db, "first"), (other, "second")])) == ["conflict", "saved"]
        assert db.change_revision() > before
        other.mutate_comment(kind="review", comment_id=parent["id"], issue_id=issue, actor="alice", actor_source="test-sso",
            actor_verified=True, is_admin=False, expected_version=2, delete=True)
        assert db.get_review_comment(reply["id"])["reply_to_deleted"]
        assert len(db.comment_change_history(kind="review", comment_id=parent["id"], issue_id=issue,
            actor="alice", actor_verified=True, is_admin=False)) == 2
        intent = db.create_intent_comment(dataset_id="comment-pg", case_id=issue, body="intent original", author="alice", author_source="test-sso", author_verified=True)
        other.mutate_comment(kind="intent", comment_id=intent["id"], issue_id=issue, dataset_id="comment-pg", actor="alice",
            actor_source="test-sso", actor_verified=True, is_admin=False, expected_version=1, body="intent updated")
        assert db.get_intent_comment("comment-pg", issue, intent["id"])["version"] == 2
    finally:
        other.close()
        db.close()
