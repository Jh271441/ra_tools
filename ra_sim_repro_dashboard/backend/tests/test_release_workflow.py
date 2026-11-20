from copy import deepcopy
from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models import ReleaseIssueSnapshot
from app.services import release_workflow as w, release_source as source
from app.services.release_cycle import (
    reference_thursday,
    resolve_current,
    query_contract,
    real_labels,
)


@pytest.fixture
def config():
    anchor = reference_thursday()
    return {
        "contract": {
            "verified": True,
            "reference": "test evidence",
            "view_id": 2410,
            "time_field": "issue_time",
        },
        "periods": [
            {
                "release": "gen4-release-20260918",
                "status": "completed",
                "verified": True,
                "evidence": "test run record",
                "cycle_end": anchor.isoformat(),
                "case_start": (anchor - timedelta(days=14)).isoformat()
                + "T00:00:00+08:00",
                "case_end_exclusive": anchor.isoformat() + "T00:00:00+08:00",
                "binary_id": 123,
                "template_job_id": 456,
                "binary_evidence": "test release binary registry",
                "scenario_query_labels": ["ra_repro_full_20261008_20260918"],
            }
        ],
        "simulation": {"driver_command": ["test-driver"], "driver_revision": "test"},
    }


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def population(*args):
    return [
        {
            "issue_id": "i1",
            "ra_type": 2,
            "ra_merge_result": "成功",
            "issue_topic": "automatic",
        },
        {"issue_id": "i2", "ra_type": 3, "ra_merge_result": "成功"},
    ]


def scene_labels(cohort):
    prefix = "ra_repro_full_20261008_20260918"
    trigger = "ManualTrigger" if cohort == "positive_manual" else "AutoTrigger"
    return [prefix, prefix + "_gen4-release-20260918", prefix + "_" + cohort, prefix + "_" + trigger]


def scenarios(*args):
    return [
        {
            "scenario_id": "1",
            "issue_id": "i1",
            "scenario_name": "scene one",
            "scenario_labels": scene_labels("positive_auto") + ["actual-tag"],
        },
        {
            "scenario_id": "2",
            "issue_id": "i2",
            "scenario_name": "scene two",
            "scenario_labels": scene_labels("positive_manual") + ["manual-tag"],
        },
    ]


def seed(db, config):
    return w.sync_once(db, config, population, scenarios)


@pytest.mark.parametrize("labels", [[], scene_labels("negative_auto"), scene_labels("positive_auto") + ["ra_repro_cycle_20261008_0918"]])
def test_plan_blocks_missing_or_conflicting_canonical_labels(db, config, labels):
    seed(db, config)
    snapshot = db.scalars(select(ReleaseIssueSnapshot)).first()
    value = deepcopy(snapshot.payload)
    value["scenarios"][0]["scenario_labels"] = labels
    snapshot.payload = value
    db.commit()
    with pytest.raises(ValueError, match="label"):
        w.make_plan(db, config)


def test_calendar_anchor_not_release_date():
    assert reference_thursday(date(2026, 9, 30)) == date(2026, 9, 24)
    assert reference_thursday(date(2026, 10, 1)) == date(2026, 9, 24)
    assert reference_thursday(date(2026, 10, 5)) == date(2026, 10, 1)


@pytest.mark.parametrize("days", [7, 14])
def test_full_period_kept(config, days):
    p = config["periods"][0]
    p["case_start"] = (
        date.fromisoformat(p["cycle_end"]) - timedelta(days=days)
    ).isoformat() + "T00:00:00+08:00"
    assert resolve_current(config)["status"] == "ready"
    filters = query_contract(config, p)
    times = filters[-1]["val"]
    assert times["max"] - times["min"] + 1 == days * 86400000
    assert next(f for f in filters if f["attr_id"] == "ra_type")["val"] == [2]
    assert next(
        f for f in query_contract(config, p, True) if f["attr_id"] == "ra_type"
    )["val"] == [2, 3]


