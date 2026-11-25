from copy import deepcopy
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import ReleaseSimulationBatch, ReleaseIssueSnapshot
from app.services.result_integration import import_executions
from app.services.result_publication import approve_publication, publication, validate_standard
from app.services.release_workflow import population_identity
from app.services.release_presentation import render_kpi, history_kpis, context
from test_result_integration import fixture_data, fail, TRIGGER


@pytest.fixture
def data():
    plan, exports = fixture_data()
    for i in range(3, 201):
        scene = {"scenario_id": str(i), "issue_id": f"i{i}", "cohort": "negative_auto"}
        plan["scenarios"].append(scene)
        plan["issues"].append({"issue_id": f"i{i}", "ra_type": 2, "ra_merge_result": "误触发"})
        for e in exports:
            e["rows"].append(
                {
                    **deepcopy(e["rows"][1]),
                    **scene,
                    "task_id": f"{e['job_id']}-{i}",
                    "argument_hash": f"args-{i}",
                }
            )
    for e in exports:
        e["progress"].update(total=200, completed=200)
    plan["period"] = {
        "release": plan["release"],
        "binary_id": 123,
        "verified": True,
        "status": "completed",
        "cycle_end": "2026-09-03",
        "evidence": "synthetic closed-cycle record",
        "case_start": "2026-09-03T00:00:00+08:00",
        "case_end_exclusive": "2026-09-05T00:00:00+08:00",
    }
    plan["population_complete"] = True
    plan["source_scope"] = "full_period"
    for issue in plan["issues"]:
        issue.update(version=plan["release"], issue_time=1788451200000)
    plan["population_hash"] = population_identity(plan)
    for e in exports:
        e["population_hash"] = plan["population_hash"]
    fail(exports[0], 1)
    exports[0]["progress"]["completed"] = 199
    exports[1]["rows"][0][TRIGGER] = -1
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ReleaseIssueSnapshot(release=plan["release"], period_hash="original", payload=plan))
        for jid in (100, 200):
            db.add(
                ReleaseSimulationBatch(
                    fingerprint=str(jid),
                    release=plan["release"],
                    status="failed",
                    payload={**deepcopy(plan), "job_id": jid},
                )
            )
        db.commit()
        import_executions(db, plan, exports, 100)
        yield db, db.get(ReleaseSimulationBatch, "100"), plan


def test_explicit_exclusion_publishes_primary_without_changing_audit(data, monkeypatch):
    db, batch, plan = data
    before = deepcopy(batch.payload)
    assert publication(batch) is None
    approve_publication(db, batch, plan["population_hash"], ["2"], "User authorized")
    metrics = publication(batch)
    assert metrics["eligible"] == 199 and metrics["precision"] == 1
    assert metrics["publication"]["comparison_conflicts"] == 1
    assert not metrics["quality_gate_passed"] and batch.status == "quality_failed"
    assert batch.payload["result_import"] == before["result_import"]
    assert batch.payload["scenario_results"]["2"]["status"] == "failed"
    kpi = render_kpi(plan["release"], metrics, metrics)
    assert kpi["dpe_coverage"] == 0.995 and not kpi["quality_gate_passed"]
    # Later source synchronization retains frozen evidence but cannot present
    # an older execution as current full-release coverage.
    newer = deepcopy(plan)
    newer["issues"].append(
        {
            "issue_id": "new",
            "ra_type": 2,
            "ra_merge_result": "成功",
            "version": plan["release"],
            "issue_time": 1788451200000,
        }
    )
    db.add(ReleaseIssueSnapshot(release=plan["release"], period_hash="new", payload=newer))
    db.commit()
    monkeypatch.setattr(
        "app.services.release_presentation.effective_config",
        lambda _: {"periods": [{"release": plan["release"], "status": "completed"}]},
    )
    assert history_kpis(db)[0]["evaluated_cases"] == 199
    monkeypatch.setattr(
        "app.services.release_presentation.status",
        lambda _: {"current_version": plan["release"], "metrics": {"available": False}},
    )
    ctx = context(db)
    assert ctx["business_status"] == "published_with_exclusions"
    assert ctx["business_metrics"]["evaluated_cases"] == 199
    assert ctx["business_metrics"]["precision"] == 1
    assert ctx["business_collection"] is None
    assert publication(batch) == metrics


