from datetime import datetime, timedelta, timezone
from copy import deepcopy

from test_release_workflow import config, db, seed
from app.services import (
    release_watch as watch,
    release_workflow as w,
    workflow_orchestrator as orchestrator,
)
from app.services.release_inventory import inventory
from app.models import ReleaseSimulationBatch, ReleaseIssueSnapshot
from sqlalchemy import select

NEW = "gen4-release-20261009"
NOW = datetime.now(timezone.utc)


def observe(db, config, now=NOW):
    rows = [
        dict(
            issue_id="cn1",
            issue_topic="new case",
            issue_time=int((now - timedelta(hours=1)).timestamp() * 1000),
            version="1." + NEW + ".600",
            ra_type=2,
            ra_merge_result="成功",
        ),
        dict(
            issue_id="cn2",
            issue_topic="manual",
            issue_time=int((now - timedelta(hours=2)).timestamp() * 1000),
            version="1." + NEW + ".600",
            ra_type=3,
            ra_merge_result="成功",
        ),
    ]
    watch.monitor_tick(db, config, now=now, activity_fetcher=lambda _: (NEW, rows))
    return rows


def test_stable_default_and_collecting_details_no_simulation(db, config, monkeypatch):
    seed(db, config)
    monkeypatch.setattr(w, "effective_config", lambda _: config)
    rows = observe(db, config)
    value = inventory(db, config, NOW)
    assert value["default_release"] == config["periods"][0]["release"]
    new = value["versions"][0]
    assert (
        new["release"],
        new["collection_status"],
        new["issue_count"],
        new["auto_count"],
        new["manual_count"],
    ) == (NEW, "collecting", 2, 1, 1)
    assert orchestrator.list_issues(db, "@stable")["items"][0]["issue_id"] == "i1"
    current = orchestrator.list_issues(db, NEW)
    assert current["total"] == 2
    assert all(
        i["sim_triggered"] is None and i["simulation_status"] == "collecting"
        for i in current["items"]
    )
    assert orchestrator.list_issues(db, NEW, query="manual")["total"] == 1
    assert orchestrator.list_issues(db, NEW, page_size=1, page=2)["items"][0]["issue_id"] == "cn2"
    assert orchestrator.list_issues(db, NEW, label="fabricated")["total"] == 0
    assert db.scalars(select(ReleaseSimulationBatch)).all() == []
    assert len(db.scalars(select(ReleaseIssueSnapshot)).all()) == 1


def test_failed_observation_retains_rows_but_not_eligible(db, config, monkeypatch):
    monkeypatch.setattr(w, "effective_config", lambda _: config)
    observe(db, config)

    def fail(_):
        raise RuntimeError("source unavailable")

    watch.monitor_tick(db, config, now=NOW + timedelta(minutes=15), activity_fetcher=fail)
    item = inventory(db, config, NOW + timedelta(minutes=15))["versions"][0]
    assert item["stale"] and item["eligible_at"] is None
    assert orchestrator.list_issues(db, NEW)["total"] == 2
    assert inventory(db, config, NOW)["default_release"] is None


def test_stable_only_after_full_day_and_not_after_gap(db, config):
    rows = observe(db, config)
    for step in range(1, 97):
        watch.monitor_tick(
            db,
            config,
            now=NOW + timedelta(minutes=15 * step),
            activity_fetcher=lambda _: (NEW, rows),
        )
    value = inventory(db, config, NOW + timedelta(days=1))
    assert value["default_release"] == NEW
    assert value["versions"][0]["collection_status"] == "stable"
    value = inventory(db, config, NOW + timedelta(days=1, hours=4))
    assert value["default_release"] is None
    assert value["versions"][0]["stale"]


def test_missing_or_partial_snapshots_not_default(db, config, monkeypatch):
    monkeypatch.setattr(w, "effective_config", lambda _: config)
    assert inventory(db, config)["default_release"] is None
    assert orchestrator.list_issues(db, "@stable")["items"] == []
    seed(db, config)
    snap = db.scalars(select(ReleaseIssueSnapshot)).one()
    snap.payload = {**snap.payload, "population_complete": False}
    db.commit()
    assert inventory(db, config)["default_release"] is None


