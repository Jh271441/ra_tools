"""Exercise task-wide edits against real storage, history, and append workflows."""
import json
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.campaigns import CampaignConflictError, CampaignReadOnlyError
from ra_triage_dashboard.tests import test_combined_reviews as combined_fixtures
from ra_triage_dashboard.tests.test_human_publication import db as role_db, choose, submit, publication


@pytest.fixture
def fixture():
    case = combined_fixtures.CombinedReviewWorkflowTest()
    case.setUp()
    yield case
    case.doCleanups()


def edit(db, cid, names, *, reviewers=1, ratio=0, revision=None, key=None):
    current_revision = revision or db.get_campaign_allocation(cid)["expected_revision"]
    people = [dict(name=n, count=None) for n in names]
    # Omitted preview is still supported for untouched tasks/old-client replay.
    config = db.get_campaign_allocation(cid)
    token = db.preview_campaign_allocation(campaign_id=cid, assignees=people,
        reviewers_per_issue=reviewers, overlap_ratio=ratio, expected_revision=current_revision)["preview_token"] if config["completed_slots"] or config["saved_pending_slots"] else ""
    return db.update_campaign_allocation(
        campaign_id=cid, assignees=people, preview_token=token,
        reviewers_per_issue=reviewers, overlap_ratio=ratio,
        expected_revision=current_revision,
        idempotency_key=key or uuid4().hex, actor="alice", actor_source="test", actor_verified=True,
    )


def snapshot(db, tables):
    with db.connect() as conn:
        return {table: [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()] for table in tables}


def test_adjust_coverage_on_untouched_cases_and_choose_partners(fixture):
    db = fixture.db
    ids = [f"cn{n}" for n in range(1, 7)]
    db.upsert_issues([dict(issue_id=i, gt_label="正确触发") for i in ids], source="test",
                     replace_gt=True, baseline_scope="scope")
    ws = db.create_review_workset(baseline_scope="scope", issue_ids=ids, created_by="alice")
    cid = db.create_campaign(
        spec=dict(purpose="labeling", workset_id=ws["id"], overlap_ratio=1,
                  members=[dict(issue_id=i, assignees=["alice", "bob"]) for i in ids]),
        actor="alice",
    )["campaign"]["id"]

    def save(iid, owner, output):
        db.create_label_revision(issue_id=iid, task_id=cid, expected_output=output, author=owner,
            author_source="test", author_verified=True, tags=[], evidence_gaps=[], rationale="Saved", is_excluded=False)

    save("cn1", "alice", "正确触发")
    save("cn2", "bob", "")
    config = db.get_campaign_allocation(cid)
    assert config["coverage"]["locked_cases"] == config["coverage"]["min_cross_cases"] == 2
    request = dict(campaign_id=cid, expected_revision=config["expected_revision"], quota_basis="total",
                   reviewers_per_issue=3, overlap_ratio=.5,
                   assignees=[dict(name="alice"), dict(name="bob"), dict(name="viewer")],
                   cross_groups=[dict(members=["alice", "viewer"], issue_ids=["cn1"]),
                                 dict(members=["alice", "bob", "viewer"], issue_ids=["cn3"])])
    preview = db.preview_campaign_allocation(**request)
    assert preview["coverage_before"]["cross_cases"] == 6
    assert preview["coverage_after"]["reviewer_counts"] == {1: 3, 2: 2, 3: 1}
    before = snapshot(db, ["model_review_revisions", "label_revisions", "review_worksets"])
    result = db.update_campaign_allocation(**request, preview_token=preview["preview_token"],
                                            idempotency_key="protected-coverage", actor="alice")
    assert result["preview"]["total_slots"] == 10
    assert db.get_campaign_allocation(cid)["cross_groups"] == preview["cross_groups"]
    assert snapshot(db, list(before)) == before
    rows = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    owners = defaultdict(set)
    for row in rows:
        owners[row["issue_id"]].add(row["assignee"])
    assert owners["cn1"] == {"alice", "viewer"}
    assert "bob" in owners["cn2"] and len(owners["cn2"]) == 2
    assert owners["cn3"] == {"alice", "bob", "viewer"}

    request.update(expected_revision=result["allocation"]["expected_revision"],
                   reviewers_per_issue=2, overlap_ratio=1, cross_groups=[])
    preview = db.preview_campaign_allocation(**request)
    save("cn3", "alice", "")
    with pytest.raises(CampaignConflictError, match="preview"):
        db.update_campaign_allocation(**request, preview_token=preview["preview_token"],
                                      idempotency_key="stale-coverage", actor="alice")
    assert db.get_campaign_allocation(cid)["cross_case_count"] == 3


