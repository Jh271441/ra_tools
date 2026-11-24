from copy import deepcopy
import pytest
from app.services import scenario_label_sets as tags, metric_profiles as profiles
from app import publish_scenario_labels as pub
from test_auto_triage_metrics import db


def revision():
    ctx = {
        "release": "gen4-release-20261016",
        "profile_id": "auto_triage_sql_v2",
        "date_start": "2026-09-19",
        "date_end": "2026-10-28",
    }
    cases = [
        ("cn1", 2, "正确触发", ["101"]),
        ("cn2", 2, "误触发", ["102"]),
        ("cn3", 3, "成功", []),
        ("cn4", 2, None, []),
    ]
    rows = []
    scenes = []
    issues = []
    for iid, trigger, label, ids in cases:
        flags = profiles.membership(profiles.DEFAULT_CONFIG, trigger, label)
        rows.append(
            {
                "issue_id": iid,
                "ra_type": trigger,
                "auto_label": label,
                "auto_memberships": flags,
                "eligible": bool(flags["precision_denominator"] or flags["recall_denominator"]),
                "scenario_ids": ids,
            }
        )
        issues.append({"issue_id": iid, "trip_id": "trip-" + iid})
        scenes.extend(
            {
                "scenario_id": sid,
                "issue_id": iid,
                "scenario_revision": 0,
                "start_timestamp": 1,
                "end_timestamp": 2,
            }
            for sid in ids
        )
    return {
        "context": ctx,
        "profile": deepcopy(profiles.BUILTIN),
        "revision_key": "rev1",
        "reconciliation": {"status": "matched"},
        "rows": rows,
        "payload": {"issues": issues, "scenarios": scenes},
    }


def live(scene):
    return {
        "id": int(scene["scenario_id"]),
        "version": 0,
        "name": "original-name",
        "scenario": "original-proto",
        "start_timestamp": 1,
        "end_timestamp": 2,
        "trip_id": "trip-" + scene["issue_id"],
        "is_deleted": False,
        "review_status": 2,
        "labels": ["#" + scene["issue_id"].removeprefix("cn"), "original-label"],
    }


def test_distinct_memberships_become_real_query_labels_without_common_tp():
    value = revision()
    before = deepcopy(value)
    plan = tags.build_plan(value)
    correct = plan["scenarios"][0]
    prefix = plan["namespace"]
    assert prefix + "_precision_numerator" not in correct["add_labels"]
    assert {
        prefix + "_precision_denominator",
        prefix + "_recall_numerator",
        prefix + "_recall_denominator",
        prefix + "_AutoTrigger",
    } <= set(correct["add_labels"])
    assert (
        plan["pending_issues"] == ["cn3"]
        and plan["eligible_issues"] == 3
        and plan["mapped_issues"] == 2
    )
    assert value == before


def test_new_rules_scope_or_membership_change_namespace_but_platform_annotations_do_not():
    original = revision()
    base = tags.build_plan(original)
    original["payload"]["scenarios"][0]["scenario_labels"] = ["arbitrary-platform-tag"]
    assert tags.build_plan(original)["id"] == base["id"]
    for field in ("config", "scope", "label"):
        changed = deepcopy(original)
        if field == "config":
            changed["profile"]["config_hash"] = "new-rules"
        elif field == "scope":
            changed["context"]["date_start"] = "2026-09-20"
        else:
            changed["rows"][0]["auto_label"] = "explicitly-mapped"
        assert tags.build_plan(changed)["namespace"] != base["namespace"]


@pytest.mark.parametrize(
    "field,value",
    [("version", 1), ("scenario", "changed-proto"), ("review_status", 1), ("name", "changed-name")],
)
def test_annotation_update_must_not_change_physical_inputs_or_revision(field, value):
    expected = tags.build_plan(revision())["scenarios"][0]
    before = live(expected)
    after = deepcopy(before)
    after["labels"] += expected["add_labels"]
    after[field] = value
    with pytest.raises(ValueError):
        tags.verify_after(before, after, expected)


