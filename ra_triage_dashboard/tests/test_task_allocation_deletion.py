"""Deletion removes current work while retaining evidence and coverage."""
import sqlite3
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ra_triage_dashboard.app.db_parts.campaigns import CampaignConflictError
from ra_triage_dashboard.app.routers import campaigns
from ra_triage_dashboard.app.version_review_tasks import version_tasks, version_task_detail
from ra_triage_dashboard.tests.test_task_allocation import fixture, snapshot, role_db, choose, submit
from ra_triage_dashboard.tests.test_task_reallocation import make_task, save_label, request, apply

EVIDENCE = ["label_revisions", "model_review_revisions", "combined_review_progress",
            "human_vote_roles", "review_worksets", "review_workset_items",
            "model_predictions", "campaign_reference_items"]


def removal(db, cid, person="alice", basis="remaining"):
    return dict(campaign_id=cid, assignee=person, quota_basis=basis,
                expected_revision=db.get_campaign_allocation(cid)["expected_revision"])


@pytest.mark.parametrize("purpose", ["labeling", "model_review"])
@pytest.mark.parametrize("basis", ["remaining", "total"])
def test_member_removal_retains_completed_and_partial_work(fixture, purpose, basis):
    db = fixture.db
    cid, ids = make_task(fixture, count=40, completed=5, purpose=purpose)
    if purpose == "labeling":
        save_label(db, cid, ids[5], output="")
    else:
        task = db.get_campaign(cid)["campaign"]
        db.create_model_review(issue_id=ids[5], model_run_id=task["evaluation_run_id"],
            campaign_id=cid, reviewer="alice", status="pending", reason="saved draft", missing_evidence=[])
    before = snapshot(db, EVIDENCE)
    body = removal(db, cid, basis=basis)
    preview = db.preview_campaign_member_removal(**body)
    own = next(p for p in preview["members"] if p["name"] == "alice")
    assert (own["completed"], own["saved_pending"], own["total_after"]) == (5, 1, 6)
    assert own["outgoing"] == 4
    result = db.delete_campaign_allocation_member(**body, preview_token=preview["preview_token"],
        actor="alice", idempotency_key="remove")
    assert result["preview"]["removed_assignee"] == "alice"
    config = db.get_campaign_allocation(cid)
    assert config["assignment_counts"]["alice"] == 6
    assert "alice" not in {p["name"] for p in config["assignees"]}
    assert config["total_slots"] == 40 and config["member_count"] == 40
    assert snapshot(db, EVIDENCE) == before
    assert db.get_campaign(cid)["campaign"]["lifecycle"] == "active"
    assert db.delete_campaign_allocation_member(**body, preview_token=preview["preview_token"],
        actor="alice", idempotency_key="remove")["replayed"]
    assert snapshot(db, EVIDENCE) == before


def test_removal_normalizes_saved_shares_and_stale_preview_cannot_write(fixture):
    db = fixture.db
    cid, ids = make_task(fixture, count=40, completed=5)
    body = request(db, cid, names=("alice", "bob", "c", "d"))
    body["assignees"] = [dict(name=p, review_percent=n) for p, n in
                         [("alice", 10), ("bob", 20), ("c", 30), ("d", 40)]]
    apply(db, body)
    remove = removal(db, cid)
    preview = db.preview_campaign_member_removal(**remove)
    with db.connect() as conn:
        pending = conn.execute("SELECT issue_id FROM review_work_assignments WHERE split_id=? AND assignee='bob' LIMIT 1", (cid,)).fetchone()
    save_label(db, cid, pending["issue_id"], author="bob")
    before = snapshot(db, [*EVIDENCE, "review_work_assignments", "campaign_config_revisions"])
    with pytest.raises(CampaignConflictError, match="preview again"):
        db.delete_campaign_allocation_member(**remove, preview_token=preview["preview_token"],
            actor="alice", idempotency_key="stale")
    assert snapshot(db, list(before)) == before
    preview = db.preview_campaign_member_removal(**remove)
    db.delete_campaign_allocation_member(**remove, preview_token=preview["preview_token"],
        actor="alice", idempotency_key="fresh")
    shares = {p["name"]: p["review_percent"] for p in db.get_campaign_allocation(cid)["assignees"]}
    assert shares == {"bob": 22.22, "c": 33.33, "d": 44.45}


def test_removal_rejects_missing_recipient_and_broken_cross_coverage(fixture):
    db = fixture.db
    task = fixture.campaign(0, assignees=["alice", "bob"])
    fixture.submit(task, db.combined_review_context(issue_id="cn1", campaign_id=task["id"], reviewer="alice"))
    before = snapshot(db, [*EVIDENCE, "review_work_assignments", "campaign_config_revisions"])
    with pytest.raises(ValueError):
        db.preview_campaign_member_removal(**removal(db, task["id"], "bob"))
    with pytest.raises(ValueError, match="not a current recipient"):
        db.preview_campaign_member_removal(**removal(db, task["id"], "missing"))
    assert snapshot(db, list(before)) == before
    single = fixture.campaign(1)["id"]
    with pytest.raises(ValueError, match="whole allocation"):
        db.preview_campaign_member_removal(**removal(db, single))


