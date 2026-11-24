from copy import deepcopy
import pytest
from app.models import ReleaseSimulationBatch, ReleaseWorkflowState
from app.services import reproduction_evidence as e, reproduction_timing as t
from app.services.release_cycle import digest
from app.services.result_publication import audit_hash
from test_auto_triage_metrics import db, RELEASE

T = 1790000020000


def setup(db, triggered=True):
    issue = {
        "issue_id": "a",
        "ra_type": 3,
        "ra_merge_result": "成功",
        "version": RELEASE,
        "trip_id": "trip-a",
        "issue_time": T + 28000,
        "ra_start_timestamp": T,
        "trip_start_time": T - 100000,
        "trip_end_time": T + 100000,
    }
    scene = {
        "scenario_id": "s-a",
        "issue_id": "a",
        "scenario_revision": 2,
        "start_timestamp": T - 8080,
        "end_timestamp": T + 10000,
    }
    result = {"sim_triggered": triggered, "reproduced": not triggered}
    batch = ReleaseSimulationBatch(
        fingerprint="batch-a",
        release=RELEASE,
        status="complete",
        payload={
            "release": RELEASE,
            "job_id": 123,
            "issues": [issue],
            "scenarios": [scene],
            "results": {"s-a": result},
            "scenario_results": {"s-a": {"task_id": "123000001", "status": "result_ready"}},
        },
    )
    db.add(batch)
    db.commit()
    origin = {
        "fingerprint": batch.fingerprint,
        "job_id": 123,
        "audit_hash": audit_hash(batch.payload),
    }
    record = {
        "binding": e.binding(RELEASE, issue, scene, result, origin),
        "task_id": "123000001",
        "task_version": 0,
        "artifact_sha256": "a" * 64,
        "trigger_events": [{"timestamp_source": "dpe_request_event", "request_timestamp": T + 1000}]
        if triggered
        else [],
    }
    return batch, issue, scene, origin, record


def activate(db):
    db.add(
        ReleaseWorkflowState(
            key="rtime_policy:" + RELEASE, payload={"enabled": True, "policy": t.POLICY}
        )
    )
    db.commit()


def test_event_store_is_immutable_and_bound_to_physical_input_and_execution(db):
    batch, issue, scene, origin, record = setup(db)
    original = deepcopy(batch.payload)
    key = e.save(db, RELEASE, [record])
    db.commit()
    assert e.save(db, RELEASE, [record]) == key
    values = e.evaluate(db, RELEASE, [issue], [scene], batch.payload["results"], {"s-a": origin})
    assert values["a"]["status"] == "after_manual_trigger" and values["a"]["matched"] is True
    changed = {**issue, "ra_start_timestamp": T + 2000}
    assert (
        e.evaluate(db, RELEASE, [changed], [scene], batch.payload["results"], {"s-a": origin})["a"][
            "status"
        ]
        == "timing_missing"
    )
    altered = {**origin, "job_id": 124}
    assert (
        e.evaluate(db, RELEASE, [issue], [scene], batch.payload["results"], {"s-a": altered})["a"][
            "status"
        ]
        == "timing_missing"
    )
    assert batch.payload == original


@pytest.mark.parametrize(
    "field,value", [("task_id", "other-task"), ("task_version", None), ("artifact_sha256", "short")]
)
def test_unbound_or_incomplete_receipts_cannot_be_imported(db, field, value):
    *_, record = setup(db)
    record[field] = value
    with pytest.raises(ValueError):
        e.save(db, RELEASE, [record])


def test_different_scene_revision_and_changed_execution_cannot_reuse_events(db):
    batch, issue, scene, origin, record = setup(db)
    record["binding"]["scene"]["scenario_revision"] += 1
    with pytest.raises(ValueError, match="input_changed"):
        e.save(db, RELEASE, [record])
    record["binding"]["scene"]["scenario_revision"] -= 1
    batch.payload = {**batch.payload, "results": {"s-a": {"sim_triggered": False}}}
    db.commit()
    with pytest.raises(ValueError, match="execution_changed"):
        e.save(db, RELEASE, [record])