def test_no_guess_on_missing_unverified_or_ambiguous(config):
    assert resolve_current({"periods": []})["current_version"] is None
    config["periods"][0]["verified"] = False
    assert resolve_current(config)["current_version"] is None
    config["periods"][0]["verified"] = True
    config["periods"].append(deepcopy(config["periods"][0]))
    assert resolve_current(config)["current_version"] is None


def test_overlap_and_timezone_block(config):
    other = deepcopy(config["periods"][0])
    other["cycle_end"] = "2000-01-06"
    config["periods"].append(other)
    assert resolve_current(config)["status"] == "pending_verification"
    config["periods"].pop()
    config["periods"][0]["case_start"] = "2026-01-01T00:00:00"
    assert resolve_current(config)["status"] == "pending_verification"


def test_labels_are_real_only():
    assert real_labels(
        {"source_labels": ["synthetic"], "labels": "actual, second,actual"}
    ) == ["actual", "second"]
    assert real_labels({"source_labels": ["release", "cohort"]}) == []


def test_snapshot_atomic_and_idempotent(db, config):
    old = seed(db, config)
    assert seed(db, config).id == old.id
    with pytest.raises(ValueError):
        w.sync_once(db, config, lambda *_: [], scenarios)
    assert len(db.scalars(select(ReleaseIssueSnapshot)).all()) == 1


def test_plan_uses_configured_concurrency_and_cancelled_job_allows_replacement(
    db, config, monkeypatch
):
    from app.models import ReleaseSimulationBatch

    seed(db, config)
    old = w.make_plan(db, config)
    batch = ReleaseSimulationBatch(
        fingerprint=old["fingerprint"],
        release=old["release"],
        status="running",
        payload={**old, "job_id": 99},
    )
    db.add(batch)
    db.commit()
    monkeypatch.setattr(
        w,
        "driver_call",
        lambda *_: {
            "fingerprint": old["fingerprint"],
            "job_id": 99,
            "status": "cancelled",
        },
    )
    w.poll_batches(db, config)
    assert batch.status == "cancelled"
    config["simulation"]["max_concurrency"] = 1000
    new = w.make_plan(db, config)
    assert (
        new["simulation"]["max_concurrency"] == 1000
        and new["fingerprint"] != old["fingerprint"]
    )
    assert (
        new["scenarios"] == old["scenarios"]
        and new["population_hash"] == old["population_hash"]
    )
    assert w.queue_plan(db, new["fingerprint"], config).status == "queued"


def test_priority_is_scoped_to_release_and_part_of_plan_identity(db, config):
    seed(db, config)
    old = w.make_plan(db, config)
    assert old["simulation"]["priority"] == "NORMAL"
    config["simulation"]["priorities_by_release"] = {"gen4-release-20260918": "HIGH"}
    new = w.make_plan(db, config)
    assert (
        new["simulation"]["priority"] == "HIGH"
        and new["fingerprint"] != old["fingerprint"]
    )
    assert (
        old["population_hash"] == new["population_hash"]
        and old["scenarios"] == new["scenarios"]
    )
    config["simulation"]["priorities_by_release"] = {"other-release": "HIGH"}
    assert w.make_plan(db, config)["simulation"]["priority"] == "NORMAL"


def test_issue_visible_without_sim_and_manual_separate(db, config, monkeypatch):
    seed(db, config)
    monkeypatch.setattr(w, "load_cycle_config", lambda: config)
    result = w.list_issues(db)
    assert result["total"] == 1
    assert result["items"][0]["sim_triggered"] is None
    assert result["items"][0]["precision_label"] is None
    assert result["items"][0]["scenario_labels"] == scene_labels("positive_auto") + ["actual-tag"]
    assert w.list_issues(db, label="synthetic")["total"] == 0
    assert w.status(db)["manual_population_count"] == 1