@pytest.mark.parametrize("purpose", ["labeling", "review"])
@pytest.mark.parametrize("grouped", [False, True])
def test_creation_preview_and_exact_commit_for_both_surfaces(fixture, monkeypatch, purpose, grouped):
    from ra_triage_dashboard.app.routers import cases
    from ra_triage_dashboard.app.routers.labeling_api import tasks

    db = fixture.db
    ids = [f"cn{n}" for n in range(1, 5)]
    db.upsert_issues([dict(issue_id=i, gt_label="正确触发") for i in ids], source="test",
                     replace_gt=True, baseline_scope="scope")
    endpoint = tasks if purpose == "labeling" else cases
    path = "/api/labeling/tasks" if purpose == "labeling" else "/api/cases/work-split"
    monkeypatch.setattr(endpoint, "database", db)
    monkeypatch.setattr(endpoint, "_admin_identity", lambda request: SimpleNamespace(username="alice", source="test", verified=True))
    body = dict(name="Cross preview", request_id="creation-preview",
                assignees=[dict(name=name, review_percent=share) for name, share in
                           [("alice", 40), ("bob", 35), ("viewer", 25)]],
                reviewers_per_issue=3, overlap_ratio=.5, cross_groups=[dict(members=["alice", "bob", "viewer"], count=1)])
    if grouped:
        body = dict(name="Group preview", request_id="creation-groups",
                    groups=[dict(group_id=gid, coverage_percent=coverage,
                                 members=[dict(name=name, review_percent=100)])
                            for gid, name, coverage in [("first", "alice", 100), ("second", "bob", 100), ("third", "viewer", 50)]],
                    cross_groups=[dict(members=[dict(group_id="first", name="alice"),
                                               dict(group_id="third", name="viewer")], issue_ids=["cn1"])])
    if purpose == "labeling":
        monkeypatch.setattr(tasks, "restrict_version_issue_ids", lambda selection, request, issue_ids: issue_ids)
        monkeypatch.setattr(tasks, "baseline_registry", SimpleNamespace(allowed_scopes=lambda: {"scope"}))
        body["issue_ids"] = ids
    else:
        run = fixture.runs[0]["id"]
        body.update(filters=dict(baselines="0508", model_run_id=run), workflow_mode="model_review_and_case_label")
        filters = dict(baseline_scopes=["scope"], model_run_id=run, comparison_status="all",
                       comment_state="all", search="", gt_label="", model_label="", annotation_author="",
                       missing_evidence="", work_assignee="")
        monkeypatch.setattr(cases, "_case_filter_kwargs", lambda **kwargs: dict(filters))
        monkeypatch.setattr(cases, "_case_issue_ids_with_status_filter", lambda **kwargs: ids)
    app = FastAPI()
    app.include_router(endpoint.router)
    before = snapshot(db, ["issue_work_splits", "review_worksets", "review_work_assignments"])
    with TestClient(app) as client:
        response = client.post(path, json={**body, "preview_only": True})
        assert response.status_code == 200, response.text
        preview = response.json()["preview"]
        assert preview["total_slots"] == (10 if grouped else 8)
        assert preview["coverage_after"]["cross_cases"] == (4 if grouped else 2)
        assert snapshot(db, list(before)) == before
        request = {**body, "preview_token": preview["preview_token"]}
        stale = client.post(path, json={**request, "name": "Changed experiment"})
        assert stale.status_code == 409, stale.text
        assert snapshot(db, list(before)) == before
        result = client.post(path, json=request)
        assert result.status_code == 200, result.text
        replay = client.post(path, json=request)
        assert replay.status_code == 200, replay.text
        assert replay.json()["split_id"] == result.json()["split_id"]
    allocation = db.get_campaign_allocation(result.json()["split_id"])
    if grouped:
        assert allocation["group_coverage"] == preview["group_coverage"]
    assert allocation["cross_groups"] == preview["cross_groups"]
    assert allocation["assignment_counts"] == {p["name"]: p["total_after"] for p in preview["members"]}


