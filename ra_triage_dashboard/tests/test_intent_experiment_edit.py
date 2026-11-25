"""Assigned experiments remain editable without losing their evidence."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.intent_experiments import build_intent_experiment_assignments
from ra_triage_dashboard.app.routers import intent_labeling


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "intent.sqlite3")
    db.init()
    db.bootstrap_access_users(writers=["alice", "bob", "carol"], administrators=["manager"])
    cases = [f"case-{index}" for index in range(10)]
    db.create_intent_experiment(
        experiment_id="edit-me", dataset_id="test-v1", name="Existing experiment",
        annotation_mode="blind", label_scope="routing", overlap_ratio=0.2,
        overlap_reviewers=2, case_count=len(cases), seed=42,
        members=["alice", "bob"],
        assignments=build_intent_experiment_assignments(cases, ["alice", "bob"], "blind", 0.2, 42),
        created_by="manager", created_by_source="sso", created_by_verified=True,
    )
    yield db
    db.close()


@pytest.fixture
def client(database):
    def identity(request, capability="view"):
        if capability == "manage" and request.headers.get("x-test-role") == "annotate":
            raise HTTPException(403, "manager required")
        return SimpleNamespace(username="manager", source="sso", verified=True)

    app = FastAPI()
    app.include_router(intent_labeling.router)
    with (
        patch.object(intent_labeling, "database", database),
        patch.object(intent_labeling, "_intent_identity", side_effect=identity),
        TestClient(app) as test_client,
    ):
        yield test_client


def assignment_rows(database):
    with database.connect() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT username, case_id, assignment_kind, ordinal, assigned_at "
            "FROM intent_experiment_assignments WHERE experiment_id = 'edit-me' "
            "ORDER BY username, ordinal, case_id"
        ).fetchall()]


def current(database):
    return database.list_intent_experiments("test-v1")[0]


def update(database, **kwargs):
    return database.update_intent_experiment(
        "edit-me", name="Existing experiment", label_scope="routing",
        updated_by="manager", updated_by_source="sso", updated_by_verified=True, **kwargs,
    )


def test_member_and_overlap_edit_preserves_cases_labels_and_audits(client, database):
    before = assignment_rows(database)
    # The removed member's completed and partial work are also preserved.
    for case_id in ("case-0", "case-1"):
        database.save_intent_labels(
            dataset_id="test-v1", case_id=case_id, author="alice",
            routing_default="straight" if case_id == "case-0" else "",
            lane_change_default="", overrides=[], expected_revision_id=None,
        )
    with database.connect() as conn:
        labels_before = [dict(row) for row in conn.execute("SELECT * FROM intent_label_revisions")]
        heads_before = [dict(row) for row in conn.execute("SELECT * FROM intent_user_label_heads")]
    response = client.patch("/api/intent-experiments/edit-me", json={
        "members": ["bob", "carol"], "overlap_ratio": 0.5, "overlap_reviewers": 2,
        "expected_update_count": 0,
    })
    assert response.status_code == 200, response.text
    experiment = response.json()["experiment"]
    after = assignment_rows(database)
    assert experiment["selected_members"] == ["bob", "carol"]
    assert experiment["assignment_count"] == 15
    assert experiment["overlap_ratio"] == 0.5
    assert experiment["case_count"] == 10
    assert experiment["seed"] == 42
    assert {row["case_id"] for row in before} == {row["case_id"] for row in after}
    assert database.intent_assigned_case_ids("test-v1", ["alice"], "edit-me") == ()
    assert len(database.intent_assigned_case_ids("test-v1", ["bob", "carol"], "edit-me")) == 5
    assert experiment["updates"][0]["allocation_changed"] is True
    assert "assignments" not in experiment["updates"][0]
    with database.connect() as conn:
        assert labels_before == [dict(row) for row in conn.execute("SELECT * FROM intent_label_revisions")]
        assert heads_before == [dict(row) for row in conn.execute("SELECT * FROM intent_user_label_heads")]
        audit = conn.execute("SELECT * FROM intent_experiment_updates").fetchone()
        old = json.loads(audit["old_allocation_json"])
        new = json.loads(audit["new_allocation_json"])
        assert old["assignments"] == before
        assert old["members"] == ["alice", "bob"]
        assert new["members"] == ["bob", "carol"]
        assert sorted(new["assignments"], key=lambda row: (row["username"], row["ordinal"], row["case_id"])) == after
        assert audit["updated_by"] == "manager"
        assert audit["updated_by_verified"]


def test_full_mode_and_single_labeler(client, database):
    full = client.patch("/api/intent-experiments/edit-me", json={
        "members": ["alice", "bob", "carol"], "annotation_mode": "full",
        "overlap_ratio": 0.2, "overlap_reviewers": 2, "expected_update_count": 0,
    })
    assert full.status_code == 200
    assert full.json()["experiment"]["assignment_count"] == 30
    assert full.json()["experiment"]["overlap_ratio"] == 1
    assert full.json()["experiment"]["overlap_reviewers"] == 3
    solo = client.patch("/api/intent-experiments/edit-me", json={
        "members": ["carol"], "annotation_mode": "blind", "overlap_ratio": 0,
        "overlap_reviewers": 1, "expected_update_count": 1,
    })
    assert solo.status_code == 200
    assert solo.json()["experiment"]["assignment_count"] == 10
    assert solo.json()["experiment"]["update_count"] == 2
    assert {row["assignment_kind"] for row in assignment_rows(database)} == {"base"}


def test_noop_and_metadata_edits_do_not_reshuffle(client, database):
    before = assignment_rows(database)
    payload = {
        "members": [" BOB ", "alice", "alice"], "annotation_mode": "blind",
        "overlap_ratio": 0.2, "overlap_reviewers": 2, "expected_update_count": 0,
    }
    assert client.patch("/api/intent-experiments/edit-me", json=payload).status_code == 200
    assert current(database)["update_count"] == 0
    assert assignment_rows(database) == before
    payload.update(name="Renamed experiment", label_scope="lane_change")
    response = client.patch("/api/intent-experiments/edit-me", json=payload)
    assert response.status_code == 200
    assert response.json()["experiment"]["updates"][0]["allocation_changed"] is False
    assert assignment_rows(database) == before


def test_overlap_only_edit_preserves_base_queues(client, database):
    before = [row for row in assignment_rows(database) if row["assignment_kind"] == "base"]
    response = client.patch("/api/intent-experiments/edit-me", json={
        "overlap_ratio": 1, "expected_update_count": 0,
    })
    assert response.status_code == 200
    assert response.json()["experiment"]["assignment_count"] == 20
    after = [row for row in assignment_rows(database) if row["assignment_kind"] == "base"]
    assert [(row["username"], row["case_id"], row["ordinal"]) for row in before] == [
        (row["username"], row["case_id"], row["ordinal"]) for row in after
    ]


def test_revoked_member_does_not_block_metadata_edit_but_blocks_reallocation(client, database):
    body = {"members": ["alice", "bob"], "overlap_ratio": 0.2,
            "overlap_reviewers": 2, "expected_update_count": 0, "name": "Renamed"}
    with patch.object(database, "list_access_users", return_value=[
        {"username": "bob", "intent_permission": "annotate"},
    ]):
        assert client.patch("/api/intent-experiments/edit-me", json=body).status_code == 200
        body.update(overlap_ratio=0.5, expected_update_count=1)
        response = client.patch("/api/intent-experiments/edit-me", json=body)
        assert response.status_code == 400
        assert "标注权限" in response.json()["detail"]
    assert current(database)["update_count"] == 1
    assert current(database)["assignment_count"] == 12


@pytest.mark.parametrize("invalid", [
    {"members": []}, {"members": "alice"}, {"members": [None]},
    {"members": ["unknown"]}, {"overlap_ratio": -0.1}, {"overlap_ratio": 1.1},
    {"overlap_ratio": True}, {"overlap_ratio": "0.5"},
    {"overlap_reviewers": 0}, {"overlap_reviewers": 1.5},
    {"overlap_reviewers": True}, {"overlap_reviewers": 3},
    {"annotation_mode": "invalid"}, {"case_count": 5}, {"dataset_id": "other"},
    {"expected_update_count": True}, {"expected_update_count": -1},
])
def test_invalid_edits_are_atomic(client, database, invalid):
    before = assignment_rows(database)
    response = client.patch("/api/intent-experiments/edit-me", json={
        "name": "Must not be saved", "members": ["alice", "bob"], "expected_update_count": 0,
        **invalid,
    })
    assert response.status_code == 400, response.text
    assert current(database)["name"] == "Existing experiment"
    assert current(database)["update_count"] == 0
    assert assignment_rows(database) == before


def test_stale_closed_missing_and_nonmanager_edits_fail(client, database):
    patch_body = {"members": ["carol"], "overlap_reviewers": 1, "expected_update_count": 0}
    assert client.patch("/api/intent-experiments/edit-me", json=patch_body,
                        headers={"x-test-role": "annotate"}).status_code == 403
    assert client.patch("/api/intent-experiments/missing", json=patch_body).status_code == 404
    assert client.patch("/api/intent-experiments/edit-me",
                        json={"members": ["carol"]}).status_code == 400
    update(database, expected_update_count=0, allocation={
        "members": ["alice", "bob"], "annotation_mode": "full", "overlap_ratio": 1,
        "overlap_reviewers": 2,
    })
    assert client.patch("/api/intent-experiments/edit-me", json=patch_body).status_code == 409
    database.close_intent_experiment("edit-me", closed_by="manager")
    patch_body["expected_update_count"] = 1
    assert client.patch("/api/intent-experiments/edit-me", json=patch_body).status_code == 409
    assert current(database)["assignment_count"] == 20
    assert current(database)["update_count"] == 1


def test_assignment_failure_rolls_back_config_and_audit(database):
    before = assignment_rows(database)
    with database.connect() as conn:
        conn.execute(
            "CREATE TRIGGER reject_test_assignment BEFORE INSERT ON intent_experiment_assignments "
            "BEGIN SELECT RAISE(ABORT, 'injected assignment failure'); END"
        )
    with pytest.raises(Exception, match="injected assignment failure"):
        update(database, expected_update_count=0, allocation={
            "members": ["carol"], "annotation_mode": "blind", "overlap_ratio": 0,
            "overlap_reviewers": 1,
        })
    assert assignment_rows(database) == before
    assert current(database)["selected_members"] == ["alice", "bob"]
    assert current(database)["update_count"] == 0


def test_concurrent_edit_has_one_winner_across_database_instances(database):
    other = Database(database.path)
    def apply(db, member):
        try:
            update(db, expected_update_count=0, allocation={
                "members": [member], "annotation_mode": "blind", "overlap_ratio": 0,
                "overlap_reviewers": 1,
            })
            return "saved"
        except ValueError as exc:
            assert "已被其他人修改" in str(exc)
            return "conflict"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda args: apply(*args), [(database, "alice"), (other, "bob")]))
        assert sorted(results) == ["conflict", "saved"]
        assert current(database)["update_count"] == 1
        assert current(database)["assignment_count"] == 10
    finally:
        other.close()


def test_zero_work_members_and_legacy_members_are_preserved(database):
    # Legacy rows derive members from their assignments.
    with database.connect() as conn:
        conn.execute("UPDATE intent_experiments SET members_json = '[]'")
    assert current(database)["selected_members"] == ["alice", "bob"]
    members = [f"member-{index:02}" for index in range(11)]
    result = update(database, allocation={
        "members": members, "annotation_mode": "blind", "overlap_ratio": 0,
        "overlap_reviewers": 1,
    }, expected_update_count=0)
    assert result["selected_members"] == members
    assert result["member_count"] == 11
    assert len([member for member in result["members"] if member["total"] == 0]) == 1
    database.init()
    assert current(database)["selected_members"] == members