def test_mapping_failure_keeps_issues_blocks_submission(db, config, monkeypatch):
    def fail(*args):
        raise RuntimeError("network")

    w.sync_once(db, config, population, fail)
    monkeypatch.setattr(w, "load_cycle_config", lambda: config)
    assert w.list_issues(db)["items"][0]["simulation_status"] == "pending_mapping"
    with pytest.raises(ValueError, match="场景映射查询失败"):
        w.make_plan(db, config)


def test_changed_contract_hides_stale_population(db, config, monkeypatch):
    seed(db, config)
    config["contract"]["reference"] = "new contract"
    monkeypatch.setattr(w, "load_cycle_config", lambda: config)
    assert w.list_issues(db)["total"] == 0


def test_submit_idempotence_and_stale_plan(db, config, monkeypatch):
    seed(db, config)
    plan = w.make_plan(db, config)
    calls = []

    def driver(config, action, payload):
        calls.append(action)
        return {"fingerprint": payload["fingerprint"], "ready": True, "job_id": 99}

    monkeypatch.setattr(w, "driver_call", driver)
    assert w.submit_plan(db, plan["fingerprint"], config).status == "running"
    assert w.submit_plan(db, plan["fingerprint"], config).status == "running"
    assert calls == ["preflight", "submit"]
    config["periods"][0]["binary_id"] = 124
    with pytest.raises(ValueError):
        w.submit_plan(db, plan["fingerprint"], config)


def test_uncertain_submission_not_retried(db, config, monkeypatch):
    seed(db, config)
    plan = w.make_plan(db, config)

    def driver(config, action, payload):
        if action == "submit":
            raise TimeoutError()
        return {"fingerprint": payload["fingerprint"], "ready": True}

    monkeypatch.setattr(w, "driver_call", driver)
    assert (
        w.submit_plan(db, plan["fingerprint"], config).status == "submission_uncertain"
    )
    monkeypatch.setattr(w, "driver_call", lambda *_: pytest.fail("must not retry"))
    assert (
        w.submit_plan(db, plan["fingerprint"], config).status == "submission_uncertain"
    )


def test_auto_mode_requires_scheduler_and_driver(db, config, monkeypatch):
    seed(db, config)
    monkeypatch.setattr(w, "load_cycle_config", lambda: config)
    monkeypatch.setattr(
        w,
        "driver_call",
        lambda c, a, p: {"ready": True, "fingerprint": p["fingerprint"]},
    )
    monkeypatch.delenv("RELEASE_WORKFLOW_ENABLED", raising=False)
    with pytest.raises(ValueError):
        w.set_mode(db, "auto")
    monkeypatch.setenv("RELEASE_WORKFLOW_ENABLED", "1")
    w.set_mode(db, "auto")
    assert w.status(db)["mode"] == "auto"
    w.set_mode(db, "manual")
    assert w.status(db)["mode"] == "manual"


def test_partial_upstream_fails(monkeypatch):
    pages = iter([{"total": 2, "res": [{"issue_id": "1"}]}, {"total": 2, "res": []}])
    monkeypatch.setattr(source, "signed_query", lambda *args: next(pages))
    with pytest.raises(RuntimeError):
        source.complete_query("url", {}, "id", "token", "issue_id")


def test_duplicate_upstream_fails(monkeypatch):
    monkeypatch.setattr(
        source,
        "signed_query",
        lambda *args: {"total": 2, "res": [{"id": "1"}, {"id": "1"}]},
    )
    with pytest.raises(RuntimeError):
        source.complete_query("url", {}, "id", "token", "id")