@pytest.mark.parametrize("purpose", ["labeling", "combined"])
def test_edit_members_and_cross_review_retains_workset_and_evidence(fixture, purpose):
    db = fixture.db
    if purpose == "combined":
        campaign = fixture.campaign(0)
        ctx = db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        fixture.submit(campaign, ctx)
    else:
        campaign = db.create_campaign(
            spec=dict(purpose="labeling", name="Label task", workset_id=fixture.workset["id"],
                      members=[dict(issue_id="cn1", assignees=["alice"])]),
            actor="alice", actor_source="test", actor_verified=True,
        )["campaign"]
        db.create_label_revision(
            issue_id="cn1", task_id=campaign["id"],
            expected_output="误触发", author="alice", author_source="test", author_verified=True,
            tags=[], evidence_gaps=[], rationale="Saved label", is_excluded=False,
        )
    cid = campaign["id"]
    tables = ["review_worksets", "review_workset_items", "campaign_reference_items",
              "model_predictions", "label_revisions", "model_review_revisions", "human_vote_roles"]
    before = snapshot(db, tables)
    with pytest.raises(ValueError, match="coverage"):
        edit(db, cid, ["bob", "viewer"], reviewers=2, ratio=1)
    protected = snapshot(db, ["review_work_assignments"])
    result = edit(db, cid, ["bob", "viewer"])
    assert result["changed"]
    assert snapshot(db, tables) == before
    assert db.get_campaign(cid)["campaign"]["workset_id"] == fixture.workset["id"]
    with db.connect() as conn:
        owners = {r["assignee"] for r in conn.execute("SELECT assignee FROM review_work_assignments WHERE split_id=?", (cid,)).fetchall()}
        assert owners == {"alice"}
        assert conn.execute("SELECT required_submitter_count FROM campaign_issue_members WHERE campaign_id=?", (cid,)).fetchone()[0] == 1
        saved = json.loads(conn.execute("SELECT config_json FROM campaign_config_revisions WHERE campaign_id=? ORDER BY revision_no DESC", (cid,)).fetchone()[0])
        assert saved["task_allocation"]["reviewers_per_issue"] == 1
    assert snapshot(db, ["review_work_assignments"]) == protected
    edit(db, cid, ["bob"], reviewers=1, ratio=0)
    assert snapshot(db, tables) == before
    assert db.get_campaign_allocation(cid)["reviewers_per_issue"] == 1


def test_noop_replay_conflict_and_atomic_validation(fixture):
    db = fixture.db; cid = fixture.campaign(0)["id"]
    before = snapshot(db, ["campaign_config_revisions", "review_work_assignments"])
    assert not edit(db, cid, ["alice"])["changed"]
    assert snapshot(db, ["campaign_config_revisions", "review_work_assignments"]) == before
    rev = db.get_campaign_allocation(cid)["expected_revision"]
    result = edit(db, cid, ["bob", "viewer"], reviewers=2, ratio=.1, revision=rev, key="retry")
    assert result["allocation"]["reviewers_per_issue"] == 2  # one Case rounds down to zero overlap
    assert edit(db, cid, ["bob", "viewer"], reviewers=2, ratio=.1, revision=rev, key="retry")["replayed"]
    with pytest.raises(CampaignConflictError):
        edit(db, cid, ["alice"], revision=rev)
    with pytest.raises(CampaignConflictError):
        edit(db, cid, ["alice"], revision=rev, key="retry")
    before = snapshot(db, ["campaign_config_revisions", "review_work_assignments"])
    for names, reviewers, ratio in [([], 1, 0), (["missing"], 1, 0), (["bob", "bob"], 1, 0),
                                    (["bob"], 2, 1), (["bob"], 1.2, 0), (["bob"], 1, float("nan"))]:
        with pytest.raises(ValueError):
            edit(db, cid, names, reviewers=reviewers, ratio=ratio)
    assert snapshot(db, ["campaign_config_revisions", "review_work_assignments"]) == before
    db.transition_campaign(campaign_id=cid, action="cancel", actor="alice",
        expected_revision=db.get_campaign_allocation(cid)["expected_revision"], idempotency_key="cancel", reason="test")
    with pytest.raises(CampaignReadOnlyError):
        edit(db, cid, ["alice"])


