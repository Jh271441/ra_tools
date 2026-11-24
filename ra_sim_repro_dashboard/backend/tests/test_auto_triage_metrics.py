from copy import deepcopy
from datetime import datetime, timezone, timedelta
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch, ReleaseWorkflowState
from app.services import auto_triage_metrics as lane, release_workflow as workflow

RELEASE = "gen4-release-20261016"


def dashboard_receipt(labels, scope):
    """SQL reference, independent of the Python membership implementation."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE source(issue_id TEXT, trigger TEXT, auto TEXT, baseline TEXT)")
    raw = {
        0: "未填写",
        1: "成功",
        2: "失败",
        3: "限制使用",
        4: "无需协助",
        5: "误触发",
        6: "未接起",
    }
    for iid, row in labels.items():
        value = row.get(
            "merged_ra_auto_result",
            row["ra_stuck_auto_result"]
            if row["ra_stuck_auto_result"] is not None
            else raw.get(row["ra_result"], row["ra_result"]),
        )
        db.execute(
            "INSERT INTO source VALUES(?,?,?,?)",
            (iid, "自触发" if row["ra_type"] == 2 else "人工触发", value, row["ra_merge_result"]),
        )
    rows = []
    for iid, trigger, auto, baseline in db.execute("SELECT * FROM source"):
        row = {
            "issue_id": iid,
            "big_version": "1." + scope["release"],
            "create_date": scope["date_start"],
            "ra_trigger_type": trigger,
            "merged_ra_auto_result": auto,
            "merged_ra_result": baseline,
            "trip_odd": "ODD2",
            "trip_category_name": "Daily Cruise/稳定版本测试",
            "version_category": "release版本",
            "is_deleted": 0,
        }
        for prefix, column in (("auto", "auto"), ("baseline", "baseline")):
            conditions = {
                "precision_numerator": f"trigger='自触发' AND {column} IN ('成功','失败','无需协助','限制使用')",
                "precision_denominator": f"trigger='自触发' AND {column} NOT IN ('out_of_scope','未接起','未填写')",
                "recall_numerator": f"trigger='自触发' AND {column} NOT IN ('误触发','out_of_scope','未接起','未填写')",
                "recall_denominator": f"trigger IN ('自触发','人工触发') AND {column} NOT IN ('误触发','out_of_scope','未接起','未填写')",
            }
            for name, condition in conditions.items():
                value = db.execute(
                    "SELECT CASE WHEN "
                    + condition
                    + " THEN 1 ELSE 0 END FROM source WHERE issue_id=?",
                    (iid,),
                ).fetchone()[0]
                row[prefix + "_" + name] = value
        rows.append(row)
    db.close()
    names = (
        [k for k in rows[0] if k.startswith(("auto_", "baseline_"))]
        if rows
        else [
            prefix + "_" + name
            for prefix in ("auto", "baseline")
            for name in (
                "precision_numerator",
                "precision_denominator",
                "recall_numerator",
                "recall_denominator",
            )
        ]
    )
    counts = {name: sum(row[name] for row in rows) for name in names}
    counts.update(population_count=len(rows), big_version="1." + scope["release"])
    return {
        "scope": scope,
        "rows": rows,
        "counts": counts,
        "observed_at": "2026-11-04T03:50:00+00:00",
        "references": [],
    }


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def sample():
    labels = [
        ("a", 2, "成功", "误触发", 1),
        ("b", 2, "误触发", "正确触发", 5),
        ("c", 3, "误触发", "成功", 5),
        ("d", 3, "成功", None, 5),
        ("e", 2, "out_of_scope", None, 2),
        ("f", 2, "成功", None, None),
        ("g", 2, "成功", None, 4),
    ]
    issues, observed, scenes, results = [], {}, [], {}
    for index, (iid, trigger, baseline, model, raw) in enumerate(labels):
        row = {
            "issue_id": iid,
            "ra_type": trigger,
            "ra_merge_result": baseline,
            "issue_topic": "Issue " + iid,
            "version": RELEASE,
            "issue_time": 1000 + index,
            "trip_id": "trip-" + iid,
            "ra_start_timestamp": 500 + index,
            "trip_start_time": 0,
            "trip_end_time": 10000,
        }
        issues.append(row)
        observed[iid] = {**row, "ra_stuck_auto_result": model, "ra_result": raw, "is_deleted": 0}
        if iid == "c":
            continue
        sid = "s-" + iid
        scenes.append(
            {
                "scenario_id": sid,
                "issue_id": iid,
                "scenario_revision": 1,
                "start_timestamp": 0,
                "end_timestamp": 10000,
            }
        )
        results[sid] = {"sim_triggered": iid in ("a", "b"), "job_id": 123}
    payload = {
        "period": {
            "release": RELEASE,
            "case_start": "2026-10-16T00:00:00+08:00",
            "case_end_exclusive": "2026-10-24T00:00:00+08:00",
            "binary_id": 456,
        },
        "issues": issues,
        "scenarios": scenes,
        "population_complete": True,
    }
    return payload, observed, results


@pytest.mark.parametrize(
    ("row", "label", "source", "complete"),
    [
        ({"ra_stuck_auto_result": "正确触发", "ra_result": 5}, "正确触发", "model", True),
        ({"ra_stuck_auto_result": "误触发", "ra_result": 1}, "误触发", "model", True),
        ({"ra_stuck_auto_result": None, "ra_result": 3}, "限制使用", "ra_result", True),
        ({"ra_stuck_auto_result": None, "ra_result": 0}, "未填写", "ra_result", True),
        ({"ra_stuck_auto_result": None, "ra_result": None}, None, "ra_result", True),
        ({"ra_stuck_auto_result": "", "ra_result": 1}, "", "model", True),
        ({"ra_merge_result": "成功"}, None, "missing", False),
        (
            {"merged_ra_auto_result": None, "ra_stuck_auto_result": "成功", "ra_result": 1},
            None,
            "warehouse",
            True,
        ),
    ],
)
def test_coalesce_uses_original_result_not_human_merge(row, label, source, complete):
    assert lane.resolve_label(row) == (label, source, complete)


def test_reclassify_old_excluded_manual_and_keep_partial_metrics_explicit():
    payload, labels, results = sample()
    original = deepcopy((payload, labels, results))
    value = lane.project(payload, labels, results)
    m = value["metrics"]
    assert (m["eligible"], m["covered"], m["missing_results"]) == (5, 4, 1)
    assert m["online_precision"] == 2 / 4 and m["online_recall"] == 3 / 4
    assert m["precision"] is None and m["recall"] is None and not m["available"]
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (0, 2, 2, 0)
    assert m["sim_recall_numerator"] == 1
    assert value["newly_eligible"] == 2
    assert value["coverage_reasons"] == {"missing_scenario": 1}
    assert next(r for r in value["rows"] if r["issue_id"] == "c")["new_cohort"] == "positive_manual"
    assert next(r for r in value["rows"] if r["issue_id"] == "f")["auto_label"] is None
    assert m["unclassified"] == 0
    assert (payload, labels, results) == original
    # A supplemental result is needed only for the one uncovered physical input.
    payload["scenarios"].append({"scenario_id": "s-c", "issue_id": "c"})
    results["s-c"] = {"sim_triggered": True, "job_id": 124}
    full = lane.project(payload, labels, results)["metrics"]
    assert full["available"] and full["precision"] == 1 / 3 and full["recall"] == 2 / 4


def test_missing_projection_empty_string_and_unknown_enum_do_not_fake_coverage():
    payload, labels, results = sample()
    del labels["a"]["ra_stuck_auto_result"]
    value = lane.project(payload, labels, results)["metrics"]
    assert value["missing_labels"] == 1 and value["online_precision"] is None
    labels["a"]["ra_stuck_auto_result"] = ""
    value = lane.project(payload, labels, results)["metrics"]
    assert value["unclassified"] == 1
    # The exact source SQL counts an unknown non-null enum in the NOT IN sets.
    assert value["precision_denominator"] == 4 and value["recall_denominator"] == 5
    assert not value["available"]


def test_false_is_a_result_missing_scenario_is_not_a_false_negative():
    payload, labels, results = sample()
    rows = lane.project(payload, labels, results)["rows"]
    assert next(r for r in rows if r["issue_id"] == "g")["precision_label"] == "FN"
    missing = next(r for r in rows if r["issue_id"] == "c")
    assert missing["sim_triggered"] is None and missing["precision_label"] is None
    payload["scenarios"].append({"scenario_id": "g-extra", "issue_id": "g"})
    value = lane.project(payload, labels, results)
    assert (
        next(r for r in value["rows"] if r["issue_id"] == "g")["result_status"] == "missing_result"
    )
    labels["a"]["ra_start_timestamp"] += 1
    value = lane.project(payload, labels, results)
    assert (
        next(r for r in value["rows"] if r["issue_id"] == "a")["result_status"] == "input_changed"
    )
    assert value["metrics"]["covered"] == 2


@pytest.fixture
def prepared(db, monkeypatch):
    payload, labels, results = sample()
    snapshot = ReleaseIssueSnapshot(release=RELEASE, period_hash="period", payload=payload)
    batch_payload = {
        **deepcopy(payload),
        "release": RELEASE,
        "job_id": 123,
        "binary_id": 456,
        "simulation": {"independent_replay": True},
        "driver_revision": "driver",
        "results": {
            sid: {**row, "precision_label": "stale", "reproduced": True}
            for sid, row in results.items()
        },
        "scenario_results": {sid: {"status": "result_ready", "errors": []} for sid in results},
        "result_import": {"primary": True, "execution_contract_hash": "runtime"},
    }
    batch = ReleaseSimulationBatch(
        fingerprint="base", release=RELEASE, status="complete", payload=batch_payload
    )
    db.add_all([snapshot, batch])
    db.commit()
    monkeypatch.setattr(
        lane, "publication", lambda b: {"available": True} if b.fingerprint == "base" else None
    )
    monkeypatch.setattr(
        workflow,
        "driver_call",
        lambda *_: (_ for _ in ()).throw(AssertionError("Simulation must not be submitted")),
    )
    monkeypatch.setattr(lane.warehouse, "fetch", lambda scope: dashboard_receipt(labels, scope))
    return db, snapshot, batch, labels


def test_versioned_recalculation_is_idempotent_and_original_batch_immutable(prepared):
    db, snap, batch, labels = prepared
    old = deepcopy(batch.payload)
    result = lane.recalculate(db, RELEASE, fetcher=lambda ids: deepcopy(labels))
    assert result["metrics"]["fp"] == 2 and result["source_job_ids"] == [123]
    assert lane.report(db, RELEASE)["status"] == "needs_simulation"
    again = lane.recalculate(
        db,
        RELEASE,
        refresh_labels=False,
        fetcher=lambda _: pytest.fail("Unexpected upstream query"),
    )
    assert again["revision_key"] == result["revision_key"]
    assert (
        len(
            [
                s
                for s in db.scalars(select(ReleaseWorkflowState))
                if s.key.startswith("at_revision:")
            ]
        )
        == 1
    )
    assert batch.payload == old
    gap = lane.gap_plan(db, RELEASE)
    assert gap["gap_count"] == 1 and gap["issues"][0]["issue_id"] == "c"
    assert gap["simulation_submitted"] is False
    assert gap["issues"][0]["source_inputs"]["trip_id"] == "trip-c"
    assert gap["issues"][0]["observed_inputs"] == gap["issues"][0]["source_inputs"]
    assert gap["source_snapshot_id"] == snap.id and gap["label_key"] == result["label_key"]
    page = lane.issue_page(db, RELEASE, 1, 20, coverage="gap")
    assert page["total"] == 1 and page["items"][0]["issue_id"] == "c"
    before = deepcopy(snap.payload)
    before["issues"][0]["ra_start_timestamp"] += 1
    snap.payload = before
    db.commit()
    assert lane.report(db, RELEASE)["status"] == "source_changed"
    assert lane.report(db, RELEASE)["result"] is None


def test_incompatible_child_and_changed_execution_are_not_reused(prepared):
    db, snapshot, base, labels = prepared
    child_payload = deepcopy(base.payload)
    child_payload.update(binary_id=999, job_id=124, backfill={"base_fingerprint": "base"})
    db.add(
        ReleaseSimulationBatch(
            fingerprint="wrong-binary", release=RELEASE, status="complete", payload=child_payload
        )
    )
    db.commit()
    results, lineage, warnings, _ = lane.reusable_results(db, base, snapshot.payload)
    assert {r["job_id"] for r in results.values()} == {123}
    assert warnings == [{"job_id": 124, "reason": "execution_contract_changed"}]
    lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    modified = deepcopy(base.payload)
    modified["results"]["s-a"]["sim_triggered"] = False
    base.payload = modified
    db.commit()
    assert lane.report(db, RELEASE)["status"] == "execution_changed"


def test_partial_label_fetch_preserves_previous_revision(prepared):
    db, _, _, labels = prepared
    first = lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    with pytest.raises(ValueError, match="label_population_mismatch"):
        lane.recalculate(
            db, RELEASE, fetcher=lambda _: {k: v for k, v in labels.items() if k != "a"}
        )
    assert lane.report(db, RELEASE)["result"]["revision_key"] == first["revision_key"]


def test_new_target_binary_does_not_reuse_previous_binary_results(prepared):
    db, snapshot, base, labels = prepared
    payload = deepcopy(snapshot.payload)
    payload["period"]["binary_id"] = 999
    snapshot.payload = payload
    db.commit()
    results, lineage, warnings, incompatible = lane.reusable_results(db, base, payload)
    assert results == {} and lineage == {}
    assert warnings == [{"job_id": 123, "reason": "binary_changed"}]
    assert incompatible == {s["scenario_id"] for s in payload["scenarios"]}
    value = lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    assert value["metrics"]["covered"] == 0
    assert not value["metrics"]["available"]
    assert lane.gap_plan(db, RELEASE)["binary_id"] == 999


def test_search_handles_null_or_numeric_source_titles(prepared):
    db, snapshot, _, labels = prepared
    payload = deepcopy(snapshot.payload)
    payload["issues"][0]["issue_topic"] = None
    payload["issues"][1]["issue_topic"] = 1228
    payload["issues"][2]["issue_topic"] = ["source-list-title"]
    snapshot.payload = payload
    db.commit()
    lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    assert lane.issue_page(db, RELEASE, query="no-such-issue")["total"] == 0
    assert lane.issue_page(db, RELEASE, query="1228")["items"][0]["issue_id"] == "b"
    assert lane.issue_page(db, RELEASE, query="source-list-title")["items"][0]["issue_id"] == "c"


def test_removed_primary_execution_invalidates_previous_metrics(prepared):
    db, _, base, labels = prepared
    lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    db.delete(base)
    db.commit()
    value = lane.report(db, RELEASE)
    assert value["status"] == "execution_missing"
    assert value["result"] is None


def test_source_sync_preserves_null_but_not_absent_projection(monkeypatch):
    calls = []
    from app.services import release_source

    monkeypatch.setattr(release_source, "trail_credentials", lambda: ("app", "token"))

    def query(url, body, *args):
        calls.append(body)
        return {
            iid: {k: iid if k == "issue_id" else None for k in lane.QUERY_FIELDS}
            for iid in body["issue_id_list"]
        }

    monkeypatch.setattr(release_source, "signed_query", query)
    result = lane.fetch_labels([str(i) for i in range(401)])
    assert len(result) == 401 and [len(c["issue_id_list"]) for c in calls] == [200, 200, 1]
    assert result["1"]["ra_stuck_auto_result"] is None
    monkeypatch.setattr(release_source, "signed_query", lambda *args: {"1": {"issue_id": "1"}})
    with pytest.raises(ValueError, match="projection_incomplete"):
        lane.fetch_labels(["1"])


def test_read_apis_never_query_upstream_or_submit_and_validate_pages(prepared, monkeypatch):
    from app.api.release_routes import router

    db, _, _, labels = prepared
    lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    monkeypatch.setattr(lane, "fetch_labels", lambda *_: pytest.fail("GET must not query Trail"))
    # Service-layer read APIs remain pure DB reads without querying upstream.
    assert lane.report(db, RELEASE)["result"]["metrics"]["covered"] == 4
    assert lane.issue_page(db, RELEASE, coverage="gap")["total"] == 1
    assert lane.gap_plan(db, RELEASE)["simulation_submitted"] is False
    # Deprecated v1 HTTP routes under /api/dashboard/workflow/auto-triage* are retired in favor of /api/dashboard/evaluation*.
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    prefix = "/api/dashboard/workflow/auto-triage"
    assert client.get(prefix, params={"release": RELEASE}).status_code == 404
    assert client.get(prefix + "/issues", params={"release": RELEASE}).status_code == 404
    assert client.get(prefix + "/gap-plan", params={"release": RELEASE}).status_code == 404
    assert client.post(prefix + "/recalculate", json={"release": RELEASE}).status_code == 404


def test_input_change_during_label_read_rejects_publication(prepared):
    db, snapshot, _, labels = prepared

    def changed(_):
        p = deepcopy(snapshot.payload)
        p["issues"][0]["trip_id"] = "other-trip"
        snapshot.payload = p
        db.commit()
        return labels

    with pytest.raises(ValueError, match="source_changed"):
        lane.recalculate(db, RELEASE, fetcher=changed)
    assert not workflow.get_state(db, "auto_triage:" + RELEASE)


def test_compact_legacy_plan_binds_to_snapshot_before_registration(prepared):
    db, snapshot, base, _ = prepared
    snapshot.created_at = datetime(2026, 10, 20)
    base.created_at = datetime(2026, 10, 21)
    p = deepcopy(base.payload)
    p["population_hash"] = workflow.population_identity(snapshot.payload)
    p["issues"] = [
        {k: row[k] for k in ("issue_id", "ra_type", "ra_merge_result")} for row in p["issues"]
    ]
    base.payload = p
    later = deepcopy(snapshot.payload)
    later["issues"][0]["trip_id"] = "later-edited-trip"
    # Legacy population hashes did not include trip IDs; a later equal hash is
    # not evidence of the inputs that were actually registered for this job.
    assert workflow.population_identity(later) == p["population_hash"]
    db.add(
        ReleaseIssueSnapshot(
            release=RELEASE, period_hash="later", payload=later, created_at=datetime(2026, 10, 22)
        )
    )
    db.commit()
    inputs, binding = lane.execution_inputs(db, base)
    assert binding["snapshot_id"] == snapshot.id and inputs["a"]["trip_id"] == "trip-a"
    results, _, _, _ = lane.reusable_results(db, base, snapshot.payload)
    assert len(results) == 6
    snapshot.payload = {**snapshot.payload, "issues": []}
    db.commit()
    assert lane.execution_inputs(db, base)[1]["kind"] == "unverified"


def test_refresh_failure_retry_and_stale_request_keep_previous_result(
    prepared, monkeypatch, tmp_path
):
    import app.database as database

    db, _, _, labels = prepared
    first = lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    monkeypatch.setattr(database, "SessionLocal", lambda: Session(db.get_bind()))
    monkeypatch.setenv("RELEASE_WORKFLOW_LOCK", str(tmp_path / "release.lock"))
    initial = lane.queue_refresh(db, RELEASE)
    assert lane.queue_refresh(db, RELEASE)["request_id"] == initial["request_id"]
    recalculate = lane.recalculate
    monkeypatch.setattr(
        lane,
        "recalculate",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database read unavailable")),
    )
    lane.process_refresh(RELEASE)
    db.expire_all()
    failed = lane.report(db, RELEASE)
    assert failed["refresh"]["status"] == "failed"
    assert failed["result"]["revision_key"] == first["revision_key"]
    lane.queue_refresh(db, RELEASE)
    monkeypatch.setattr(lane, "recalculate", recalculate)
    monkeypatch.setattr(
        lane, "fetch_labels", lambda _: pytest.fail("DB-only refresh must not query Trail")
    )
    lane.process_refresh(RELEASE)
    db.expire_all()
    assert lane.report(db, RELEASE)["refresh"]["status"] == "complete"
    refresh_key = lane.view_context(db, RELEASE)[4]
    workflow.put_state(
        db,
        refresh_key,
        {
            "status": "running",
            "requested_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        },
    )
    assert lane.report(db, RELEASE)["refresh"]["status"] == "failed"
    assert lane.queue_refresh(db, RELEASE)["status"] == "queued"


def test_background_trail_observation_cannot_replace_dashboard_labels(
    prepared, monkeypatch, tmp_path
):
    db, _, _, labels = prepared
    monkeypatch.setenv("RELEASE_WORKFLOW_LOCK", str(tmp_path / "release.lock"))
    initial = lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    changed = deepcopy(labels)
    changed["b"]["ra_stuck_auto_result"] = "误触发"
    observed_at = datetime.now(timezone.utc).isoformat()
    workflow.put_state(
        db,
        "release_observation:" + RELEASE,
        {"issues": list(changed.values()), "observed_at": observed_at},
    )
    monkeypatch.setattr(
        lane, "fetch_labels", lambda _: pytest.fail("Fresh observations must be reused")
    )
    lane.refresh_observed(db, RELEASE)
    after = lane.report(db, RELEASE)
    assert after["result"]["revision_key"] == initial["revision_key"]
    assert after["label_checked_at"] == "2026-11-04T03:50:00+00:00"
    # A still-fresh observation from before the manual sync cannot roll it back.
    workflow.put_state(
        db,
        "release_observation:" + RELEASE,
        {
            "issues": list(labels.values()),
            "observed_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        },
    )
    lane.refresh_observed(db, RELEASE)
    current = lane.report(db, RELEASE)
    assert current["result"]["revision_key"] == after["result"]["revision_key"]
    assert current["label_checked_at"] == after["label_checked_at"]
    workflow.put_state(
        db,
        "release_observation:" + RELEASE,
        {
            "issues": list(labels.values()),
            "observed_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        },
    )
    lane.refresh_observed(db, RELEASE)
    assert lane.report(db, RELEASE)["result"]["revision_key"] == after["result"]["revision_key"]


def test_literal_correct_trigger_has_different_precision_and_recall_sets():
    payload, labels, results = sample()
    payload["issues"] = [r for r in payload["issues"] if r["issue_id"] == "b"]
    payload["scenarios"] = [r for r in payload["scenarios"] if r["issue_id"] == "b"]
    value = lane.project(payload, {"b": labels["b"]}, results)
    m = value["metrics"]
    assert m["available"] and m["online_precision"] == 0 and m["online_recall"] == 1
    assert m["precision"] == 0 and m["recall"] == 1
    assert value["rows"][0]["auto_label"] == "正确触发"
    assert value["rows"][0]["sim_memberships"] == {
        "precision_numerator": 0,
        "precision_denominator": 1,
        "recall_numerator": 1,
        "recall_denominator": 1,
    }


def test_dashboard_population_replaces_inventory_without_editing_it(prepared):
    db, snapshot, batch, labels = prepared
    before = deepcopy(snapshot.payload)
    selected = deepcopy(labels)
    del selected["a"]
    added = deepcopy(labels["c"])
    added.update(issue_id="new", trip_id="trip-new")
    selected["new"] = added
    result = lane.recalculate(
        db,
        RELEASE,
        fetcher=lambda _: deepcopy(selected),
        warehouse_fetcher=lambda scope: dashboard_receipt(selected, scope),
    )
    assert result["source_count"] == len(selected)
    assert result["reconciliation"]["dashboard_only_ids"] == ["new"]
    assert result["reconciliation"]["inventory_only_ids"] == ["a"]
    assert (
        next(r for r in result["rows"] if r["issue_id"] == "new")["result_status"]
        == "missing_scenario"
    )
    assert snapshot.payload == before and len(batch.payload["issues"]) == len(before["issues"])


def test_dashboard_mismatch_or_login_failure_retains_previous_verified_result(
    prepared, monkeypatch
):
    db, _, _, labels = prepared
    first = lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))

    def bad(scope):
        value = dashboard_receipt(labels, scope)
        value["rows"][0]["auto_precision_numerator"] = 1
        return value

    with pytest.raises(ValueError, match="dashboard_membership_mismatch"):
        lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels), warehouse_fetcher=bad)
    monkeypatch.setattr(
        lane.warehouse,
        "fetch",
        lambda _: (_ for _ in ()).throw(ValueError("dashboard_login_required")),
    )
    with pytest.raises(ValueError, match="dashboard_login_required"):
        lane.recalculate(
            db,
            RELEASE,
            fetcher=lambda _: pytest.fail("Do not substitute Trail after warehouse failure"),
        )
    assert lane.report(db, RELEASE)["result"]["revision_key"] == first["revision_key"]


def test_date_scopes_are_isolated_and_unverified_old_pointer_is_not_served(prepared):
    db, _, _, labels = prepared
    first = lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    second = lane.recalculate(
        db,
        RELEASE,
        fetcher=lambda _: deepcopy(labels),
        date_start="2026-10-17",
        date_end="2026-10-22",
    )
    assert first["revision_key"] != second["revision_key"]
    assert lane.report(db, RELEASE)["result"]["revision_key"] == first["revision_key"]
    assert (
        lane.report(db, RELEASE, "2026-10-17", "2026-10-22")["result"]["revision_key"]
        == second["revision_key"]
    )
    workflow.put_state(db, "auto_triage:" + RELEASE, {"revision_key": first["revision_key"]})
    db.delete(db.get(ReleaseWorkflowState, lane.view_context(db, RELEASE)[3]))
    db.commit()
    assert lane.report(db, RELEASE)["result"] is None
    assert lane.report(db, RELEASE)["status"] == "dashboard_required"
    assert all(len(row.key) <= 64 for row in db.scalars(select(ReleaseWorkflowState)))


def test_user_exclusion_preserves_dashboard_counts_and_requires_review(prepared):
    db, snapshot, _, labels = prepared
    payload = deepcopy(snapshot.payload)
    next(r for r in payload["issues"] if r["issue_id"] == "g")["evaluation_exclusion"] = {
        "approved_by": "user",
        "reason": "Preserve the original review decision",
    }
    snapshot.payload = payload
    db.commit()
    value = lane.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    assert value["metrics"]["precision_auto_tp"] == 2
    assert value["metrics"]["recall_auto_tp"] == 3
    assert value["coverage_reasons"]["user_exclusion"] == 1
    plan = lane.gap_plan(db, RELEASE)
    assert plan["requires_user_review"] is True
    case = next(r for r in plan["issues"] if r["issue_id"] == "g")
    assert case["evaluation_exclusion"]["approved_by"] == "user"
    assert case["sim_triggered"] is None and case["precision_label"] is None