def test_switch_only_monday_and_retain_completed_release(config):
    p = config["periods"][0]
    p.update(
        cycle_end="2026-09-24",
        case_start="2026-09-10T00:00:00+08:00",
        case_end_exclusive="2026-09-25T00:00:00+08:00",
    )
    following = dict(
        p,
        release="next-release",
        cycle_end="2026-10-01",
        case_start="2026-09-24T00:00:00+08:00",
        case_end_exclusive="2026-10-02T00:00:00+08:00",
    )
    config["periods"].append(following)
    for day in [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 4)]:
        assert resolve_current(config, day)["current_version"] == "gen4-release-20260918"
    assert (
        resolve_current(config, date(2026, 10, 5))["current_version"] == "next-release"
    )
    following["status"] = "running"
    value = resolve_current(config, date(2026, 10, 5))
    assert value["current_version"] == "gen4-release-20260918"
    assert value["retained_previous"] is True


def test_cross_release_cutover_overlap_allowed(config):
    p = config["periods"][0]
    earlier = dict(
        p,
        release="earlier-release",
        cycle_end=(date.fromisoformat(p["cycle_end"]) - timedelta(days=7)).isoformat(),
    )
    config["periods"].append(earlier)
    assert resolve_current(config)["status"] == "ready"


def test_inferred_current_distinct_from_verified(config):
    config["periods"][0].update(verified=False, basis="inferred")
    value = resolve_current(config)
    assert value["current_version"] == "gen4-release-20260918"
    assert value["period_verified"] is False


def test_partial_artifact_never_submits(db, config, monkeypatch):
    seed(db, config)
    snapshot = db.scalars(select(ReleaseIssueSnapshot)).first()
    snapshot.payload = {**snapshot.payload, "population_complete": False}
    db.commit()
    with pytest.raises(ValueError, match="完整采集"):
        w.make_plan(db, config)


def test_missing_period_verification_blocks_submit_but_not_source_sync(db, config):
    config["periods"][0].update(verified=False, basis="inferred")
    seed(db, config)
    with pytest.raises(ValueError, match="推断值"):
        w.make_plan(db, config)


def test_unclassified_gt_prevents_full_metrics(db, config):
    w.sync_once(
        db,
        config,
        lambda *_: [{"issue_id": "i1", "ra_type": 2, "ra_merge_result": "待确认"}],
        scenarios,
    )
    with pytest.raises(ValueError, match="GT"):
        w.make_plan(db, config)


def test_poll_completion_quality_and_manual_tracking(db, config, monkeypatch):
    from app.models import ReleaseSimulationBatch

    seed(db, config)
    plan = w.make_plan(db, config)
    batch = ReleaseSimulationBatch(
        fingerprint=plan["fingerprint"],
        release=plan["release"],
        status="running",
        payload={**plan, "job_id": 99},
    )
    db.add(batch)
    db.commit()
    results = {
        s["scenario_id"]: {
            "sim_triggered": True,
            "reproduced": s["cohort"] != "positive_manual",
            "precision_label": "TP",
        }
        for s in plan["scenarios"]
    }
    monkeypatch.setattr(
        w,
        "driver_call",
        lambda *_: {
            "fingerprint": plan["fingerprint"],
            "job_id": 99,
            "status": "complete",
            "quality_gate_passed": True,
            "results": results,
        },
    )
    w.poll_batches(db, config)
    assert batch.status == "complete"
    snapshot = db.scalars(select(ReleaseIssueSnapshot)).first()
    assert w.metrics_for_snapshot(db, snapshot)["available"] is True
    assert w.metrics_for_snapshot(db, snapshot)["eligible"] == 2


def test_poll_incomplete_coverage_not_published(db, config, monkeypatch):
    from app.models import ReleaseSimulationBatch

    seed(db, config)
    plan = w.make_plan(db, config)
    batch = ReleaseSimulationBatch(
        fingerprint=plan["fingerprint"],
        release=plan["release"],
        status="running",
        payload={**plan, "job_id": 99},
    )
    db.add(batch)
    db.commit()
    monkeypatch.setattr(
        w,
        "driver_call",
        lambda *_: {
            "fingerprint": plan["fingerprint"],
            "job_id": 99,
            "status": "complete",
            "quality_gate_passed": True,
            "results": {},
        },
    )
    w.poll_batches(db, config)
    assert batch.status == "quality_failed"
    assert not w.metrics_for_snapshot(
        db, db.scalars(select(ReleaseIssueSnapshot)).first()
    )["available"]