def test_same_count_replacement_visible_keeps_last_issue_age(db, config, monkeypatch):
    monkeypatch.setattr(w, "effective_config", lambda _: config)
    rows = observe(db, config)
    changed = deepcopy(rows)
    changed[0]["issue_id"] = "cn3"
    watch.monitor_tick(
        db, config, now=NOW + timedelta(minutes=15), activity_fetcher=lambda _: (NEW, changed)
    )
    assert {i["issue_id"] for i in orchestrator.list_issues(db, NEW)["items"]} == {"cn2", "cn3"}
    assert w.get_state(db, "release_monitor")["quiet_seconds"] == 4500


def test_previous_observer_remains_in_inventory_and_issue_browser(db, config, monkeypatch):
    monkeypatch.setattr(w, "effective_config", lambda _: config)
    rows = observe(db, config)
    newer = "gen4-release-20261016"
    watch.monitor_tick(
        db,
        config,
        now=NOW + timedelta(minutes=15),
        activity_fetcher=lambda _: (newer, [{**rows[0], "version": "1." + newer + ".610"}]),
    )
    versions = {
        v["release"]: v for v in inventory(db, config, NOW + timedelta(minutes=15))["versions"]
    }
    assert NEW in versions and newer in versions
    assert versions[NEW]["issue_count"] == 2
    assert orchestrator.list_issues(db, NEW)["total"] == 2


def test_simulation_view_keeps_frozen_results_when_collection_is_observed(db, config, monkeypatch):
    from app.services import release_inventory

    seed(db, config)
    monkeypatch.setattr(w, "effective_config", lambda _: config)
    snapshot = db.scalars(select(ReleaseIssueSnapshot)).one()
    release = snapshot.release
    monkeypatch.setattr(
        release_inventory,
        "inventory",
        lambda *a: {
            "default_release": release,
            "versions": [{"release": release, "source": "observation"}],
        },
    )
    monkeypatch.setattr(
        release_inventory,
        "observation_issues",
        lambda *a: {
            "items": [{"issue_id": "new-collection-only", "sim_triggered": None}],
            "total": 1,
        },
    )
    db.add(
        ReleaseSimulationBatch(
            fingerprint="frozen",
            release=release,
            status="complete",
            payload={
                "population_hash": w.population_identity(snapshot.payload),
                "scenarios": snapshot.payload["scenarios"],
                "results": {
                    "1": {"sim_triggered": True, "reproduced": True, "precision_label": "TP"}
                },
            },
        )
    )
    db.commit()
    assert (
        orchestrator.list_issues(db, release, view="collection")["items"][0]["issue_id"]
        == "new-collection-only"
    )
    result = orchestrator.list_issues(db, release, view="simulation")
    assert result["total"] == 2
    assert result["items"][0]["issue_id"] == "i1"
    assert result["items"][0]["scenario_id"] == "1"
    assert result["items"][0]["sim_triggered"] is True
    assert result["items"][0]["precision_label"] == "TP"


def test_known_completed_collection_stays_completed_when_observation_is_overdue(db, config):
    rows = observe(db, config)
    checked = NOW + timedelta(days=1)
    watch.monitor_tick(db, config, now=checked, activity_fetcher=lambda _: (NEW, rows))
    value = inventory(db, config, checked + timedelta(days=7))
    item = value["versions"][0]
    assert item["collection_completed"] is True and item["stale"] is True
    assert item["collection_status"] == "collecting"  # Freshness gate for writes is unchanged.
    assert value["default_release"] is None
    assert not db.scalars(select(ReleaseSimulationBatch)).all()


def test_elapsed_wall_clock_without_a_successful_observation_does_not_complete_collection(
    db, config
):
    observe(db, config)
    value = inventory(db, config, NOW + timedelta(days=7))
    assert value["versions"][0]["collection_completed"] is False
    assert value["versions"][0]["stale"] is True
    assert value["default_release"] is None


def test_a_new_issue_reopens_previously_completed_collection(db, config):
    rows = observe(db, config)
    checked = NOW + timedelta(days=1)
    watch.monitor_tick(db, config, now=checked, activity_fetcher=lambda _: (NEW, rows))
    assert inventory(db, config, checked)["versions"][0]["collection_completed"] is True
    changed = deepcopy(rows)
    changed.append(
        {**rows[0], "issue_id": "new-late-issue", "issue_time": int(checked.timestamp() * 1000)}
    )
    watch.monitor_tick(
        db, config, now=checked + timedelta(minutes=15), activity_fetcher=lambda _: (NEW, changed)
    )
    item = inventory(db, config, checked + timedelta(minutes=15))["versions"][0]
    assert item["collection_completed"] is False and item["collection_status"] == "collecting"
    assert not db.scalars(select(ReleaseSimulationBatch)).all()