def test_competing_writers_only_one_revision_commits(fixture):
    db = fixture.db; cid = fixture.campaign(0)["id"]
    # Independent DB instances are exercised by opening the fixture file.
    other = Database(db.path)
    rev = db.get_campaign_allocation(cid)["expected_revision"]
    def attempt(database, name):
        try:
            return edit(database, cid, [name], revision=rev)["changed"]
        except CampaignConflictError:
            return False
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda args: attempt(*args), [(db, "bob"), (other, "viewer")]))
        assert results.count(True) == 1
        assert db.get_campaign_allocation(cid)["expected_revision"] == rev + 1
    finally:
        other.close()


def test_router_requires_admin_and_validates_body(fixture):
    from ra_triage_dashboard.app.routers import campaigns
    from fastapi import HTTPException
    cid = fixture.campaign(0)["id"]
    app = FastAPI(); app.include_router(campaigns.router)
    with patch.object(campaigns, "database", fixture.db), TestClient(app) as client:
        with patch.object(campaigns, "_campaign_admin", side_effect=HTTPException(403)):
            assert client.get(f"/api/campaigns/{cid}/allocation").status_code == 403
            assert client.patch(f"/api/campaigns/{cid}/allocation", json={}).status_code == 403
        with patch.object(campaigns, "_campaign_admin", return_value=("alice", "test", True)):
            config = client.get(f"/api/campaigns/{cid}/allocation").json()
            body = dict(assignees=[dict(name="bob")], reviewers_per_issue=1, overlap_ratio=0,
                        expected_revision=config["expected_revision"])
            url = f"/api/campaigns/{cid}/allocation"
            assert client.patch(url, json=body).status_code == 400
            assert client.patch(url, json=body, headers={"Idempotency-Key": "router"}).status_code == 200
            assert client.patch(url, json=body, headers={"Idempotency-Key": "stale"}).status_code == 409