def test_preserves_every_original_tag_and_rejects_wrong_membership_or_issue():
    expected = tags.build_plan(revision())["scenarios"][0]
    before = live(expected)
    after = deepcopy(before)
    after["labels"] += expected["add_labels"]
    tags.verify_after(before, after, expected)
    for values in (
        [v for v in after["labels"] if v != "original-label"],
        after["labels"] + [expected["add_labels"][0] + "_precision_numerator"],
        ["#999", *expected["add_labels"]],
    ):
        after["labels"] = values
        with pytest.raises(ValueError):
            tags.verify_after(before, after, expected)


class FakePlatform:
    def __init__(self, plan):
        self.rows = {s["scenario_id"]: live(s) for s in plan["scenarios"]}
        self.writes = []
        self.fail = False

    def query(self, ids=None, label=None):
        values = [deepcopy(row) for sid, row in self.rows.items() if ids is None or sid in ids]
        return [row for row in values if label is None or label in row["labels"]]

    def append(self, row, expected):
        self.writes.append(expected["scenario_id"])
        if self.fail:
            raise TimeoutError("ambiguous")
        self.rows[expected["scenario_id"]]["labels"] = sorted(
            tags.labels(row) | set(expected["add_labels"])
        )


def test_preview_is_read_only_and_rejects_entire_invalid_batch_before_writing(tmp_path):
    plan = tags.build_plan(revision())
    platform = FakePlatform(plan)
    result = pub.publish(plan, platform, tmp_path)
    assert result["scenario_count"] == 2 and not platform.writes
    platform.rows["102"]["version"] = 99
    with pytest.raises(ValueError):
        pub.publish(plan, platform, tmp_path, apply=True, canary_only=True)
    assert not platform.writes


def test_idempotent_canary_and_ambiguous_mutation_never_automatically_retry(tmp_path):
    plan = tags.build_plan(revision())
    platform = FakePlatform(plan)
    pub.publish(plan, platform, tmp_path, apply=True, canary_only=True)
    pub.publish(plan, platform, tmp_path, apply=True, canary_only=True)
    assert platform.writes == ["101"]
    platform = FakePlatform(plan)
    platform.fail = True
    with pytest.raises(TimeoutError):
        pub.publish(plan, platform, tmp_path / "error", apply=True, canary_only=True)
    assert platform.writes == ["101"]


def test_browser_reads_only_verified_matching_context_receipts(db):
    value = revision()
    plan = tags.build_plan(value)
    verified = {s["scenario_id"]: live(s) for s in plan["scenarios"]}
    for scene in plan["scenarios"]:
        verified[scene["scenario_id"]]["labels"] += scene["add_labels"]
    tags.save_verified(db, plan, verified)
    ctx = plan["context"]
    result = tags.issue_labels(db, ctx, "cn1", "rev1")
    assert result["status"] == "complete" and result["items"][0]["scenario_id"] == "101"
    assert tags.issue_labels(db, ctx, "cn3", "rev1")["status"] == "pending"
    assert tags.issue_labels(db, ctx, "cn4", "rev1")["status"] == "excluded"
    assert tags.issue_labels(db, ctx, "cn1", "new-revision")["status"] == "stale"
    assert tags.issue_labels(db, ctx, "cn1", "new-revision", plan["id"])["status"] == "complete"
    assert not tags.issue_labels(db, {**ctx, "date_start": "2026-09-20"}, "cn1", "rev1")["items"]


def test_full_publication_queries_namespace_before_writing_receipts(db, tmp_path, monkeypatch):
    from contextlib import nullcontext

    plan = tags.build_plan(revision())
    platform = FakePlatform(plan)
    monkeypatch.setattr(pub, "SessionLocal", lambda: nullcontext(db))
    result = pub.publish(plan, platform, tmp_path, apply=True)
    assert result["status"] == "complete" and result["query_verified"]
    assert tags.issue_labels(db, plan["context"], "cn1", "rev1")["status"] == "complete"
    assert len(platform.writes) == 2