def test_multiple_scenarios_do_not_multiply_population():
    from app.services.release_metrics import summarize_population

    issues = [
        {"issue_id": "i1", "ra_type": 2, "ra_merge_result": "成功"},
        {"issue_id": "i2", "ra_type": 2, "ra_merge_result": "误触发"},
    ]
    scenes = [
        {"scenario_id": "1", "issue_id": "i1"},
        {"scenario_id": "2", "issue_id": "i1"},
        {"scenario_id": "3", "issue_id": "i2"},
    ]
    result = summarize_population(
        issues,
        scenes,
        {
            "1": {"sim_triggered": False},
            "2": {"sim_triggered": True},
            "3": {"sim_triggered": False},
        },
    )
    assert result["eligible"] == 2
    assert result["tp"] == 1 and result["tn"] == 1
    assert result["available"] is True


def test_metadata_and_labels_do_not_resubmit_same_population(db, config):
    from app.services.release_workflow import population_identity

    snapshot = seed(db, config)
    changed = deepcopy(snapshot.payload)
    changed["issues"][0]["issue_topic"] = "updated topic"
    changed["scenarios"][0]["scenario_labels"].append("new label")
    assert population_identity(changed) == population_identity(snapshot.payload)
    changed["issues"][0]["ra_merge_result"] = "误触发"
    assert population_identity(changed) != population_identity(snapshot.payload)


def test_actual_scenario_label_mapping_is_unambiguous():
    from app.services.release_source import scenario_issue_id

    assert (
        scenario_issue_id({"labels": ["scenario_from_issue", "#36182045"]})
        == "cn36182045"
    )
    with pytest.raises(ValueError):
        scenario_issue_id({"labels": ["#36182045", "#36182046"]})
    with pytest.raises(ValueError):
        scenario_issue_id({"issue_id": "cn1", "labels": ["#2"]})


def test_manual_false_trigger_excluded_from_recall_population():
    from app.services.release_metrics import summarize_population

    summary = summarize_population(
        [{"issue_id": "m", "ra_type": 3, "ra_merge_result": "误触发"}], [], {}
    )
    assert summary["excluded"] == 1 and summary["unclassified"] == 0
    assert summary["recall"] is None


def test_period_discovery_uses_actual_transition_dates():
    from app.services.release_catalog import infer_completed_cycles
    from datetime import datetime

    def row(release, day):
        stamp = datetime.fromisoformat(day + "T12:00:00+08:00")
        return {
            "version": f"1.gen4-release-{release}.555",
            "issue_time": int(stamp.timestamp() * 1000),
        }

    values = [
        row("20260904", "2026-09-10"),
        row("20260904", "2026-09-24"),
        row("20260918", "2026-09-24"),
        row("20260918", "2026-09-30"),
    ]
    periods, warnings = infer_completed_cycles(values)
    assert len(periods) == 1 and not warnings
    assert periods[0]["release"] == "gen4-release-20260904"
    assert periods[0]["cycle_end"] == "2026-09-24"
    assert periods[0]["case_start"].startswith("2026-09-10")


def test_period_discovery_does_not_close_release_with_late_tail():
    from app.services.release_catalog import infer_completed_cycles
    from datetime import datetime

    def row(release, day):
        return {
            "version": f"1.gen4-release-{release}.555",
            "issue_time": int(
                datetime.fromisoformat(day + "T12:00:00+08:00").timestamp() * 1000
            ),
        }

    periods, warnings = infer_completed_cycles(
        [
            row("20260904", "2026-09-10"),
            row("20260904", "2026-09-28"),
            row("20260918", "2026-09-24"),
        ]
    )
    assert not periods and warnings