def test_latest_observation_keeps_overview_metrics_visible_without_rewriting_publication(
    data, monkeypatch
):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.services import release_workflow as workflow
    from app.services.business_population import scope_for_batch
    from app.api import routes

    db, batch, plan = data
    approve_publication(db, batch, plan["population_hash"], ["2"], "User authorized")
    db.commit()
    before = deepcopy(batch.payload)
    observed = deepcopy(plan["issues"])
    observed.append(
        {
            "issue_id": "late-manual",
            "ra_type": 3,
            "ra_merge_result": "成功",
            "version": plan["release"],
            "issue_time": 1788451200000,
        }
    )
    now = datetime.now(timezone.utc).isoformat()
    workflow.put_state(
        db,
        "release_observation:" + plan["release"],
        {
            "release": plan["release"],
            "issues": observed,
            "activity_hash": "new-population",
            "observed_at": now,
        },
    )
    workflow.put_state(
        db,
        "release_monitor:" + plan["release"],
        {
            "release": plan["release"],
            "activity_hash": "new-population",
            "quiet_seconds": 0,
            "last_success_at": now,
            "population_changed_after_submission": True,
        },
    )
    config = {
        "periods": [plan["period"]],
        "contract": {"time_field": "issue_time", "verified": True, "reference": "synthetic"},
    }
    monkeypatch.setattr(workflow, "effective_config", lambda _: config)
    monkeypatch.setattr("app.services.release_presentation.effective_config", lambda _: config)
    monkeypatch.setattr(
        "app.services.release_presentation.status",
        lambda _: {"current_version": plan["release"], "metrics": {"available": False}},
    )
    # Operational scope still detects the population change accurately.
    scope = scope_for_batch(db, batch)
    assert not scope["available"] and scope["reason_code"] == "population_changed"
    assert (
        scope["collected_issue_count"] == 201
        and scope["auto_count"] == 200
        and scope["manual_count"] == 1
        and scope["evaluated_issue_count"] == 199
    )
    # Overview presentation always keeps audited published metrics visible.
    result = context(db)
    assert result["business_status"] == "published_with_exclusions"
    assert result["business_collection"] is None
    assert result["business_metrics"]["evaluated_cases"] == 199
    assert result["business_metrics"]["precision"] == 1
    row = next(item for item in history_kpis(db) if item["version_key"] == plan["release"])
    assert row["sim_repro_rate"] is not None and row["precision"] == 1
    assert row["sim_estimate"]["estimated_tp"] is not None
    monkeypatch.setattr(routes, "business_context", lambda _: result)
    monkeypatch.setattr(routes, "_read_dashboard_snapshot", lambda _: {"generated_at": now})
    response = routes._summary(db, SimpleNamespace(headers={"x-ra-sim-client": "release-cycle-v1"}))
    assert response.current is not None and response.current.evaluated_cases == 199
    assert response.business_collection is None
    assert batch.payload == before and publication(batch)["eligible"] == 199


def test_ordinary_evaluation_kpi_and_context_surface_covered_metrics_and_f1(data, monkeypatch):
    from app.services import ordinary_evaluation

    db, _, plan = data
    release = plan["release"]
    revision = {
        "revision_key": "normalrevision:test-1106",
        "context": {"release": release},
        "source_count": 1703,
        "generated_at": "2026-11-25T05:42:51+00:00",
        "lineage": {"1": {"job_id": 50805791}},
        "metrics": {
            "available": True,
            "covered": 1252,
            "eligible": 1252,
            "coverage": 1.0,
            "road_matches": 1106,
            "missing_results": 0,
            "sim_repro_rate": None,
            "precision": None,
            "recall": None,
            "covered_repro_rate": 0.8834,
            "covered_precision": 0.8133,
            "covered_recall": 0.7787,
            "online_precision": 0.6131,
            "online_recall": 0.7852,
            "counts": {
                "precision_numerator": 824,
                "precision_denominator": 1344,
                "recall_numerator": 824,
                "recall_denominator": 1049,
            },
            "covered_source_counts": {
                "precision_numerator": 824,
                "precision_denominator": 1344,
                "recall_numerator": 824,
                "recall_denominator": 1049,
            },
            "sim_counts": {
                "precision_numerator": 806,
                "precision_denominator": 991,
                "recall_numerator": 806,
                "recall_denominator": 1035,
            },
        },
    }
    kpi = ordinary_evaluation.kpi(revision)
    assert kpi["sim_repro_rate"] == pytest.approx(0.8834)
    assert kpi["precision"] == pytest.approx(0.8133)
    assert kpi["recall"] == pytest.approx(0.7787)
    assert kpi["f1"] == pytest.approx(2 * 0.8133 * 0.7787 / (0.8133 + 0.7787))
    assert kpi["sim_estimate"]["same_version_projection"]["sim_precision"] == pytest.approx(0.8133)
    assert kpi["sim_estimate"]["same_version_projection"]["sim_business_recall"] == pytest.approx(
        0.7787
    )

    monkeypatch.setattr(
        ordinary_evaluation, "read", lambda _db, rel: revision if rel == release else None
    )
    monkeypatch.setattr(
        "app.services.release_presentation.status",
        lambda _: {"current_version": release, "metrics": {"available": False}},
    )
    ctx = context(db)
    assert ctx["business_status"] == "complete"
    assert ctx["business_collection"] is None
    assert ctx["business_metrics"]["sim_repro_rate"] == pytest.approx(0.8834)
    assert ctx["business_metrics"]["f1"] == pytest.approx(kpi["f1"])
    assert ctx["metrics"]["job_id"] == 50805791
    assert ctx["metrics"]["generated_at"] == "2026-11-25T05:42:51+00:00"