def test_conflicting_evidence_is_pending_instead_of_selecting_favorable_run(db):
    batch, issue, scene, origin, record = setup(db)
    e.save(db, RELEASE, [record])
    db.commit()
    second = deepcopy(record)
    second["trigger_events"][0]["request_timestamp"] = T - 500
    e.save(db, RELEASE, [second])
    db.commit()
    values = e.evaluate(db, RELEASE, [issue], [scene], batch.payload["results"], {"s-a": origin})
    assert values["a"]["status"] == "timing_missing"


def test_standard_overlay_changes_behavior_only_and_does_not_mutate_history(db):
    batch, issue, scene, origin, record = setup(db)
    e.save(db, RELEASE, [record])
    db.commit()
    activate(db)
    original = {
        "eligible": 1,
        "road_matches": 0,
        "sim_repro_rate": 0.0,
        "precision": 1.0,
        "recall": 1.0,
        "tp": 1,
        "fp": 0,
        "fn": 0,
        "tn": 0,
        "available": True,
    }
    before = deepcopy(original)
    view = e.standard_view(db, batch, original)
    assert view["sim_repro_rate"] == 1 and view["road_matches"] == 1
    assert view["reproduction"]["statuses"] == {"after_manual_trigger": 1}
    assert view["whole_window_road_matches"] == 0
    for field in ("tp", "fp", "fn", "tn", "precision", "recall", "eligible", "available"):
        assert view[field] == original[field]
    assert original == before


def test_missing_time_is_not_a_business_fn_or_a_result_failure(db):
    batch, *_ = setup(db)
    activate(db)
    original = {
        "eligible": 1,
        "road_matches": 0,
        "sim_repro_rate": 0.0,
        "precision": 1.0,
        "recall": 1.0,
        "tp": 1,
        "fn": 0,
        "available": True,
    }
    view = e.standard_view(db, batch, original)
    assert view["sim_repro_rate"] is None and view["reproduction"]["pending"] == 1
    assert view["tp"] == 1 and view["fn"] == 0 and view["available"]
    assert batch.status == "complete"


def test_policy_requires_explicit_activation_and_invalid_ledger_is_ignored(db):
    batch, issue, scene, origin, record = setup(db)
    metrics = {"eligible": 1, "road_matches": 0, "sim_repro_rate": 0.0}
    assert e.standard_view(db, batch, metrics) is metrics
    key = e.save(db, RELEASE, [record])
    db.commit()
    state = db.get(ReleaseWorkflowState, key)
    tampered = deepcopy(state.payload)
    tampered["records"][0]["trigger_events"][0]["request_timestamp"] = T - 500
    state.payload = tampered
    db.commit()
    assert not e.index(db, RELEASE)


def test_negative_results_require_no_artifact_or_upstream_read(db):
    batch, *_ = setup(db, False)
    activate(db)
    view = e.standard_view(db, batch, {"eligible": 1, "road_matches": 1, "sim_repro_rate": 1.0})
    assert view["reproduction"]["pending"] == 0 and view["sim_repro_rate"] == 1.0


def test_evaluation_overlay_retains_entire_window_memberships_and_revision(db):
    from app.services import evaluation_pipeline as p, metric_profiles as profiles

    batch, issue, scene, origin, record = setup(db)
    e.save(db, RELEASE, [record])
    db.commit()
    activate(db)
    rows = [
        {
            "issue_id": "a",
            "ra_type": 3,
            "auto_label": "成功",
            "baseline_label": "成功",
            "eligible": True,
            "sim_triggered": True,
            "result_status": "reused",
            "scenario_ids": ["s-a"],
        }
    ]
    metrics = p.summarize(rows, profiles.DEFAULT_CONFIG)
    revision = {
        "context": {"release": RELEASE},
        "profile": {"config": profiles.DEFAULT_CONFIG},
        "payload": {"issues": [issue], "scenarios": [scene]},
        "lineage": {"s-a": origin},
        "rows": rows,
        "metrics": metrics,
        "baseline": deepcopy(metrics),
        "revision_key": "frozen",
    }
    original = deepcopy(revision)
    view = e.evaluation_view(db, revision)
    assert view["metrics"]["covered_repro_rate"] == 1 and view["rows"][0]["sim_triggered"] is True
    assert view["rows"][0]["reproduction"]["status"] == "after_manual_trigger"
    for field in (
        "precision",
        "recall",
        "covered_precision",
        "covered_recall",
        "sim_counts",
        "counts",
        "covered_source_counts",
        "coverage",
    ):
        assert view["metrics"][field] == original["metrics"][field]
    assert view["metrics"]["cohorts"]["positive_manual"]["matches"] == 1
    assert revision == original
    aggregate = e.evaluation_view(db, revision, include_rows=False)
    assert {k: v for k, v in aggregate.items() if k != "rows"} == {
        k: v for k, v in view.items() if k != "rows"
    }
    assert aggregate["rows"] is revision["rows"]
    assert revision == original
    # Issue projections still isolate nested receipts from the saved revision.
    view["rows"][0]["scenario_ids"].append("another-scene")
    view["metrics"]["cohorts"]["positive_manual"]["matches"] = -1
    aggregate["baseline"]["cohorts"]["positive_manual"]["matches"] = -1
    assert revision == original