def test_member_removal_failure_rolls_back_assignments_and_audit(fixture):
    db = fixture.db
    cid, _ = make_task(fixture, count=40, completed=5)
    body = removal(db, cid)
    preview = db.preview_campaign_member_removal(**body)
    tables = [*EVIDENCE, "issue_work_splits", "review_work_assignments", "campaign_issue_members",
              "campaign_assignment_audit", "campaign_config_revisions", "review_work_assignment_changes"]
    before = snapshot(db, tables)
    with db.connect() as conn:
        conn.execute("""CREATE TRIGGER fail_removal BEFORE INSERT ON campaign_config_revisions
            WHEN NEW.change_source='allocation' BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        db.delete_campaign_allocation_member(**body, preview_token=preview["preview_token"],
            actor="alice", idempotency_key="rollback")
    assert snapshot(db, tables) == before


@pytest.mark.parametrize("purpose", ["labeling", "model_review"])
def test_delete_whole_api_retains_all_evidence_and_assignments(fixture, purpose):
    db = fixture.db
    cid, _ = make_task(fixture, count=40, completed=5, purpose=purpose)
    before = snapshot(db, [*EVIDENCE, "review_work_assignments"])
    app = FastAPI(); app.include_router(campaigns.router)
    url = f"/api/campaigns/{cid}/allocation"
    body = dict(expected_revision=1, reason="Remove allocation, retain evidence")
    with patch.object(campaigns, "database", db), patch.object(campaigns, "_campaign_admin",
            return_value=("alice", "test", True)), TestClient(app) as client:
        assert client.request("DELETE", url, json=body).status_code == 400
        stale = client.request("DELETE", url, json={**body, "expected_revision": 2},
            headers={"Idempotency-Key": "stale"})
        assert stale.status_code == 409
        assert snapshot(db, list(before)) == before
        response = client.request("DELETE", url, json=body, headers={"Idempotency-Key": "delete"})
        assert response.status_code == 200, response.text
        assert db.get_campaign(cid)["campaign"]["lifecycle"] == "cancelled"
        assert snapshot(db, list(before)) == before
        assert not db.get_campaign_allocation(cid)["editable"]
        assert cid not in {i["id"] for i in db.list_campaigns(lifecycle="current")["items"]}
        assert cid in {i["id"] for i in db.list_campaigns(lifecycle="history")["items"]}
        replay = client.request("DELETE", url, json=body, headers={"Idempotency-Key": "delete"})
        assert replay.status_code == 200 and replay.json()["replayed"]
        assert db.get_campaign_allocation(cid)["expected_revision"] == 2


def test_removal_apis_require_admin_and_snapshot_preview(fixture):
    db = fixture.db
    cid, _ = make_task(fixture, count=40, completed=5)
    app = FastAPI(); app.include_router(campaigns.router)
    url = f"/api/campaigns/{cid}/allocation"
    with patch.object(campaigns, "database", db), TestClient(app) as client:
        with patch.object(campaigns, "_campaign_admin", side_effect=HTTPException(403)):
            assert client.request("DELETE", url, json={}).status_code == 403
            assert client.request("DELETE", url + "/assignees/alice", json={}).status_code == 403
            assert client.post(url + "/assignees/alice/removal-preview", json={}).status_code == 403
        with patch.object(campaigns, "_campaign_admin", return_value=("alice", "test", True)):
            headers = {"Idempotency-Key": "member-api"}
            body = dict(expected_revision=1, quota_basis="total")
            assert client.request("DELETE", url + "/assignees/alice", json=body, headers=headers).status_code == 409
            preview = client.post(url + "/assignees/alice/removal-preview", json=body)
            assert preview.status_code == 200, preview.text
            body["preview_token"] = preview.json()["preview_token"]
            assert client.request("DELETE", url + "/assignees/alice", json=body, headers=headers).status_code == 200
            assert client.request("DELETE", url + "/assignees/bob", json=body, headers=headers).status_code == 409


def test_cancelled_version_task_stays_in_history_and_stops_appending(role_db):
    db = role_db
    iid, binding = choose(db)
    cid = binding["campaign_id"]
    submit(db, iid, binding["assignees"][0])
    before = snapshot(db, [*EVIDENCE, "review_work_assignments", "human_assignment_roles"])
    db.transition_campaign(campaign_id=cid, action="cancel", actor="alice",
        expected_revision=db.get_campaign_allocation(cid)["expected_revision"],
        idempotency_key="cancel", reason="Delete allocation")
    assert snapshot(db, list(before)) == before
    assert cid not in {t["split_id"] for t in version_tasks(db)}
    historical = next(t for t in version_tasks(db, lifecycle="history") if t["split_id"] == cid)
    assert historical["lifecycle"] == "cancelled" and not historical["is_current"]
    assert not version_task_detail(db, cid)["is_current"]
    with pytest.raises(ValueError, match="not active"):
        db.append_version_campaign_members(family="20261106",
            policy=dict(sampling_policy="version_probability_v3", seed="a"*64),
            issue_ids=[iid], current_target_ids=[iid], batch_key="after-cancel", actor="test")
    assert snapshot(db, list(before)) == before