def test_unclassified_ordinary_revision_falls_back_to_clean_published_batch(data, monkeypatch):
    from app.services import ordinary_evaluation

    db, batch, plan = data
    release = plan["release"]
    approve_publication(db, batch, plan["population_hash"], ["2"], "User authorized")
    db.commit()

    poisoned = {
        "revision_key": "normalrevision:poisoned-unclassified",
        "context": {"release": release},
        "source_count": 200,
        "generated_at": "2026-11-25T05:42:51+00:00",
        "lineage": {"1": {"job_id": 50805791}},
        "rows": [{"issue_id": "i1", "baseline_label": ""}],
        "metrics": {
            "available": True,
            "covered": 150,
            "eligible": 150,
            "unclassified": 50,
            "coverage": 1.0,
            "road_matches": 130,
            "missing_results": 0,
            "sim_repro_rate": None,
            "precision": None,
            "recall": None,
            "covered_repro_rate": 0.8667,
            "covered_precision": 0.8,
            "covered_recall": 0.75,
            "online_precision": 0.613,
            "online_recall": 0.79,
            "positive_auto_repro_rate": 0.91,
            "negative_auto_repro_rate": 0.85,
            "positive_manual_repro_rate": 0.77,
            "counts": {
                "precision_numerator": 824,
                "precision_denominator": 1344,
                "recall_numerator": 824,
                "recall_denominator": 1049,
            },
            "covered_source_counts": {
                "precision_numerator": 824,
                "precision_denominator": 1344,
                "recall_numerator": 824,
                "recall_denominator": 1049,
            },
            "sim_counts": {
                "precision_numerator": 806,
                "precision_denominator": 991,
                "recall_numerator": 806,
                "recall_denominator": 1035,
            },
        },
    }
    kpi = ordinary_evaluation.kpi(poisoned)
    assert kpi["positive_auto_repro_rate"] == pytest.approx(0.91)
    assert kpi["negative_auto_repro_rate"] == pytest.approx(0.85)
    assert kpi["positive_manual_repro_rate"] == pytest.approx(0.77)

    monkeypatch.setattr(
        ordinary_evaluation, "read", lambda _db, rel: poisoned if rel == release else None
    )
    monkeypatch.setattr(
        "app.services.release_presentation.ordinary_kpis",
        lambda _db: [kpi],
    )
    monkeypatch.setattr(
        "app.services.release_presentation.effective_config",
        lambda _: {"periods": [{"release": release, "status": "completed"}]},
    )
    monkeypatch.setattr(
        "app.services.release_presentation.status",
        lambda _: {"current_version": release, "metrics": {"available": False}},
    )
    ctx = context(db)
    assert ctx["business_status"] == "published_with_exclusions"
    assert ctx["business_metrics"]["evaluated_cases"] == 199
    assert ctx["business_metrics"]["sim_estimate"]["job_id"] == 100
    rows = history_kpis(db)
    assert len(rows) == 1
    assert rows[0]["evaluated_cases"] == 199
    assert rows[0]["sim_estimate"]["job_id"] == 100


@pytest.mark.parametrize(
    "case", ["wrong_hash", "wrong_exclusions", "artifact_failure", "secondary"]
)
def test_unapproved_or_wrong_population_cannot_be_published(data, case):
    db, batch, plan = data
    h, exclusions = plan["population_hash"], ["2"]
    if case == "wrong_hash":
        h = "other"
    if case == "wrong_exclusions":
        exclusions = ["1"]
    if case == "secondary":
        batch = db.get(ReleaseSimulationBatch, "200")
    if case == "artifact_failure":
        p = deepcopy(batch.payload)
        p["result_import"]["failures"][0]["status"] = "quality_failed"
        batch.payload = p
    with pytest.raises(ValueError):
        approve_publication(db, batch, h, exclusions, "User authorized")