def test_cosmetic_source_changes_keep_plan_fingerprint(db, config):
    seed(db, config)
    before = w.make_plan(db, config)["fingerprint"]
    snapshot = db.scalars(select(ReleaseIssueSnapshot)).first()
    value = deepcopy(snapshot.payload)
    value["issues"][0]["issue_topic"] = "new description"
    value["scenarios"][0]["scenario_name"] = "renamed"
    value["scenarios"][0]["scenario_labels"].append("new tag")
    snapshot.payload = value
    db.commit()
    assert w.make_plan(db, config)["fingerprint"] == before


def test_active_release_batch_prevents_second_population_launch(
    db, config, monkeypatch
):
    seed(db, config)
    plan = w.make_plan(db, config)
    monkeypatch.setattr(
        w,
        "driver_call",
        lambda c, a, p: {"fingerprint": p["fingerprint"], "ready": True, "job_id": 99},
    )
    w.submit_plan(db, plan["fingerprint"], config)
    snapshot = db.scalars(select(ReleaseIssueSnapshot)).first()
    value = deepcopy(snapshot.payload)
    value["issues"][0]["ra_merge_result"] = "误触发"
    value["scenarios"][0]["scenario_labels"] = scene_labels("negative_auto")
    snapshot.payload = value
    db.commit()
    new_plan = w.make_plan(db, config)
    with pytest.raises(ValueError, match="活动批次"):
        w.queue_plan(db, new_plan["fingerprint"], config)


def test_online_formulas_keep_independent_precision_recall_populations():
    from app.services.release_metrics import summarize_population

    rows = [
        {"issue_id": "1", "ra_type": 2, "ra_merge_result": "成功"},
        {"issue_id": "2", "ra_type": 2, "ra_merge_result": "待确认"},
        {"issue_id": "3", "ra_type": 2, "ra_merge_result": "误触发"},
        {"issue_id": "4", "ra_type": 3, "ra_merge_result": "成功"},
    ]
    value = summarize_population(rows, [], {})
    assert value["online_precision"] == 1 / 3
    assert value["online_recall"] == 2 / 3
    assert value["available"] is False
    assert value["precision_auto_tp"] == 1 and value["recall_auto_tp"] == 2


def test_business_summary_never_uses_old_release_as_current(db, config, monkeypatch):
    from app.api import routes

    seed(db, config)
    monkeypatch.setattr(w, "load_cycle_config", lambda: config)
    legacy = {
        "version_key": "old-release",
        "label": "old",
        "total_cases": 1,
        "road_positive_cases": 1,
        "sim_positive_cases": 1,
        "reproduced_cases": 1,
        "sim_repro_rate": 1,
        "model_repro_rate": 1,
        "fn_fallback_rate": 0,
        "fp_suppress_rate": 0,
        "precision": 1,
        "recall": 1,
        "f1": 1,
        "root_causes": {},
    }
    monkeypatch.setattr(
        routes,
        "_read_dashboard_snapshot",
        lambda _: {
            "current": legacy,
            "comparison": [],
            "generated_at": "2026-09-30T00:00:00",
        },
    )
    value = routes.summary(db)
    assert value.business_current_version == "gen4-release-20260918"
    assert value.current is None
    assert value.legacy_current.version_key == "old-release"
    assert value.deltas == {}


def test_acceptance_subset_never_publishes_full_cycle_kpi(db, config, monkeypatch):
    from app.models import ReleaseSimulationBatch
    from app.services.release_presentation import context

    seed(db, config)
    config["simulation"]["acceptance_only"] = True
    monkeypatch.setattr(w, "load_cycle_config", lambda: config)
    plan = w.make_plan(db, config)
    batch = ReleaseSimulationBatch(
        fingerprint=plan["fingerprint"],
        release=plan["release"],
        status="complete",
        payload={
            **plan,
            "job_id": 99,
            "summary": {
                "available": True,
                "eligible": 2,
                "tp": 2,
                "fp": 0,
                "fn": 0,
                "tn": 0,
                "road_matches": 1,
                "precision": 1,
                "recall": 1,
                "sim_repro_rate": 0.5,
            },
        },
    )
    db.add(batch)
    db.commit()
    assert context(db)["business_metrics"] is None