def test_new_execution_completion_captures_times_without_rewriting_audited_results(db):
    from app.services.evaluation_pipeline import execution_audit_hash

    batch, issue, scene, origin, record = setup(db)
    execution = {
        "id": "new",
        "status": "complete",
        "job_id": 124,
        "plan": {"release": RELEASE, "issues": [issue], "scenarios": [scene]},
        "results": {"s-a": {"sim_triggered": True}},
        "export": {
            "rows": [
                {
                    "scenario_id": "s-a",
                    "task_id": "124000001",
                    "reproduction_timing": {
                        "status": "verified",
                        "sim_triggered": True,
                        "task_id": "124000001",
                        "task_version": 1,
                        "artifact_sha256": "b" * 64,
                        "trigger_events": record["trigger_events"],
                    },
                }
            ]
        },
    }
    execution["audit_hash"] = execution_audit_hash(execution)
    original = deepcopy(execution)
    db.add(ReleaseWorkflowState(key="evexecution:new", payload=execution))
    db.commit()
    key = e.capture_completion(db, execution=execution)
    assert key and db.get(ReleaseWorkflowState, key)
    assert db.get(ReleaseWorkflowState, "evexecution:new").payload == original
    new_origin = {"execution_id": "new", "job_id": 124, "audit_hash": execution["audit_hash"]}
    assert (
        e.evaluate(db, RELEASE, [issue], [scene], execution["results"], {"s-a": new_origin})["a"][
            "matched"
        ]
        is True
    )


def test_behavior_filters_preserve_whole_window_trigger_and_paginate(monkeypatch):
    from app.services import evaluation_pipeline as p, metric_profiles as profiles

    rows = [
        {
            "issue_id": str(i),
            "issue_topic": "",
            "eligible": True,
            "changed": False,
            "sim_triggered": True,
            "reproduction": {
                "matched": None if i == 0 else True,
                "status": "boundary_review" if i == 0 else "after_manual_trigger",
            },
        }
        for i in range(13)
    ]
    monkeypatch.setattr(
        p, "current_revision", lambda *a, **k: {"rows": rows, "revision_key": "frozen"}
    )
    monkeypatch.setattr(profiles, "get", lambda *a: profiles.BUILTIN)
    page = p.issue_page(None, coverage="after_manual", page=2, page_size=10)
    assert page["total"] == 12 and len(page["items"]) == 2
    assert all(r["sim_triggered"] is True for r in page["items"])
    assert p.issue_page(None, coverage="reproduction_pending")["items"] == [rows[0]]


def test_pending_cohort_is_not_rendered_as_zero_reproduction():
    from app.schemas import KpiSummary
    from app.services.release_presentation import render_kpi

    metrics = {
        "eligible": 1,
        "road_matches": 0,
        "sim_repro_rate": None,
        "positive_manual_repro_rate": None,
        "reproduction": {"pending": 1},
    }
    rendered = render_kpi(RELEASE, metrics, {})
    assert rendered["positive_manual_repro_rate"] is None
    assert KpiSummary.model_validate(rendered).positive_manual_repro_rate is None