def test_storage_failure_rolls_back_allocation_and_audit(fixture):
    db = fixture.db; cid = fixture.campaign(0)["id"]
    tables = ["issue_work_splits", "review_work_assignments", "campaign_assignment_audit",
              "campaign_issue_members", "campaign_config_revisions", "human_assignment_roles"]
    before = snapshot(db, tables)
    with db.connect() as conn:
        conn.execute("""CREATE TRIGGER fail_allocation BEFORE INSERT ON campaign_config_revisions
            WHEN NEW.change_source='allocation' BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        edit(db, cid, ["bob"])
    assert snapshot(db, tables) == before


def test_partial_overlap_preserves_base_owners_and_quota_zero(fixture):
    db = fixture.db
    ids = [f"cn{n}" for n in range(20, 30)]
    db.upsert_issues([dict(issue_id=i, gt_label="误触发") for i in ids],
                    source="test", replace_gt=True, baseline_scope="scope")
    ws = db.create_review_workset(baseline_scope="scope", issue_ids=ids, name="Ten Cases", created_by="alice")
    cid = db.create_campaign(spec=dict(purpose="labeling", workset_id=ws["id"],
        members=[dict(issue_id=i, assignees=["alice" if n % 2 == 0 else "bob"]) for n, i in enumerate(ids)]),
        actor="alice")["campaign"]["id"]
    before = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    edit(db, cid, ["alice", "bob"], reviewers=2, ratio=.5)
    rows = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    assert {(r["issue_id"], r["assignee"]) for r in rows if r["assignment_kind"] == "base"} == {
        (r["issue_id"], r["assignee"]) for r in before}
    assert len(rows) == 15
    db.update_campaign_allocation(campaign_id=cid,
        assignees=[dict(name="alice", count=0), dict(name="bob", count=None)], reviewers_per_issue=1,
        overlap_ratio=0, expected_revision=db.get_campaign_allocation(cid)["expected_revision"],
        idempotency_key="zero", actor="alice")
    assert {r["assignee"] for r in snapshot(db, ["review_work_assignments"])["review_work_assignments"]} == {"bob"}
    assert db.get_campaign_allocation(cid)["assignees"] == [dict(name="alice", count=0), dict(name="bob", count=None)]


def test_older_version_append_and_ingestion_keep_edited_cross_review(fixture):
    db = fixture.db
    family = "20261030"
    for name in ["jasperchen", "liangxianghui", "hejianmo"]:
        db.set_access_user(username=name, role="writer", actor="test")
    rid = db.ensure_version_stream(family, "test")
    ids = ["cn101", "cn102", "cn103"]
    db.append_version_predictions(run_id=rid, rows=[dict(issue_id=i, model_label="误触发", model_confidence=.7,
        model_extra=dict(software_version=f"1.gen4-release-{family}.1")) for i in ids])
    policy = dict(sampling_policy="version_probability_v3", seed="a" * 64)
    first = db.append_version_campaign_members(family=family, policy=policy, issue_ids=ids[:2],
        current_target_ids=ids, batch_key="first", actor="test")
    cid = first["campaign_id"]
    edit(db, cid, ["alice", "bob"], reviewers=2, ratio=1)
    before = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    added = db.append_version_campaign_members(family=family, policy=policy, issue_ids=ids,
        current_target_ids=ids, batch_key="second", actor="test")
    assert added["added"] == 1
    assert set(added["bindings"]["cn103"]["assignees"]) == {"alice", "bob"}
    assert all(r in snapshot(db, ["review_work_assignments"])["review_work_assignments"] for r in before)
    def packet(bindings):
        return [dict(issue_id=i, software_version=f"1.gen4-release-{family}.1", state="published",
                     is_target=True, is_low=True, is_sample=False, binding=bindings[i]) for i in ids]
    db.ingest_version_dataset(family=family, policy=policy, batch_key="second", actor="test",
                             items=packet(added["bindings"]))
    from ra_triage_dashboard.app.version_review_tasks import version_tasks
    task = next(item for item in version_tasks(db) if item["split_id"] == cid)
    assert task["assignment_count"] == 6 and task["reviewers_per_issue"] == 2
    edit(db, cid, ["bob", "viewer"], reviewers=2, ratio=.5)
    replay = db.append_version_campaign_members(family=family, policy=policy, issue_ids=ids,
        current_target_ids=ids, batch_key="second", actor="test")
    assert replay["bindings"] == added["bindings"]
    assert db.ingest_version_dataset(family=family, policy=policy, batch_key="second", actor="test",
                                    items=packet(replay["bindings"]))["replayed"]
    frozen = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    # Daily single-Case packets still balance owners and reach the saved ratio.
    new_ids = [f"cn{n}" for n in range(104, 111)]
    db.append_version_predictions(run_id=rid, rows=[dict(issue_id=i, model_label="误触发", model_confidence=.7,
        model_extra=dict(software_version=f"1.gen4-release-{family}.1")) for i in new_ids])
    for iid in new_ids:
        db.append_version_campaign_members(family=family, policy=policy, issue_ids=[iid],
            current_target_ids=ids+new_ids, batch_key=iid, actor="test")
    rows = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    assert all(row in rows for row in frozen)
    assert len(rows) == 15
    assert len({r["issue_id"] for r in rows if r["assignment_kind"] == "cross"}) == 5
    assert {r["assignee"] for r in rows} == {"bob", "viewer"}
    assert sum(r["assignee"] == "bob" and r["assignment_kind"] == "base" for r in rows) == 5


def test_role_edit_preserves_consensus_votes_and_controls_future_appends(role_db):
    db = role_db
    iid, binding = choose(db)
    cid = binding["campaign_id"]
    for person in binding["assignees"]:
        submit(db, iid, person)
    db.refresh_human_publications(delay=0)
    assert publication(db, iid)["conclusion"] == "resolved"
    before = snapshot(db, ["label_revisions", "model_review_revisions", "human_vote_roles"])
    old_rd = next(m["username"] for m in db.human_label_context(iid)["members"] if m["role"] == "rd")
    new_rd = "liangxianghui" if old_rd == "jasperchen" else "jasperchen"
    edit(db, cid, [new_rd, "yupuxue_v"], reviewers=2, ratio=1)
    assert snapshot(db, ["label_revisions", "model_review_revisions", "human_vote_roles"]) == before
    assert db.human_label_context(iid)["lanes"]["rd"]["state"] == "resolved"
    db.refresh_human_publications(delay=0)
    assert publication(db, iid)["desired"] is not None
    with pytest.raises(ValueError, match="RD"):
        edit(db, cid, [new_rd, "yupuxue_v"], reviewers=2, ratio=.5)
    from ra_triage_dashboard.app.db_parts.role_version_tasks import sampled
    new_id = next(f"cn{n}" for n in range(100, 120) if not sampled("a" * 64, "20261106", f"cn{n}"))
    rid = db.ensure_version_stream("20261106", "test")
    db.append_version_predictions(run_id=rid, rows=[dict(issue_id=new_id, model_label="误触发", model_confidence=.7,
        model_extra=dict(software_version="1.gen4-release-20261106.1"))])
    added = db.append_version_campaign_members(family="20261106", policy=dict(sampling_policy="version_probability_v3", seed="a" * 64),
        issue_ids=[new_id], current_target_ids=[new_id], batch_key="after-edit", actor="test")
    assert set(added["bindings"][new_id]["assignees"]) == {new_rd, "yupuxue_v"}
    assert snapshot(db, ["label_revisions", "model_review_revisions", "human_vote_roles"]) == before
    def packet(bindings):
        return [dict(issue_id=new_id, software_version="1.gen4-release-20261106.1", state="published",
                     is_target=True, is_low=True, is_sample=False, binding=bindings[new_id])]
    policy = dict(sampling_policy="version_probability_v3", seed="a"*64)
    db.ingest_version_dataset(family="20261106", policy=policy, items=packet(added["bindings"]),
                             batch_key="after-edit", actor="test")
    with pytest.raises(ValueError, match="coverage"):
        edit(db, cid, [new_rd, old_rd, "yupuxue_v"], reviewers=3, ratio=1)
    edit(db, cid, [new_rd, old_rd, "yupuxue_v"], reviewers=2, ratio=1)
    replay = db.append_version_campaign_members(family="20261106", policy=policy, issue_ids=[new_id],
        current_target_ids=[new_id], batch_key="after-edit", actor="test")
    assert replay["bindings"][new_id] == added["bindings"][new_id]
    assert db.ingest_version_dataset(family="20261106", policy=policy, items=packet(replay["bindings"]),
                                    batch_key="after-edit", actor="test")["replayed"]


def percent_edit(db, cid, percentages, *, reviewers=1, ratio=0):
    people = [dict(name=name, count=None, review_percent=value) for name, value in percentages.items()]
    config = db.get_campaign_allocation(cid)
    preview = db.preview_campaign_allocation(campaign_id=cid, assignees=people,
        reviewers_per_issue=reviewers, overlap_ratio=ratio, expected_revision=config["expected_revision"], quota_basis="total")
    return db.update_campaign_allocation(campaign_id=cid,
        assignees=people, preview_token=preview["preview_token"], quota_basis="total",
        reviewers_per_issue=reviewers, overlap_ratio=ratio,
        expected_revision=db.get_campaign_allocation(cid)["expected_revision"],
        idempotency_key=uuid4().hex, actor="alice", actor_source="test", actor_verified=True)


@pytest.mark.parametrize("purpose", ["labeling", "model_review"])
def test_percent_edit_sets_total_workload_shares_and_round_trips_without_reshuffle(fixture, purpose):
    db = fixture.db
    ids = [f"cn{n}" for n in range(20, 40)]
    db.upsert_issues([dict(issue_id=i, gt_label="误触发") for i in ids], source="test", replace_gt=True, baseline_scope="scope")
    run, _ = db.import_model_run(name="percent", source_name="percent.json", source_sha256="7" * 64,
        metadata={}, rows=[dict(issue_id=i, model_label="误触发") for i in ids])
    ws = db.create_review_workset(baseline_scope="scope", issue_ids=ids, created_by="alice")
    spec = dict(purpose=purpose, workset_id=ws["id"],
                members=[dict(issue_id=i, assignees=["alice" if n % 2 else "bob"]) for n, i in enumerate(ids)])
    if purpose == "model_review":
        spec.update(evaluation_run_id=run["id"], workflow_mode="model_review_and_case_label")
    cid = db.create_campaign(spec=spec, actor="alice")["campaign"]["id"]
    evidence = snapshot(db, ["model_predictions", "review_worksets", "review_workset_items", "campaign_reference_items"])
    shares = dict(alice=50, bob=30, viewer=20)
    result = percent_edit(db, cid, shares, reviewers=2, ratio=.5)
    assert result["changed"]
    assert result["allocation"]["assignment_counts"] == dict(alice=15, bob=9, viewer=6)
    assert {p["name"]: p["review_percent"] for p in db.get_campaign_allocation(cid)["assignees"]} == shares
    shares = dict(alice=60, bob=30, viewer=10)
    assert percent_edit(db, cid, shares, reviewers=2, ratio=.5)["allocation"]["assignment_counts"] == dict(alice=18, bob=9, viewer=3)
    before = snapshot(db, ["review_work_assignments", "campaign_config_revisions"])
    assert not percent_edit(db, cid, shares, reviewers=2, ratio=.5)["changed"]
    assert snapshot(db, ["review_work_assignments", "campaign_config_revisions"]) == before
    assert snapshot(db, list(evidence)) == evidence
    rows = before["review_work_assignments"]
    assert len({(r["issue_id"], r["assignee"]) for r in rows}) == len(rows)
    assert len({r["issue_id"] for r in rows if r["assignment_kind"] == "cross"}) == 10
    # Switching out of percentage mode really changes the distribution.
    result = edit(db, cid, ["alice", "bob", "viewer"])
    assert sum(result["allocation"]["assignment_counts"].values()) == 20
    assert "review_percent" not in result["allocation"]["assignees"][0]


@pytest.mark.parametrize("shares,reviewers,ratio", [
    (dict(alice=40, bob=40), 1, 0),
    (dict(alice=None, bob=100), 1, 0),
    (dict(alice=True, bob=99), 1, 0),
    (dict(alice="50", bob=50), 1, 0),
    (dict(alice=-10, bob=110), 1, 0),
    (dict(alice=float("nan"), bob=100), 1, 0),
    (dict(alice=float("inf"), bob=0), 1, 0),
    (dict(alice=33.333, bob=66.667), 1, 0),
    (dict(alice=75, bob=25), 2, 1),
])
def test_invalid_personal_percentages_do_not_write(fixture, shares, reviewers, ratio):
    db = fixture.db; cid = fixture.campaign(0)["id"]
    tables = ["issue_work_splits", "review_work_assignments", "campaign_config_revisions", "campaign_assignment_audit"]
    before = snapshot(db, tables)
    with pytest.raises(ValueError):
        percent_edit(db, cid, shares, reviewers=reviewers, ratio=ratio)
    assert snapshot(db, tables) == before


def test_formal_percentage_targets_keep_role_coverage_and_saved_votes(role_db):
    db = role_db
    iid, binding = choose(db)
    cid = binding["campaign_id"]
    submit(db, iid, binding["assignee"])
    current = db.get_campaign_allocation(cid)
    assert sorted(current["role_movable_slots"].values()) == [current["member_count"] - 1, current["member_count"]]
    before = snapshot(db, ["label_revisions", "model_review_revisions", "human_vote_roles"])
    shares = dict(jasperchen=40, liangxianghui=10, yupuxue_v=30, zhangxuzhao_v=20)
    result = percent_edit(db, cid, shares, reviewers=2, ratio=1)
    count = result["allocation"]["member_count"]
    actual = result["allocation"]["assignment_counts"]
    assert actual["jasperchen"] + actual["liangxianghui"] == count
    assert actual["yupuxue_v"] + actual["zhangxuzhao_v"] == count
    assert all(abs(actual[name] - 2 * count * share / 100) <= 1 for name, share in shares.items())
    with db.connect() as conn:
        groups = defaultdict(list)
        for r in conn.execute("SELECT a.issue_id,h.role FROM review_work_assignments a "
                              "JOIN human_user_roles h ON h.username=a.assignee WHERE a.split_id=?", (cid,)).fetchall():
            groups[r["issue_id"]].append(r["role"])
    assert all(sorted(roles) == ["rd", "te"] for roles in groups.values())
    assert snapshot(db, list(before)) == before
    constrained = percent_edit(db, cid, dict(jasperchen=40, liangxianghui=20, yupuxue_v=20, zhangxuzhao_v=20), reviewers=2, ratio=1)
    assert any(p["constrained"] for p in constrained["preview"]["members"])
    percent_edit(db, cid, shares, reviewers=2, ratio=1)
    rid = db.ensure_version_stream("20261106", "test")
    from ra_triage_dashboard.app.db_parts.role_version_tasks import sampled
    policy = dict(sampling_policy="version_probability_v3", seed="a" * 64)
    fresh = [f"cn{n}" for n in range(100, 130) if not sampled(policy["seed"], "20261106", f"cn{n}")]
    db.append_version_predictions(run_id=rid, rows=[dict(issue_id=i, model_label="误触发", model_confidence=.7,
        model_extra=dict(software_version="1.gen4-release-20261106.1")) for i in fresh])
    frozen = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    old_ids = [f"cn{n}" for n in range(1, 61)]
    for iid in fresh:
        db.append_version_campaign_members(family="20261106", policy=policy, issue_ids=[iid],
            current_target_ids=old_ids + fresh, batch_key=iid, actor="test")
    assert all(row in snapshot(db, ["review_work_assignments"])["review_work_assignments"] for row in frozen)
    allocation = db.get_campaign_allocation(cid)
    assert all(abs(allocation["assignment_counts"][name] - 2 * (count + len(fresh)) * share / 100) <= 1
               for name, share in shares.items())


def test_percentage_rounding_single_case_roles_and_incremental_non_role_work():
    from ra_triage_dashboard.app.task_allocation_policy import allocate_percentages, validate_percentages
    roles = dict(a="rd", b="rd", c="te", d="te")
    people = [dict(name=name, review_percent=25) for name in roles]
    tiny = allocate_percentages(["one"], people, reviewers=2, overlap=1, seed=42, roles=roles)
    assert sorted(roles[r["assignee"]] for r in tiny) == ["rd", "te"]
    many = allocate_percentages([str(i) for i in range(101)], people, reviewers=3, overlap=1, seed=42, roles=roles)
    groups = defaultdict(list)
    for row in many:
        groups[row["issue_id"]].append(row["assignee"])
    assert all(len(set(names)) == 3 and {roles[p] for p in names} == {"rd", "te"} for names in groups.values())
    assert sorted(Counter(r["assignee"] for r in many).values()) == [75, 76, 76, 76]
    thirds = [dict(name=name, review_percent=value) for name, value in dict(a=33.34, c=33.33, d=33.33).items()]
    validate_percentages(thirds, reviewers=3, overlap=1, roles=roles)
    all_review = allocate_percentages([str(i) for i in range(101)], thirds, reviewers=3, overlap=1, seed=42, roles=roles)
    assert Counter(r["assignee"] for r in all_review) == dict(a=101, c=101, d=101)
    people = [dict(name="a", review_percent=60), dict(name="b", review_percent=30), dict(name="c", review_percent=10)]
    previous = []
    for index in range(100):
        rows = allocate_percentages([str(index)], people, reviewers=2, overlap=.5, seed=42, previous=previous)
        previous.append(dict(assignees=[r["assignee"] for r in rows]))
    actual = Counter(name for item in previous for name in item["assignees"])
    assert actual == dict(a=90, b=45, c=15)
    assert all(len(set(item["assignees"])) == len(item["assignees"]) for item in previous)