def test_authenticated_api_reads_database_receipt_without_platform_calls(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.api.evaluation_routes import router
    from app.services import evaluation_pipeline as pipeline, release_workflow as w

    value = revision()
    plan = tags.build_plan(value)
    verified = {s["scenario_id"]: live(s) for s in plan["scenarios"]}
    for scene in plan["scenarios"]:
        verified[scene["scenario_id"]]["labels"] += scene["add_labels"]
    tags.save_verified(db, plan, verified)
    w.put_state(db, "test-context", {"revision_key": "rev1"})
    monkeypatch.setattr(pipeline, "current_revision", lambda *a, **k: value)
    monkeypatch.setattr(
        pipeline, "context", lambda *a, **k: (value["context"], None, None, "test-context")
    )
    monkeypatch.setattr(
        pub, "Platform", lambda: pytest.fail("Browser GET must never call Scenario")
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get(
            "/api/dashboard/evaluation/scenario-labels",
            params={**value["context"], "issue_id": "cn1"},
        )
        assert response.status_code == 200 and response.json()["status"] == "complete"
        assert (
            response.json()["items"][0]["autotriage_labels"] == plan["scenarios"][0]["add_labels"]
        )
        assert (
            client.get(
                "/api/dashboard/evaluation/scenario-labels", params={"issue_id": "x" * 101}
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "read_only,status,attempts", [(False, 596, 1), (True, 596, 3), (True, 401, 1)]
)
def test_only_transient_reads_retry_and_platform_writes_never_repeat(
    read_only, status, attempts, monkeypatch
):
    from types import SimpleNamespace
    import requests

    class Session:
        count = 0

        def post(self, *a, **kw):
            self.count += 1
            response = requests.Response()
            response.status_code = status
            raise requests.HTTPError(response=response)

    client = pub.Platform.__new__(pub.Platform)
    client.api = SimpleNamespace(_sign_for_json_string=lambda _: "test-sign")
    client.session = Session()
    monkeypatch.setattr(pub.time, "sleep", lambda _: None)
    with pytest.raises(requests.HTTPError):
        client.post("test://scenario", {}, read_only=read_only)
    assert client.session.count == attempts


def test_resume_receipt_can_only_allow_never_attempted_scenes(db, tmp_path, monkeypatch):
    from contextlib import nullcontext
    from app.services.release_cycle import digest

    plan = tags.build_plan(revision())
    platform = FakePlatform(plan)
    platform.rows["101"]["labels"] += plan["scenarios"][0]["add_labels"]
    value = {
        "plan_id": plan["id"],
        "confirmed_ids": ["101"],
        "previously_attempted_ids": ["101"],
        "allowed_ids": ["102"],
    }
    value["verification_hash"] = digest(value)
    allowed = pub.resume_allowlist(plan, value)
    monkeypatch.setattr(pub, "SessionLocal", lambda: nullcontext(db))
    pub.publish(plan, platform, tmp_path, apply=True, allowed_ids=allowed)
    assert platform.writes == ["102"]
    value["allowed_ids"] = ["101", "102"]
    value["verification_hash"] = digest(
        {k: v for k, v in value.items() if k != "verification_hash"}
    )
    with pytest.raises(ValueError):
        pub.resume_allowlist(plan, value)


def test_canary_uses_explicit_scene_choice_and_cannot_escape_plan(tmp_path):
    plan = tags.build_plan(revision())
    platform = FakePlatform(plan)
    pub.publish(plan, platform, tmp_path, apply=True, canary_only=True, canary_scenario_id="102")
    assert platform.writes == ["102"]
    with pytest.raises(ValueError):
        pub.publish(
            plan, platform, tmp_path, apply=True, canary_only=True, canary_scenario_id="999"
        )
    assert platform.writes == ["102"]
