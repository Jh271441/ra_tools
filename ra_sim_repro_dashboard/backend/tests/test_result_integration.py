from copy import deepcopy
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models import ReleaseSimulationBatch, ReleaseWorkflowState
from app.services.result_integration import integrate, import_executions, TRIGGER


def fixture_data():
    scenes = [
        {
            "scenario_id": str(i),
            "issue_id": f"i{i}",
            "cohort": "positive_auto" if i == 1 else "negative_auto",
        }
        for i in (1, 2)
    ]
    plan = {
        "release": "gen4-release-20260904",
        "binary_id": 123,
        "population_hash": "source-hash",
        "driver_revision": "v1",
        "simulation": {
            "priority": "HIGH",
            "max_concurrency": 1000,
            "cache": "disabled",
        },
        "scenarios": scenes,
        "issues": [
            {"issue_id": "i1", "ra_type": 2, "ra_merge_result": "成功"},
            {"issue_id": "i2", "ra_type": 2, "ra_merge_result": "误触发"},
        ],
    }
    row = lambda s: {
        **s,
        "task_id": f"100{s['scenario_id']}",
        "task_status": 3,
        "task_outcome": "Done",
        "task_outcome_detail": "",
        "argument_hash": "args-" + s["scenario_id"],
        "simulator_cache_hit": False,
        "inference_log_count": 1,
        "dpe_output_count": 1,
        "output_bag_count": 1,
        "failed_evaluation_count": 0,
        "unexpected_warning_count": 0,
        TRIGGER: 1 if s["scenario_id"] == "1" else 0,
    }
    export = lambda jid: {
        "job_id": jid,
        "release": plan["release"],
        "binary_id": 123,
        "population_hash": "source-hash",
        "progress": {
            "job_id": jid,
            "state": "COMPLETED",
            "total": 2,
            "completed": 2,
            "failed": 0,
            "cancelled": 0,
        },
        "rows": [row(s) for s in scenes],
        "quality": {"quality": {}},
    }
    return plan, [export(100), export(200)]


def fail(export, index):
    export["rows"][index].update(
        task_status=4, task_outcome="Planner crashed", **{TRIGGER: None}
    )
    export["progress"].update(completed=1, failed=1)


def test_same_task_two_executions_count_population_once():
    plan, exports = fixture_data()
    r = integrate(plan, exports, 100)
    assert (
        r["scenario_count"] == 2
        and len(r["results"]) == 2
        and r["subset_summary"]["eligible"] == 2
    )
    assert r["comparison"] == {"comparable": 2, "agree": 2, "conflicts": []}
    assert r["quality_gate_passed"]


def test_secondary_success_cannot_hide_primary_failure():
    plan, exports = fixture_data()
    fail(exports[0], 1)
    r = integrate(plan, exports, 100)
    assert len(r["results"]) == 1 and r["coverage"] == 0.5
    assert not r["summary"]["available"] and not r["quality_gate_passed"]
    assert r["subset_summary"]["precision"] == 1 and r["missing_scenario_count"] == 1
    assert r["scenario_results"]["2"]["status"] == "failed"


def test_conflicting_rerun_does_not_choose_better_result():
    plan, exports = fixture_data()
    exports[1]["rows"][0][TRIGGER] = 0
    r = integrate(plan, exports, 100)
    assert r["results"]["1"]["sim_triggered"] is True
    assert r["comparison"]["conflicts"] == ["1"] and not r["quality_gate_passed"]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "different_binary",
        "arguments",
        "nonterminal",
        "source",
        "counts",
    ],
)
def test_import_rejects_wrong_identity_or_population(change):
    plan, exports = fixture_data()
    if change == "missing":
        exports[1]["rows"].pop()
    if change == "duplicate":
        exports[1]["rows"].append(exports[1]["rows"][0])
    if change == "different_binary":
        exports[1]["binary_id"] = 999
    if change == "arguments":
        exports[1]["rows"][0]["argument_hash"] = "changed"
    if change == "nonterminal":
        exports[1]["progress"]["state"] = "RUNNING"
    if change == "source":
        exports[1]["rows"][0]["cohort"] = "positive_manual"
    if change == "counts":
        exports[1]["progress"]["completed"] = 1
    with pytest.raises(ValueError):
        integrate(plan, exports, 100)


@pytest.mark.parametrize(
    "field,value",
    [
        ("simulator_cache_hit", True),
        ("inference_log_count", 0),
        ("failed_evaluation_count", 1),
        (TRIGGER, None),
        (TRIGGER, float("nan")),
    ],
)
def test_artifact_quality_failures_do_not_create_labels(field, value):
    plan, exports = fixture_data()
    exports[0]["rows"][0][field] = value
    r = integrate(plan, exports, 100)
    assert "1" not in r["results"] and not r["quality_gate_passed"]
    assert r["scenario_results"]["1"]["status"] == "quality_failed"


def test_database_import_preserves_attempts_and_primary_only():
    plan, exports = fixture_data()
    fail(exports[0], 1)
    fail(exports[1], 1)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
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
        r = import_executions(db, plan, exports, 100)
        primary = db.get(ReleaseSimulationBatch, "100")
        other = db.get(ReleaseSimulationBatch, "200")
        assert primary.status == "quality_failed" and other.status == "quality_failed"
        assert len(primary.payload["results"]) == 1 and "results" not in other.payload
        assert (
            primary.payload["result_import"]["task_key"]
            == other.payload["result_import"]["task_key"]
        )
        assert (
            db.get(ReleaseWorkflowState, "job-progress:100").payload["value"]["state"]
            == "COMPLETED"
        )
        import_executions(db, plan, exports, 100)
        assert len(list(db.scalars(select(ReleaseSimulationBatch)))) == 2


def test_minus_one_is_a_valid_untriggered_dpe_value():
    plan, exports = fixture_data()
    for e in exports:
        e["rows"][1][TRIGGER] = -1
    result = integrate(plan, exports, 100)
    assert result["valid_scenario_count"] == 2
    assert result["results"]["2"]["precision_label"] == "TN"
    assert result["subset_summary"]["recall"] == 1