def exclusion_decision(config):
    return {"issue_id": "missing", "release": config['periods'][0]['release'],
            "approved_by": "user", "approved_at": "2026-10-19T00:00:00+00:00",
            "reason": "User explicitly excludes missing GT from this evaluation",
            "source": {"version": "road-build", "ra_type": 2, "ra_merge_result": None}}


def test_scoped_exclusion_preserves_raw_truth_and_unblocks_only_approved_issue(db, config):
    from app.services.release_metrics import summarize_population
    unknown = {"issue_id": "missing", "version": "road-build", "ra_type": 2, "ra_merge_result": None}
    rows = population() + [unknown]
    fetch = lambda *_: rows
    first = w.sync_once(db, config, fetch, scenarios)
    old_hash = w.population_identity(first.payload)
    with pytest.raises(ValueError, match='GT'):
        w.make_plan(db, config)
    decision = exclusion_decision(config)
    w.put_state(db, 'issue_exclusions:' + decision['release'], {'items': [decision]})
    snapshot = w.sync_once(db, config, fetch, scenarios)
    assert len(snapshot.payload['issues']) == 3
    assert snapshot.payload['issues'][-1]['ra_merge_result'] is None
    assert 'evaluation_exclusion' not in unknown  # Do not mutate source responses.
    assert w.population_identity(snapshot.payload) != old_hash
    plan = w.make_plan(db, config)
    assert len(plan['scenarios']) == 2
    assert plan['issues'][-1]['evaluation_exclusion'] == decision
    assert w.sync_once(db, config, fetch, scenarios).id == snapshot.id
    metrics = summarize_population(snapshot.payload['issues'], snapshot.payload['scenarios'], {
        '1': {'sim_triggered': True}, '2': {'sim_triggered': False}})
    assert metrics['available'] is True
    assert metrics['unclassified'] == 0 and metrics['excluded'] == 1
    assert metrics['eligible'] == 2
    # Same missing GT in another release remains unclassified.
    assert 'evaluation_exclusion' not in w.apply_issue_exclusions(db, 'other-release', [unknown])[0]
    with pytest.raises(ValueError, match='源标注已变化'):
        w.sync_once(db, config, lambda *_: population()+[{**unknown,'ra_merge_result':'成功'}], scenarios)
    with pytest.raises(ValueError, match='不在当前人口'):
        w.sync_once(db, config, population, scenarios)


def test_exclusion_cannot_hide_other_unknown_truth_or_arrive_from_upstream(db, config):
    decision = exclusion_decision(config)
    unknown = {"issue_id": "missing", **decision['source'], 'evaluation_exclusion': decision}
    cleaned = w.apply_issue_exclusions(db, decision['release'], [unknown])
    assert 'evaluation_exclusion' not in cleaned[0]
    w.put_state(db, 'issue_exclusions:' + decision['release'], {'items': [decision]})
    w.sync_once(db, config, lambda *_: population()+[unknown,{**unknown,'issue_id':'another'}], scenarios)
    with pytest.raises(ValueError, match='1 个 Issue 的 GT'):
        w.make_plan(db, config)


