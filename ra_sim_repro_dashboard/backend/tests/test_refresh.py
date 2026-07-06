from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import config_hash
from app.database import Base
from app.models import RefreshJob, Scenario, ScenarioVersionResult, Version
from app.services import refresh as refresh_module
from app.services.refresh import _normalize_result_raw
from app.services.scenario_client import build_source_scenario_index, source_counts_from_index


def test_normalize_result_raw_preserves_zero_values():
    raw = {
        "dpe_assist_channel_triggered__group1": 0,
        "assist_channel_triggered": 1,
        "road_triggered": False,
        "max_scen_dnn": 0,
        "scenario_dnn_stuck_likelihood_from_ra_vnode": 0.91,
        "threshold": 0,
        "stuck_threshold": 0.5,
    }

    normalized = _normalize_result_raw(raw)

    assert normalized["dpe_assist_channel_triggered"] == 0
    assert normalized["sim_triggered"] == 0
    assert normalized["road_triggered"] is False
    assert normalized["model_score_max"] == 0
    assert normalized["threshold"] == 0


def test_source_index_accumulates_groups_and_labels_for_same_scenario():
    class FakeScenarioClient:
        def query_label_set(self, labels):
            return [{"scenario_id": "s1", "scenario_name": "same scenario"}]

    metadata = {
        "scenario_sets": {
            "positive": {
                "labels": ["pos", "auto"],
                "manual_labels": ["pos", "manual"],
            },
            "negative": {
                "normal_stop_labels": ["neg", "normal_stop"],
            },
        }
    }

    index = build_source_scenario_index(metadata, FakeScenarioClient())

    assert set(index["s1"]["source_groups"]) == {
        "positive_auto",
        "positive_manual",
        "negative_normal_stop",
    }
    assert set(index["s1"]["source_labels"]) == {"pos", "auto", "manual", "neg", "normal_stop"}
    assert source_counts_from_index(index) == {
        "auto_trigger_tp": 1,
        "manual_trigger_fn": 1,
        "auto_trigger_fp": 0,
        "manual_trigger_irrelevant": 0,
        "normal_wait_tn_partial": 1,
        "total_scenarios": 1,
    }


def test_refresh_keeps_existing_results_when_sim_fetch_fails(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    payload = {
        "current_version": "v1",
        "compare_versions": [],
        "versions": {
            "v1": {
                "label": "release v1",
                "sim_jobs": {"positive_job_id": 101, "negative_job_id": 102},
                "source_gt_counts": {"auto_trigger_tp": 1, "manual_trigger_fn": 0, "auto_trigger_fp": 0},
            }
        },
    }
    try:
        db.add(RefreshJob(job_id="job1", status="queued", progress=0, config_hash=config_hash(payload)))
        db.add(
            Version(
                version_key="v1",
                label="release v1",
                metadata_json=payload["versions"]["v1"],
            )
        )
        db.add(Scenario(scenario_id="s1", scenario_name="existing"))
        db.add(
            ScenarioVersionResult(
                version_key="v1",
                scenario_id="s1",
                road_triggered=True,
                sim_triggered=True,
                reproduced=True,
                precision_label="TP",
                trigger_type="MODEL",
                root_cause="REPRODUCED",
            )
        )
        db.commit()

        monkeypatch.setattr(refresh_module, "load_versions_config", lambda: payload)

        def fail_query_eval_jobs(self, positive_job_id, negative_job_id, version_key):
            raise RuntimeError("sim backend timeout")

        monkeypatch.setattr(refresh_module.SimResultClient, "query_eval_jobs", fail_query_eval_jobs)

        refresh_module._refresh_dashboard("job1", db)

        rows = db.execute(select(ScenarioVersionResult)).scalars().all()
        job = db.get(RefreshJob, "job1")

        assert len(rows) == 1
        assert rows[0].scenario_id == "s1"
        assert job is not None
        assert job.status == "completed"
        assert "fallback" in job.message
    finally:
        db.close()
