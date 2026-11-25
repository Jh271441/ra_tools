"""Protected redistribution: quotas, evidence, concurrency and real persistence."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import product
import json
from threading import Event
from unittest.mock import patch
from uuid import uuid4

import pytest

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.campaigns import CampaignConflictError
from ra_triage_dashboard.app.db_parts.shared import AnnotationConflictError, LabelAnnotationConflictError
from ra_triage_dashboard.app.task_reallocation import bounded_shares, reallocate_slots
from ra_triage_dashboard.tests.test_task_allocation import fixture, snapshot, role_db, choose, submit


def request(db, cid, *, basis="total", names=("alice", "bob", "c", "d", "e")):
    config = db.get_campaign_allocation(cid)
    return dict(campaign_id=cid, assignees=[dict(name=p, review_percent=100 / len(names)) for p in names],
        reviewers_per_issue=config["reviewers_per_issue"], overlap_ratio=config["overlap_ratio"],
        expected_revision=config["expected_revision"], quota_basis=basis)


def apply(db, body, preview=None, key=None):
    preview = preview or db.preview_campaign_allocation(**body)
    return db.update_campaign_allocation(**body, preview_token=preview["preview_token"],
        idempotency_key=key or uuid4().hex, actor="alice")


def make_task(fixture, count=400, completed=50, purpose="labeling"):
    db = fixture.db
    people = ["alice", "bob", "c", "d", "e"]
    for name in people:
        db.set_access_user(username=name, role="admin" if name in {"alice", "bob"} else "writer", actor="test")
    ids = [f"cn{2000+i}" for i in range(count)]
    db.upsert_issues([dict(issue_id=i, gt_label="误触发") for i in ids], source="test", replace_gt=True, baseline_scope="scope")
    ws = db.create_review_workset(baseline_scope="scope", issue_ids=ids, created_by="alice")
    spec = dict(purpose=purpose, workset_id=ws["id"], name="Protected workload",
        members=[dict(issue_id=i, assignees=[people[min(3, n * 4 // count)]]) for n, i in enumerate(ids)])
    if purpose == "model_review":
        run, _ = db.import_model_run(name="protected", source_name="protected.json", source_sha256="9"*64,
            metadata={}, rows=[dict(issue_id=i, model_label="误触发") for i in ids])
        spec.update(evaluation_run_id=run["id"], workflow_mode="model_review_and_case_label")
    task = db.create_campaign(spec=spec, actor="alice")["campaign"]
    for iid in ids[:completed]:
        if purpose == "labeling":
            save_label(db, task["id"], iid)
        else:
            ctx = db.combined_review_context(issue_id=iid, campaign_id=task["id"], reviewer="alice")
            db.submit_combined_review(issue_id=iid, campaign_id=task["id"], model_run_id=run["id"],
                reviewer="alice", reviewer_source="test", reviewer_verified=True,
                model_review_status="completed", reason="retained", missing_evidence=[], expected_output="误触发",
                tags=[], rationale="retained", expected_model_review_storage_id=ctx["model_review_storage_id"],
                expected_case_revision_id=ctx["case_revision_id"], expected_label_state_fingerprint=ctx["label_state_fingerprint"],
                idempotency_key=iid)
    return task["id"], ids


def save_label(db, cid, iid, author="alice", output="误触发"):
    return db.create_label_revision(issue_id=iid, task_id=cid, expected_output=output,
        author=author, author_source="test", author_verified=True, tags=[], evidence_gaps=[],
        rationale="Saved evidence", is_excluded=False)


@pytest.mark.parametrize("purpose", ["labeling", "model_review"])
@pytest.mark.parametrize("basis,expected,moves", [
    ("remaining", [70]*5, 90), ("total", [30, 80, 80, 80, 80], 80),
])
def test_400_case_example_persists_exact_quotas_and_frozen_ownership(fixture, purpose, basis, expected, moves):
    db = fixture.db
    cid, ids = make_task(fixture, purpose=purpose)
    tables = ["label_revisions", "model_review_revisions", "combined_review_progress",
              "human_vote_roles", "review_worksets", "review_workset_items", "model_predictions", "campaign_reference_items"]
    original = snapshot(db, tables)
    with db.connect() as conn:
        locked = [dict(r) for r in conn.execute("SELECT * FROM review_work_assignments WHERE split_id=? AND assignee='alice' ORDER BY issue_id", (cid,)).fetchall()][:50]
    body = request(db, cid, basis=basis)
    preview = db.preview_campaign_allocation(**body)
    assert [p["pending_after"] for p in preview["members"]] == expected
    assert preview["moved_slots"] == moves
    assert preview["completed_slots"] == 50 and preview["movable_slots"] == 350
    result = apply(db, body, preview, key="save")
    assert result["changed"]
    assert snapshot(db, tables) == original
    with db.connect() as conn:
        after = [dict(r) for r in conn.execute("SELECT * FROM review_work_assignments WHERE split_id=?", (cid,)).fetchall()]
    assert all(r in after for r in locked)
    assert len(after) == 400
    assert db.get_campaign_allocation(cid)["completed_slots"] == 50
    assert db.get_campaign(cid)["progress"]["completed_issue_count"] == 50
    assert apply(db, body, preview, key="save")["replayed"]
    assert db.get_campaign_allocation(cid)["expected_revision"] == body["expected_revision"] + 1
    assert snapshot(db, tables) == original
    with db.connect() as conn:
        transfers = conn.execute(
            "SELECT issue_id,from_assignee,to_assignee FROM review_work_assignment_changes WHERE split_id=?",
            (cid,),
        ).fetchall()
    assert len(transfers) == moves
    assert all(row["from_assignee"] != row["to_assignee"] for row in transfers)


@pytest.mark.parametrize("lower,expected", [
    (dict(a=50), [80,80,80,80,80]), (dict(a=100), [100,75,75,75,75]),
    (dict(a=50,b=10), [80]*5),
])
def test_bounded_balancing(lower, expected):
    assert list(bounded_shares(dict.fromkeys("abcde",20),400,lower).values()) == expected
    assert bounded_shares(dict(a=0,b=25,c=25,d=25,e=25),400,dict(a=50)) == dict(a=50,b=88,c=88,d=87,e=87)
    assert bounded_shares(dict(a=40,b=20,c=20,d=10,e=10),400,dict(a=200)) == dict(a=200,b=67,c=67,d=33,e=33)


def test_departed_author_keeps_completed_and_saved_unfinished_work(fixture):
    db = fixture.db
    cid, ids = make_task(fixture, count=40, completed=5)
    save_label(db, cid, ids[5], output="")
    original = snapshot(db, ["label_revisions", "human_vote_roles"])
    body = request(db, cid, names=("bob","c","d","e"))
    result = apply(db, body)
    author = next(p for p in result["preview"]["members"] if p["name"] == "alice")
    assert (author["completed"], author["saved_pending"], author["pending_after"], author["total_after"]) == (5,1,1,6)
    assert snapshot(db, list(original)) == original
    assert result["allocation"]["assignment_counts"]["alice"] == 6


@pytest.mark.parametrize("basis,alice_pending", [("remaining", 70), ("total", 30)])
def test_grouped_redistribution_locks_completed_and_draft_work(fixture, basis, alice_pending):
    db = fixture.db
    cid, ids = make_task(fixture)
    body = request(db, cid, basis=basis)
    body["groups"] = [dict(group_id="group-1", coverage_percent=100,
                           members=[dict(name=name, review_percent=20) for name in ("alice", "bob", "c", "d", "e")])]
    baseline = snapshot(db, ["label_revisions"])
    response = apply(db, body)
    alice = next(p for p in response["preview"]["members"] if p["name"] == "alice")
    assert alice["pending_after"] == alice_pending
    after = db.get_campaign_allocation(cid)
    assert after["groups"] == [dict(**body["groups"][0], coverage_strategy="overlap")]
    assert after["group_coverage"]["case_count"] == 400
    assert baseline == snapshot(db, ["label_revisions"])
    # A draft submitted after a preview invalidates that preview, and the new
    # plan retains its assignee even when that person leaves the group.
    next_body = {**body, "expected_revision": after["expected_revision"],
                 "groups": [dict(group_id="group-1", coverage_percent=100,
                                 members=[dict(name=name, review_percent=25) for name in ("bob", "c", "d", "e")])]}
    completed = set(ids[:50])
    draft_case = next(row["issue_id"] for row in snapshot(db, ["review_work_assignments"])["review_work_assignments"]
                      if row["assignee"] == "alice" and row["issue_id"] not in completed)
    preview = db.preview_campaign_allocation(**next_body)
    save_label(db, cid, draft_case, output="")
    with pytest.raises(CampaignConflictError, match="preview again"):
        apply(db, next_body, preview)
    result = apply(db, next_body)
    member = next(p for p in result["preview"]["members"] if p["name"] == "alice")
    assert (member["completed"], member["saved_pending"], member["total_after"]) == (50, 1, 51)


def test_group_coverage_policy_and_explicit_partner_binding():
    from ra_triage_dashboard.app.group_allocation import normalize_groups, plan_groups

    cases = [f"cn{i}" for i in range(12)]
    raw = [dict(group_id=gid, coverage_percent=coverage, members=[dict(name=name, review_percent=100)])
           for gid, name, coverage in [("first", "a", 100), ("second", "b", 50), ("third", "c", 50), ("fourth", "d", 25)]]
    groups = normalize_groups(raw, set("abcd"))
    _, overlap, _ = plan_groups(cases, groups, [], seed=20)
    assert sum("second" in owners and "third" in owners for owners in overlap.values()) == 6
    groups[2]["coverage_strategy"] = "fill"
    rows, filled, _ = plan_groups(cases, groups, [], seed=20)
    assert not any("second" in owners and "third" in owners for owners in filled.values())
    assert len(rows) == 27 and all(len(owners) >= 2 for owners in filled.values())
    _, pinned, rules = plan_groups(cases, groups, [
        dict(members=[dict(group_id="second", name="b"), dict(group_id="third", name="c")], issue_ids=["cn3"])
    ], seed=20)
    assert pinned["cn3"]["second"] == "b" and pinned["cn3"]["third"] == "c"
    assert rules[0]["issue_ids"] == ["cn3"]


def test_cross_case_locks_only_saved_slot_and_preserves_exact_coverage(fixture):
    db = fixture.db
    cid = fixture.campaign(0, assignees=["alice", "bob"])["id"]
    task = db.get_campaign(cid)["campaign"]
    fixture.submit(task, db.combined_review_context(issue_id="cn1", campaign_id=cid, reviewer="alice"))
    before = snapshot(db, ["review_work_assignments", "human_assignment_roles"])
    result = apply(db, request(db, cid, names=("viewer",)))
    assert result["allocation"]["assignment_counts"] == dict(alice=1, viewer=1)
    assert result["preview"]["completed_slots"] == 1 and result["preview"]["moved_slots"] == 1
    after = snapshot(db, ["review_work_assignments", "human_assignment_roles"])
    assert next(r for r in before["review_work_assignments"] if r["assignee"] == "alice") in after["review_work_assignments"]
    with pytest.raises(ValueError):
        apply(db, request(db, cid, names=("alice",)))


def test_stale_preview_after_submission_permissions_and_expiry_cannot_write(fixture):
    db = fixture.db
    cid, ids = make_task(fixture, count=40, completed=5)
    body = request(db, cid)
    preview = db.preview_campaign_allocation(**body)
    save_label(db, cid, ids[5])
    before = snapshot(db, ["review_work_assignments", "campaign_assignment_audit", "campaign_config_revisions"])
    with pytest.raises(CampaignConflictError, match="preview again"):
        apply(db, body, preview)
    assert snapshot(db, list(before)) == before
    preview = db.preview_campaign_allocation(**body)
    db.delete_access_user("e")
    with pytest.raises(ValueError):
        apply(db, body, preview)
    db.set_access_user(username="e", role="writer", actor="alice")
    preview = db.preview_campaign_allocation(**body)
    with patch("ra_triage_dashboard.app.db_parts.campaign_allocation.time.time", return_value=preview["expires_at"]+1):
        with pytest.raises(CampaignConflictError, match="expired"):
            apply(db, body, preview)
    assert snapshot(db, list(before)) == before
    with pytest.raises(CampaignConflictError, match="Preview changes"):
        db.update_campaign_allocation(**body, idempotency_key="old-client", actor="alice")


def test_saved_progress_preserved_when_a_concurrent_submit_wins(fixture):
    db = fixture.db
    cid, ids = make_task(fixture, count=40, completed=5)
    other = Database(db.path)
    body = request(db, cid)
    preview = db.preview_campaign_allocation(**body)
    acquired, applying, release = Event(), Event(), Event()
    other_lock, edit_lock = other._lock_task_work, db._lock_task_work
    def save_gate(conn):
        other_lock(conn)
        acquired.set()
        assert release.wait(5)
    def edit_gate(conn):
        applying.set()
        edit_lock(conn)
    try:
        # Different DB objects: correctness must not depend on the process lock.
        with patch.object(other, "_lock_task_work", save_gate), patch.object(db, "_lock_task_work", edit_gate):
            with ThreadPoolExecutor(max_workers=2) as pool:
                saved = pool.submit(save_label, other, cid, ids[5])
                assert acquired.wait(5)
                future = pool.submit(apply, db, body, preview)
                assert applying.wait(5)
                release.set()
                saved.result()
                with pytest.raises(CampaignConflictError):
                    future.result()
        assert db.get_campaign_allocation(cid)["completed_slots"] == 6
    finally:
        release.set()
        other.close()


def test_old_page_submission_rejected_after_allocation_without_new_evidence(fixture):
    db = fixture.db
    cid, ids = make_task(fixture, count=40, completed=5)
    revision = db.get_campaign_allocation(cid)["expected_revision"]
    apply(db, request(db, cid))
    before = snapshot(db, ["label_revisions", "combined_review_progress"])
    with pytest.raises(LabelAnnotationConflictError, match="draft is retained"):
        db.create_label_revision(issue_id=ids[6], task_id=cid, expected_output="误触发",
            author="alice", author_source="test", author_verified=True, tags=[], evidence_gaps=[],
            rationale="unsaved draft", is_excluded=False, expected_allocation_revision=revision)
    assert snapshot(db, list(before)) == before
    with pytest.raises(ValueError, match="positive integer"):
        db.create_label_revision(issue_id=ids[6], task_id=cid, expected_output="误触发",
            author="alice", author_source="test", author_verified=True, tags=[], evidence_gaps=[],
            rationale="unsaved draft", is_excluded=False, expected_allocation_revision=True)


def test_partial_combined_save_cannot_move_through_either_assignment_entry(fixture):
    db = fixture.db
    task = fixture.campaign(0, assignees=["alice", "bob"])
    cid = task["id"]
    db.create_model_review(issue_id="cn1", model_run_id=task["evaluation_run_id"], campaign_id=cid,
        reviewer="alice", status="pending", reason="saved draft", missing_evidence=[])
    before = snapshot(db, ["model_review_revisions", "review_work_assignments"])
    with pytest.raises(ValueError, match="saved or protected"):
        db.update_campaign_assignment(campaign_id=cid, issue_id="cn1", action="reassign", actor="alice",
            from_assignee="alice", assignee="viewer", expected_revision=1, idempotency_key="old-single")
    with pytest.raises(ValueError, match="saved or protected"):
        db.reassign_review_work_assignment(split_id=cid, issue_id="cn1", assignee="viewer", changed_by="alice")
    assert snapshot(db, list(before)) == before
    result = apply(db, request(db, cid, names=("viewer",)))
    assert result["preview"]["completed_slots"] == 0 and result["preview"]["saved_pending_slots"] == 1
    with pytest.raises(AnnotationConflictError, match="no longer assigned"):
        db.create_model_review(issue_id="cn1", model_run_id=task["evaluation_run_id"], campaign_id=cid,
            reviewer="bob", status="completed", reason="old page", missing_evidence=[])


def test_unassigned_historical_author_cannot_become_a_new_completed_slot(fixture):
    db = fixture.db
    task = fixture.campaign(0)
    cid = task["id"]
    db.create_model_review(issue_id="cn1", model_run_id=task["evaluation_run_id"], campaign_id=cid,
        reviewer="bob", status="completed", reason="supplemental history", missing_evidence=[])
    before = snapshot(db, ["review_work_assignments", "model_review_revisions"])
    with pytest.raises(ValueError):
        apply(db, request(db, cid, names=("bob",)))
    assert snapshot(db, list(before)) == before
    result = apply(db, request(db, cid, names=("viewer",)))
    assert result["preview"]["completed_slots"] == 0


def test_other_task_evidence_does_not_credit_this_task(fixture):
    db = fixture.db
    first, second = fixture.campaign(0), fixture.campaign(1)
    fixture.submit(first, db.combined_review_context(issue_id="cn1", campaign_id=first["id"], reviewer="alice"))
    config = db.get_campaign_allocation(second["id"])
    assert config["completed_slots"] == 0 and config["saved_pending_slots"] == 0
    assert apply(db, request(db, second["id"], names=("bob",)))["preview"]["completed_slots"] == 0


def test_formal_role_pools_balance_remaining_independently():
    rows = [dict(issue_id=str(i), assignee=p, assignment_kind="base" if p == "a" else "cross", ordinal=i)
            for i in range(10) for p in ("a", "c")]
    captured = {(r["issue_id"], r["assignee"]): "rd" if r["assignee"] == "a" else "te" for r in rows}
    locked = {(str(i), "a") for i in range(8)}
    _, summary = reallocate_slots(rows, dict(a=1,b=1,c=1,d=1), basis="remaining",
        protected=locked, completed=locked, roles=dict(a="rd",b="rd",c="te",d="te"), captured_roles=captured)
    assert [p["pending_after"] for p in summary] == [1,1,5,5]
    assert [p["pool_percent"] for p in summary] == [50]*4


def test_future_appends_keep_independent_role_percentages():
    from ra_triage_dashboard.app.task_allocation_policy import allocate_percentages
    people = [dict(name=p, review_percent=w) for p,w in zip("abcd", (30,10,45,15))]
    previous = [dict(assignees=["a" if n%2 else "b", "c" if n%2 else "d"],
                     roles=dict(a="rd", b="rd", c="te", d="te")) for n in range(20)]
    rows = allocate_percentages([f"cn{n}" for n in range(60)], people,
        reviewers=2, overlap=1, seed=1, roles=dict(a="rd", b="rd", c="te", d="te"), previous=previous)
    counts = Counter(p for item in previous for p in item["assignees"])
    counts.update(r["assignee"] for r in rows)
    assert counts == dict(a=60,b=20,c=60,d=20)
    for n in range(60):
        owners = {r["assignee"] for r in rows if r["issue_id"] == f"cn{n}"}
        assert len(owners & set("ab")) == len(owners & set("cd")) == 1


@pytest.mark.parametrize("grouped", [False, True])
def test_saved_role_shares_govern_appended_cases_without_moving_prior_work(role_db, grouped):
    from ra_triage_dashboard.app.db_parts.role_version_tasks import sampled
    db = role_db
    iid, binding = choose(db)
    cid = binding["campaign_id"]
    submit(db, iid, binding["assignee"])
    names = ("jasperchen","liangxianghui","yupuxue_v","zhangxuzhao_v")
    body = request(db, cid, names=names)
    body["assignees"] = [dict(name=p, review_percent=w) for p,w in zip(names,(30,10,45,15))]
    if grouped:
        current = db.get_campaign_allocation(cid)
        assert [(group["group_id"], group["coverage_percent"]) for group in current["groups"]] == [("rd", 100), ("te", 100)]
        body["groups"] = [dict(group_id=role, coverage_percent=100,
                               members=[dict(name=first, review_percent=75), dict(name=second, review_percent=25)])
                          for role, first, second in [("rd", *names[:2]), ("te", *names[2:])]]
    apply(db, body)
    preserved = snapshot(db, ["review_work_assignments","label_revisions","model_review_revisions"])
    existing = [row["issue_id"] for row in db.version_dataset_gallery_rows("release-20261106-odd2")]
    needed = 100 - db.get_campaign_allocation(cid)["member_count"]
    ids = [f"cn{n}" for n in range(1000,1200) if not sampled("a"*64,"20261106",f"cn{n}")][:needed]
    rid = db.ensure_version_stream("20261106", "test")
    db.append_version_predictions(run_id=rid, rows=[dict(issue_id=i, model_label="误触发", model_confidence=.7,
        model_extra=dict(software_version="1.gen4-release-20261106.1")) for i in ids])
    db.append_version_campaign_members(family="20261106",
        policy=dict(sampling_policy="version_probability_v3", seed="a"*64), issue_ids=ids,
        current_target_ids=existing+ids, batch_key="independent-role-append", actor="test")
    assert db.get_campaign_allocation(cid)["assignment_counts"] == dict(zip(names,(75,25,75,25)))
    after = snapshot(db, list(preserved))
    assert all(row in after["review_work_assignments"] for row in preserved["review_work_assignments"])
    assert after["label_revisions"] == preserved["label_revisions"]
    assert after["model_review_revisions"] == preserved["model_review_revisions"]


def test_formal_task_can_save_and_append_role_neutral_groups(role_db):
    from ra_triage_dashboard.app.db_parts.role_version_tasks import sampled

    db = role_db
    iid, binding = choose(db)
    cid = binding["campaign_id"]
    rd, te = binding["assignees"]
    submit(db, iid, rd)
    submit(db, iid, te)
    frozen = next(r for r in db.version_dataset_gallery_rows("release-20261106-odd2")
                  if r["issue_id"] != iid and r["binding"]["campaign_id"] == cid)
    frozen_iid = frozen["issue_id"]
    submit(db, frozen_iid, frozen["binding"]["assignee"])
    frozen_context = db.human_label_context(frozen_iid)
    db.adjudicate_issue_label(baseline_scope=frozen_context["scope"]["baseline_scope"], issue_id=frozen_iid,
        expected_output="正确触发", rationale="existing decision", actor="jasperchen", actor_source="test",
        actor_verified=True, expected_source_fingerprint=frozen_context["source_fingerprint"])
    frozen_context = db.human_label_context(frozen_iid)

    db.set_access_user(username="extra_te", role="writer", annotation_role="te", actor="test")
    current = db.get_campaign_allocation(cid)
    other_te = next(p["name"] for p in current["groups"][1]["members"] if p["name"] != te)
    additional = [
        dict(group_id="group-1", coverage_percent=50, coverage_strategy="fill",
             members=[dict(name="observer", review_percent=50), dict(name=other_te, review_percent=50)]),
        dict(group_id="group-2", coverage_percent=25, members=[dict(name="extra_te", review_percent=100)]),
    ]
    body = request(db, cid, basis="remaining", names=(rd, te))
    body["groups"] = [*current["groups"], *additional]
    body["cross_groups"] = [dict(issue_ids=[iid], members=[
        dict(group_id="rd", name=rd), dict(group_id="group-1", name="observer"),
    ])]
    tables = ["label_revisions", "model_review_revisions", "combined_review_progress",
              "human_vote_roles", "issue_label_decisions"]
    saved = snapshot(db, tables)
    original = db.human_label_context(iid)
    result = apply(db, body)
    case_count = current["member_count"]
    third, fourth = round(.50 * case_count), round(.25 * case_count)
    assert result["preview"]["total_slots"] == 2 * case_count + third + fourth
    assert result["preview"]["completed_slots"] == 3
    allocation = db.get_campaign_allocation(cid)
    assert [(g["group_id"], g["coverage_percent"]) for g in allocation["groups"]] == [
        ("rd", 100), ("te", 100), ("group-1", 50), ("group-2", 25)]
    assert allocation["group_rules"] == body["cross_groups"]
    assert db.human_label_context(iid)["lanes"]["te"]["fingerprint"] == original["lanes"]["te"]["fingerprint"]
    assert {row["username"] for row in db.human_label_context(iid)["members"]} >= {rd, te, "observer"}
    updated_frozen = db.human_label_context(frozen_iid)
    assert updated_frozen["members"] == frozen_context["members"]
    assert updated_frozen["lanes"]["arbitrated"] == frozen_context["lanes"]["arbitrated"]
    assert snapshot(db, tables) == saved

    # The next packet fills these percentages cumulatively without rewriting any prior owner.
    assigned = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    targets = db.version_dataset_gallery_rows("release-20261106-odd2")
    policy = dict(sampling_policy="version_probability_v3", seed="a" * 64)
    fresh = [f"cn{i}" for i in range(500, 520) if not sampled(policy["seed"], "20261106", f"cn{i}")]
    rid = binding["run_id"]
    db.append_version_predictions(run_id=rid, rows=[dict(issue_id=case, model_label="误触发", model_confidence=.7,
        model_extra=dict(software_version="1.gen4-release-20261106.1")) for case in fresh])
    db.append_version_campaign_members(family="20261106", policy=policy, issue_ids=fresh,
        current_target_ids=[r["issue_id"] for r in targets] + fresh, batch_key="mixed-groups-next", actor="test")
    reread = db.get_campaign_allocation(cid)
    assert reread["expected_revision"] == allocation["expected_revision"] + 1
    assert reread["total_slots"] == 2 * (case_count + len(fresh)) + (
        round(.5 * (case_count + len(fresh))) + round(.25 * (case_count + len(fresh))))
    assert reread["group_rules"] == body["cross_groups"]
    assert reread["completed_slots"] == 3
    new_assignments = snapshot(db, ["review_work_assignments"])["review_work_assignments"]
    assert all(row in new_assignments for row in assigned)
    assert snapshot(db, tables) == saved


def test_appendable_task_requires_recipients_in_both_roles(role_db):
    db = role_db
    iid, binding = choose(db)
    for person in binding["assignees"]:
        submit(db, iid, person)
    cid = binding["campaign_id"]
    with pytest.raises(ValueError, match="RD and TE"):
        db.preview_campaign_allocation(**request(db, cid, names=("jasperchen", "liangxianghui")))


def test_single_assignment_api_cannot_remove_formal_role_coverage(role_db):
    db = role_db
    iid, binding = choose(db)
    cid = binding["campaign_id"]
    ctx = db.human_label_context(iid)
    source = next(p["username"] for p in ctx["members"] if p["role"] == "rd")
    target = next(p for p in ("yupuxue_v","zhangxuzhao_v") if p not in binding["assignees"])
    before = snapshot(db, ["review_work_assignments", "human_assignment_roles"])
    with pytest.raises(ValueError, match="RD and TE"):
        db.update_campaign_assignment(campaign_id=cid, issue_id=iid, action="reassign",
            actor="jasperchen", expected_revision=db.get_campaign_allocation(cid)["expected_revision"],
            idempotency_key="wrong-role-transfer", from_assignee=source, assignee=target)
    assert snapshot(db, list(before)) == before


def test_version_append_invalidates_preview(role_db):
    db = role_db
    _, binding = choose(db)
    cid = binding["campaign_id"]
    body = request(db, cid, names=("jasperchen","liangxianghui","yupuxue_v","zhangxuzhao_v"))
    preview = db.preview_campaign_allocation(**body)
    from ra_triage_dashboard.app.db_parts.role_version_tasks import sampled
    policy = dict(sampling_policy="version_probability_v3", seed="a"*64)
    iid = next(f"cn{n}" for n in range(300,400) if not sampled(policy["seed"],"20261106",f"cn{n}"))
    rid = db.ensure_version_stream("20261106", "test")
    db.append_version_predictions(run_id=rid, rows=[dict(issue_id=iid, model_label="误触发", model_confidence=.7,
        model_extra=dict(software_version="1.gen4-release-20261106.1"))])
    db.append_version_campaign_members(family="20261106", policy=policy, issue_ids=[iid],
        current_target_ids=[iid], batch_key="preview-race", actor="test")
    before = snapshot(db, ["review_work_assignments", "campaign_config_revisions"])
    with pytest.raises(CampaignConflictError):
        apply(db, body, preview)
    assert snapshot(db, list(before)) == before


def test_minimum_transfer_and_feasible_quota_against_small_exhaustive_oracle():
    rows = [dict(issue_id=str(i), assignee="ab"[i%2], assignment_kind="base", ordinal=i) for i in range(5)]
    protected = {("0","a")}
    for basis in ("remaining","total"):
        for weights in [dict(a=1,b=1,c=1), dict(a=0,b=1,c=2),dict(a=3,b=1,c=1)]:
            actual, summary = reallocate_slots(rows,weights,basis=basis,protected=protected,completed=protected)
            q = {p["name"]:p["quota"] for p in summary}
            def score(owners):
                pending = Counter(owners[1:])
                return (sum(abs(pending[p]-q[p]) for p in q),
                        sum(owners[i] != rows[i]["assignee"] for i in range(5)))
            best = min(score(("a",*tail)) for tail in product([p for p in weights if weights[p]],repeat=4))
            assert score(tuple(next(r["assignee"] for r in actual if r["issue_id"] == str(i)) for i in range(5))) == best


def test_orthogonal_cross_pairing_and_set_union_round_trip_without_doubling(role_db):
    from ra_triage_dashboard.app.group_allocation import normalize_groups, plan_groups
    from ra_triage_dashboard.app.version_review_tasks import version_tasks

    # 1. Pure orthogonal 50/50 x 50/50 pairing + cross-group shared member
    cases = [f"case-{i:03d}" for i in range(80)]
    elig = {"a", "b", "c", "d"}
    g_orth = normalize_groups([
        dict(group_id="g1", coverage_percent=100, members=[dict(name="a", review_percent=50), dict(name="b", review_percent=50)]),
        dict(group_id="g2", coverage_percent=100, members=[dict(name="c", review_percent=50), dict(name="d", review_percent=50)]),
    ], elig)
    _, placed, _ = plan_groups(cases, g_orth, [], seed=19)
    assert dict(Counter((o["g1"], o["g2"]) for o in placed.values())) == {
        ("a", "c"): 20, ("a", "d"): 20, ("b", "c"): 20, ("b", "d"): 20,
    }
    g_shared = normalize_groups([
        dict(group_id="g1", coverage_percent=100, members=[dict(name="a", review_percent=50), dict(name="b", review_percent=50)]),
        dict(group_id="g2", coverage_percent=100, members=[dict(name="b", review_percent=50), dict(name="c", review_percent=50)]),
    ], elig)
    rows_shared, placed_shared, _ = plan_groups(cases, g_shared, [], seed=19)
    assert dict(Counter(r["assignee"] for r in rows_shared)) == {"a": 40, "b": 80, "c": 40}
    assert all(o["g1"] != o["g2"] for o in placed_shared.values())

    # 2. Formal task shrink 2 -> 1 (with conflict & set union) and restore 1 -> 2 without 2x inflation
    db = role_db
    iid, binding = choose(db)
    cid = binding["campaign_id"]
    rd_user, te_user = binding["assignees"]
    # Submit conflicting labels on iid
    ctx_rd = db.combined_review_context(issue_id=iid, campaign_id=cid, reviewer=rd_user)
    db.submit_combined_review(
        issue_id=iid, campaign_id=cid, model_run_id=binding["run_id"],
        reviewer=rd_user, reviewer_source="test", reviewer_verified=True,
        model_review_status="completed", reason="rd view", missing_evidence=[],
        expected_output="误触发", tags=[], rationale="rd",
        expected_model_review_storage_id=ctx_rd["model_review_storage_id"],
        expected_case_revision_id=ctx_rd["case_revision_id"],
        expected_label_state_fingerprint=ctx_rd["label_state_fingerprint"],
        idempotency_key="conf-rd",
    )
    ctx_te = db.combined_review_context(issue_id=iid, campaign_id=cid, reviewer=te_user)
    db.submit_combined_review(
        issue_id=iid, campaign_id=cid, model_run_id=binding["run_id"],
        reviewer=te_user, reviewer_source="test", reviewer_verified=True,
        model_review_status="completed", reason="te view", missing_evidence=[],
        expected_output="正确触发", tags=[], rationale="te",
        expected_model_review_storage_id=ctx_te["model_review_storage_id"],
        expected_case_revision_id=ctx_te["case_revision_id"],
        expected_label_state_fingerprint=ctx_te["label_state_fingerprint"],
        idempotency_key="conf-te",
    )
    current = db.get_campaign_allocation(cid)
    n_cases = current["member_count"]
    shrink_body = request(db, cid, basis="total", names=("jasperchen", "liangxianghui"))
    shrink_body["groups"] = [dict(
        group_id="rd", coverage_percent=100,
        members=[dict(name="jasperchen", review_percent=50), dict(name="liangxianghui", review_percent=50)],
    )]
    prev_shrink = db.preview_campaign_allocation(**shrink_body)
    assert prev_shrink["active_slots"] == n_cases
    assert prev_shrink["convergence"]["conflict_cases"] == 1
    apply(db, shrink_body, prev_shrink)

    card = next(t for t in version_tasks(db) if t["split_id"] == cid)
    assert card["allocation_group_count"] == 1
    assert card["assignment_count"] == n_cases
    assert card["conflict_count"] == 1
    splits = db.list_review_work_splits(limit=100)
    assert next(s for s in splits if s["split_id"] == cid)["allocation_group_count"] == 1

    # Restore 2 groups: quotas must total exactly 2 * n_cases with zero doubling
    restore_body = request(db, cid, basis="total", names=("jasperchen", "liangxianghui", "yupuxue_v", "zhangxuzhao_v"))
    restore_body["groups"] = [
        dict(group_id="g1", coverage_percent=100, members=[
            dict(name="jasperchen", review_percent=50), dict(name="liangxianghui", review_percent=50)]),
        dict(group_id="g2", coverage_percent=100, members=[
            dict(name="yupuxue_v", review_percent=50), dict(name="zhangxuzhao_v", review_percent=50)]),
    ]
    prev_rest = db.preview_campaign_allocation(**restore_body)
    assert prev_rest["active_slots"] == 2 * n_cases
    apply(db, restore_body, prev_rest)
    restored_card = next(t for t in version_tasks(db) if t["split_id"] == cid)
    assert restored_card["allocation_group_count"] == 2
    assert restored_card["assignment_count"] == 2 * n_cases


def test_paired_mode_matches_members_sequentially_and_persists(role_db):
    from ra_triage_dashboard.app.group_allocation import normalize_groups, plan_groups

    cases = [f"case-{i:03d}" for i in range(40)]
    elig = {"a", "b", "c", "d"}
    groups = normalize_groups([
        dict(group_id="g1", coverage_percent=100, members=[dict(name="a", review_percent=50), dict(name="b", review_percent=50)]),
        dict(group_id="g2", coverage_percent=100, members=[dict(name="c", review_percent=50), dict(name="d", review_percent=50)]),
    ], elig)
    _, orth_placed, _ = plan_groups(cases, groups, [], seed=7, pairing_mode="orthogonal")
    assert dict(Counter((o["g1"], o["g2"]) for o in orth_placed.values())) == {
        ("a", "c"): 10, ("a", "d"): 10, ("b", "c"): 10, ("b", "d"): 10,
    }
    _, paired_placed, _ = plan_groups(cases, groups, [], seed=7, pairing_mode="paired")
    assert dict(Counter((o["g1"], o["g2"]) for o in paired_placed.values())) == {
        ("a", "c"): 20, ("b", "d"): 20,
    }
    # Even when Group 2 is already 100% locked/completed, Group 1's movable cases still pair 1-to-1!
    g2_locked = {(cases[i], "c" if i < 20 else "d") for i in range(40)}
    _, lookahead_placed, _ = plan_groups(
        cases, groups, [], seed=7, pairing_mode="paired",
        evidence=dict(protected=g2_locked, completed=g2_locked, forbidden=set(), frozen_cases=set()),
    )
    assert dict(Counter((o["g1"], o["g2"]) for o in lookahead_placed.values())) == {
        ("a", "c"): 20, ("b", "d"): 20,
    }

    # Verify DB preview / apply / reread roundtrip for pairing_mode
    db = role_db
    _, binding = choose(db)
    cid = binding["campaign_id"]
    body = request(db, cid, basis="total", names=("jasperchen", "liangxianghui", "yupuxue_v", "zhangxuzhao_v"))
    body["groups"] = [
        dict(group_id="rd", coverage_percent=100, members=[
            dict(name="jasperchen", review_percent=50), dict(name="liangxianghui", review_percent=50)]),
        dict(group_id="te", coverage_percent=100, members=[
            dict(name="yupuxue_v", review_percent=50), dict(name="zhangxuzhao_v", review_percent=50)]),
    ]
    body["pairing_mode"] = "paired"
    prev_paired = db.preview_campaign_allocation(**body)
    assert prev_paired["pairing_mode"] == "paired"
    combos_paired = {tuple(item["owners"]): item["count"] for item in prev_paired["group_coverage"]["combinations"]}
    assert combos_paired.get(("jasperchen", "yupuxue_v"), 0) + combos_paired.get(("liangxianghui", "zhangxuzhao_v"), 0) == prev_paired["group_coverage"]["case_count"]
    apply(db, body, prev_paired)
    assert db.get_campaign_allocation(cid)["pairing_mode"] == "paired"

    # Revert to orthogonal cleanly
    body2 = request(db, cid, basis="total", names=("jasperchen", "liangxianghui", "yupuxue_v", "zhangxuzhao_v"))
    body2["groups"] = body["groups"]
    body2["pairing_mode"] = "orthogonal"
    prev_orth = db.preview_campaign_allocation(**body2)
    assert prev_orth["pairing_mode"] == "orthogonal"
    apply(db, body2, prev_orth)
    assert db.get_campaign_allocation(cid)["pairing_mode"] == "orthogonal"

@pytest.mark.parametrize("basis", ["remaining", "total"])
def test_unrelated_issue_decision_retains_evidence_and_moves_only_untouched_work(fixture, basis):
    db = fixture.db
    cid, ids = make_task(fixture, count=4, completed=1, purpose="model_review")
    # Bob's pending Case has a personal decision. The other two have
    # task-bound and unknown decision sources, respectively.
    with db.connect() as conn:
        for iid, task_id in zip(ids[1:], ["", cid, None]):
            sources = []
            if task_id is not None:
                case_id = f"source-{iid}"
                conn.execute("INSERT INTO label_cases(id,baseline_scope,issue_id,task_id,created_at) "
                             "VALUES(?,'scope',?,?,CURRENT_TIMESTAMP)", (case_id, iid, task_id))
                sources.append(case_id)
            conn.execute("INSERT INTO issue_label_decisions(baseline_scope,issue_id,expected_output,"
                         "source_case_ids_json,source_fingerprint,created_at) "
                         "VALUES('scope',?,'误触发',?,'test',CURRENT_TIMESTAMP)", (iid, json.dumps(sources)))
    evidence = snapshot(db, ["issue_label_decisions", "combined_review_progress", "model_review_revisions"])
    current = db.get_campaign_allocation(cid)
    assert current["movable_slots"] == 1
    body = request(db, cid, basis=basis)
    shares = [0, 0, 0, 0, 100] if basis == "remaining" else [25, 0, 25, 25, 25]
    body["groups"] = [{**current["groups"][0], "members": [
        dict(name=name, review_percent=share) for name, share in zip(("alice", "bob", "c", "d", "e"), shares)
    ]}]
    preview = db.preview_campaign_allocation(**body)
    assert preview["changes"] == [dict(issue_id=ids[1], before=["bob"], after=["e"])]
    apply(db, body, preview)
    after = db.get_campaign_allocation(cid)
    assert after["assignment_counts"] == {"alice": 1, "c": 1, "d": 1, "e": 1}
    assert after["group_coverage"] == preview["group_coverage"]
    assert after["active_assignment_counts"] == after["assignment_counts"]
    assert snapshot(db, list(evidence)) == evidence