def test_changed_results_invalidate_existing_publication(data):
    db, batch, plan = data
    approve_publication(db, batch, plan["population_hash"], ["2"], "User authorized")
    p = deepcopy(batch.payload)
    p["results"]["1"]["sim_triggered"] = False
    batch.payload = p
    assert publication(batch) is None


def test_below_threshold_is_blocked(data):
    _, batch, _ = data
    p = deepcopy(batch.payload)
    p["scenarios"] = [s for s in p["scenarios"] if s["scenario_id"] != "200"]
    del p["results"]["200"]
    del p["scenario_results"]["200"]
    p["result_import"].update(scenario_count=199, valid_scenario_count=198)
    p["execution_progress"].update(total=199, completed=198)
    with pytest.raises(ValueError, match="99.5%"):
        validate_standard(p)


@pytest.mark.parametrize(
    "field,value", [("state", "RUNNING"), ("queued", 1), ("cancelled", 1), ("unknown", 1)]
)
def test_unfinished_execution_blocked(data, field, value):
    _, batch, _ = data
    p = deepcopy(batch.payload)
    p["execution_progress"][field] = value
    with pytest.raises(ValueError):
        validate_standard(p)


def test_unverified_cycle_blocked(data):
    _, batch, _ = data
    p = deepcopy(batch.payload)
    p["period"]["verified"] = False
    with pytest.raises(ValueError, match="cycle"):
        validate_standard(p)


def ready_for_auto(data, grow=True):
    db, batch, plan = data
    p = deepcopy(batch.payload)
    p["result_import"]["comparison"]["conflicts"] = []
    for row in p["scenario_results"].values():
        row["conflict"] = False
    if grow:
        from app.services.release_metrics import summarize_population

        p["issues"].append({"issue_id": "i201", "ra_type": 2, "ra_merge_result": "误触发"})
        p["scenarios"].append({**p["scenarios"][-1], "scenario_id": "201", "issue_id": "i201"})
        p["results"]["201"] = {**p["results"]["200"], "issue_id": "i201"}
        p["scenario_results"]["201"] = deepcopy(p["scenario_results"]["200"])
        p["result_import"].update(scenario_count=201, valid_scenario_count=200, coverage=200 / 201)
        p["execution_progress"].update(total=201, completed=200)
        p["result_import"]["subset_summary"] = summarize_population(
            [i for i in p["issues"] if i["issue_id"] != "i2"],
            [s for s in p["scenarios"] if s["issue_id"] != "i2"],
            p["results"],
        )
        p["population_hash"] = population_identity(p)
        p["result_import"]["population_hash"] = p["population_hash"]
        db.add(ReleaseIssueSnapshot(release=p["release"], period_hash="grown", payload=deepcopy(p)))
    batch.payload = p
    db.commit()
    return db, batch, plan


def test_auto_publishes_above_threshold_and_is_idempotent(data):
    from app.services.result_publication import reconcile_publications

    db, batch, plan = ready_for_auto(data)
    before = deepcopy(batch.payload["result_import"])
    reconcile_publications(db, {})
    first = deepcopy(batch.payload)
    metrics = publication(batch)
    assert metrics["available"] and metrics["publication"]["automatic"]
    assert metrics["publication"]["coverage"] == 200 / 201
    assert metrics["publication"]["issue_coverage"] == 200 / 201
    assert batch.payload["result_import"] == before
    assert batch.status == "quality_failed"
    reconcile_publications(db, {})
    assert batch.payload == first


def test_auto_tolerates_audited_artifact_failure(data):
    from app.services.result_publication import reconcile_publications

    db, batch, _ = ready_for_auto(data)
    p = deepcopy(batch.payload)
    p["scenario_results"]["2"].update(
        status="quality_failed", errors=["unexpected_warning_count"], outcome="Done with warnings"
    )
    p["result_import"]["failures"][0].update(p["scenario_results"]["2"])
    p["execution_progress"].update(completed=201, failed=0)
    batch.payload = p
    db.commit()
    reconcile_publications(db, {})
    metrics = publication(batch)
    assert metrics["available"] and metrics["publication"]["quality_failed_count"] == 1
    assert metrics["publication"]["execution_failed_count"] == 0
    assert batch.payload["scenario_results"]["2"]["status"] == "quality_failed"