@pytest.mark.parametrize('failed', [False, True])
def test_terminal_audit_imports_success_or_partial_reference(db, config, monkeypatch, failed):
    from app.models import ReleaseSimulationBatch
    seed(db, config)
    plan = w.make_plan(db, config)
    batch = ReleaseSimulationBatch(fingerprint=plan['fingerprint'], release=plan['release'],
        status='verifying', payload={**plan, 'job_id': 99})
    db.add(batch); db.commit()
    rows = [{**s, 'task_id': '99'+s['scenario_id'], 'task_status': 3,
        'task_outcome': 'Done', 'argument_hash': 'verified-'+s['scenario_id'],
        'simulator_cache_hit': False, 'inference_log_count': 1, 'dpe_output_count': 1,
        'output_bag_count': 1, 'failed_evaluation_count': 0, 'unexpected_warning_count': 0,
        'dpe_assist_channel_triggered__group1': -1} for s in plan['scenarios']]
    if failed:
        rows[0].update(task_status=4, task_outcome='DPE exceeded memory quota')
    export = {**{k: plan[k] for k in ('release', 'binary_id', 'population_hash')},
        'job_id': 99, 'execution_contract_hash': 'runtime-verified', 'progress': dict(job_id=99, state='COMPLETED', total=2,
                                     completed=2-int(failed), failed=int(failed), cancelled=0),
        'rows': rows, 'quality': {'quality': {'gate_passed_so_far': not failed}}}
    monkeypatch.setattr(w, 'driver_call', lambda *_: dict(fingerprint=plan['fingerprint'],
        job_id=99, status='audited', execution_export=export))
    w.poll_batches(db, config)
    assert batch.status == ('quality_failed' if failed else 'complete')
    evaluation = batch.payload['result_import']
    assert evaluation['valid_scenario_count'] == 2-int(failed)
    assert evaluation['missing_scenario_count'] == int(failed)
    assert evaluation['quality_gate_passed'] is not failed
    assert evaluation['subset_summary']['available']
    assert bool(evaluation['failures']) is failed
    if not failed:
        assert batch.payload['publication_approval']['automatic']
    else:
        assert batch.payload['publication_decision']['status'] == 'blocked'
    assert w.metrics_for_snapshot(db, db.scalars(select(ReleaseIssueSnapshot)).first())['available'] is not failed


def test_legacy_failed_signal_keeps_polling_then_recovers(db, config, monkeypatch):
    from app.models import ReleaseSimulationBatch
    seed(db, config)
    plan = w.make_plan(db, config)
    batch = ReleaseSimulationBatch(fingerprint=plan['fingerprint'], release=plan['release'],
        status='running', payload={**plan, 'job_id': 99})
    db.add(batch); db.commit()
    state = iter(['failed', 'running', 'verifying'])
    monkeypatch.setattr(w, 'driver_call', lambda *_: dict(fingerprint=plan['fingerprint'],
        job_id=99, status=next(state)))
    for expected in ['verifying', 'running', 'verifying']:
        w.poll_batches(db, config)
        assert batch.status == expected


@pytest.mark.parametrize('problem', ['population', 'unknown_state', 'timeout'])
def test_audit_error_is_visible_and_does_not_freeze_polling(db, config, monkeypatch, problem):
    from app.models import ReleaseSimulationBatch
    seed(db, config)
    plan = w.make_plan(db, config)
    batch = ReleaseSimulationBatch(fingerprint=plan['fingerprint'], release=plan['release'],
        status='verifying', payload={**plan, 'job_id': 99})
    db.add(batch); db.commit()
    if problem == 'population':
        snapshot = db.scalars(select(ReleaseIssueSnapshot)).first()
        payload = deepcopy(snapshot.payload); payload['issues'][0]['ra_merge_result'] = '误触发'
        snapshot.payload = payload; db.commit()
    def call(*_):
        if problem == 'timeout':
            raise TimeoutError()
        return dict(fingerprint=plan['fingerprint'], job_id=99,
                    status='audited' if problem == 'population' else 'nonsense')
    monkeypatch.setattr(w, 'driver_call', call)
    w.poll_batches(db, config)
    assert batch.status == 'verifying'
    assert batch.payload.get('last_poll_error')
    assert 'result_import' not in batch.payload