@pytest.mark.parametrize(
    "change", ["threshold", "population", "conflicts", "details", "runtime", "identity", "disabled"]
)
def test_auto_publication_blocks_missing_prerequisites_with_reason(data, change):
    from app.services.result_publication import reconcile_publications

    db, batch, plan = ready_for_auto(data)
    p = deepcopy(batch.payload)
    config = {}
    if change == "threshold":
        config = {"result_publication": {"minimum_coverage": 0.996}}
    if change == "disabled":
        config = {"result_publication": {"enabled": False}}
    if change == "population":
        newer = deepcopy(plan)
        newer["issues"][0]["ra_merge_result"] = "误触发"
        db.add(ReleaseIssueSnapshot(release=plan["release"], period_hash="new", payload=newer))
    if change == "conflicts":
        p["result_import"]["comparison"]["conflicts"] = ["1"]
    if change == "details":
        p["scenario_results"]["1"]["errors"] = ["dpe_missing"]
    if change == "runtime":
        p["execution_progress"]["state"] = "RUNNING"
    if change == "identity":
        p["result_import"]["binary_id"] = 999
    batch.payload = p
    db.commit()
    reconcile_publications(db, config)
    assert publication(batch) is None
    assert batch.payload["publication_decision"]["status"] == "blocked"
    assert batch.payload["publication_decision"]["reason"]


def test_policy_change_rechecks_and_does_not_mutate_manual_approval(data):
    from app.services.result_publication import reconcile_publications

    db, batch, plan = data
    approve_publication(db, batch, plan["population_hash"], ["2"], "User authorized")
    before = deepcopy(batch.payload)
    reconcile_publications(db, {"result_publication": {"minimum_coverage": 1}})
    assert batch.payload == before and publication(batch)


def test_auto_threshold_change_revokes_old_automatic_publication(data):
    from app.services.result_publication import reconcile_publications

    db, batch, _ = ready_for_auto(data)
    reconcile_publications(db, {})
    assert publication(batch)
    reconcile_publications(db, {"result_publication": {"minimum_coverage": 1}})
    assert not publication(batch)
    assert batch.payload["publication_decision"]["status"] == "blocked"


@pytest.mark.parametrize("threshold", [True, 0, -1, 1.1, "NaN", "bad"])
def test_invalid_threshold_rejected(threshold):
    from app.services.result_publication import coverage_policy

    with pytest.raises(ValueError):
        coverage_policy({"result_publication": {"minimum_coverage": threshold}})


def test_multiple_scenarios_cannot_hide_missing_issue_coverage(data):
    from app.services.result_publication import validate_coverage_standard
    from app.services.release_metrics import summarize_population

    _, batch, _ = ready_for_auto(data)
    p = deepcopy(batch.payload)
    for scene in p["scenarios"]:
        if int(scene["scenario_id"]) > 100:
            scene["issue_id"] = "i1"
            p["results"][scene["scenario_id"]]["issue_id"] = "i1"
    p["issues"] = [i for i in p["issues"] if int(i["issue_id"][1:]) <= 100]
    p["result_import"]["subset_summary"] = summarize_population(
        [i for i in p["issues"] if i["issue_id"] != "i2"],
        [s for s in p["scenarios"] if s["issue_id"] != "i2"],
        p["results"],
    )
    with pytest.raises(ValueError, match="Issue 覆盖率"):
        validate_coverage_standard(p)


def test_auto_rejects_exact_threshold(data):
    from app.services.result_publication import reconcile_publications

    db, batch, _ = ready_for_auto(data, grow=False)
    reconcile_publications(db, {})
    assert publication(batch) is None
    assert "99.5%" in batch.payload["publication_decision"]["reason"]


def test_legacy_auto_approval_remains_readable(data):
    from app.services.result_publication import (
        validate_coverage_standard,
        audit_hash,
        reconcile_publications,
    )

    db, batch, _ = ready_for_auto(data, grow=False)
    p = deepcopy(batch.payload)
    p["publication_approval"] = {
        **validate_coverage_standard(p, issue_budget=False),
        "policy": "audited_valid_samples",
        "automatic": True,
        "approved_at": "2026-10-22T00:00:00Z",
        "audit_hash": audit_hash(p),
        "excluded_scenario_ids": ["2"],
    }
    batch.payload = p
    db.commit()
    before = deepcopy(p)
    reconcile_publications(db, {})
    assert publication(batch) and batch.payload == before
