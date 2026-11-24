"""Cold reads skip irrelevant payloads without weakening execution audits."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.models import ReleaseWorkflowState
from app.services import evaluation_pipeline as p, reproduction_evidence as evidence
from app.services import auto_triage_metrics as at, release_workflow as w
from app.services.release_cycle import digest
from test_auto_triage_metrics import db, prepared, RELEASE


def approved_target(db, snapshot):
    period = {
        **snapshot.payload["period"],
        "verified": True,
        "binary_id": 789,
        "binary_evidence": {"source": "verified"},
    }
    plan = {
        "release": RELEASE,
        "period": period,
        "binary_id": 789,
        "template_job_id": 456,
        "simulation": {"cache": "disabled"},
        "driver_revision": "approved-driver",
    }
    execution = {
        "id": "approved",
        "status": "complete",
        "job_id": 987,
        "plan": plan,
        "results": {"scene": {"sim_triggered": True}},
        "export": {
            "release": RELEASE,
            "binary_id": 789,
            "job_id": 987,
            "execution_contract_hash": "approved-contract",
        },
        "preflight": {"execution_contract_hash": "approved-contract"},
    }
    execution["audit_hash"] = p.execution_audit_hash(execution)
    w.put_state(db, "evexecution:approved", execution)
    w.put_state(
        db,
        "evaluation_target:" + RELEASE,
        {"release": RELEASE, "execution_id": "approved", "audit_hash": execution["audit_hash"]},
    )
    return execution


def test_approved_target_skips_legacy_payloads_and_retains_runtime_overrides(prepared, monkeypatch):
    db, snapshot, _, _ = prepared
    execution = approved_target(db, snapshot)
    original = deepcopy(execution)
    config = {"simulation": {"warmup_ms_by_release": {RELEASE: 15000}}}
    monkeypatch.setattr(w, "effective_config", lambda _: config)
    monkeypatch.setattr(
        at, "_base", lambda *_: pytest.fail("Approved target must not load legacy batches")
    )

    expected = {
        key: deepcopy(execution["plan"][key])
        for key in ("period", "binary_id", "template_job_id", "simulation", "driver_revision")
    }
    expected["simulation"].update(w.execution_overrides(config, RELEASE))
    assert p.target(db, snapshot) == expected
    assert w.get_state(db, "evexecution:approved") == original


@pytest.mark.parametrize("corruption", ["audit_hash", "contract", "period", "status"])
def test_invalid_approved_target_still_fails_closed(prepared, monkeypatch, corruption):
    db, snapshot, _, _ = prepared
    execution = approved_target(db, snapshot)
    if corruption == "audit_hash":
        execution["results"]["scene"]["sim_triggered"] = False
    elif corruption == "contract":
        execution["preflight"]["execution_contract_hash"] = "changed"
    elif corruption == "period":
        execution["plan"]["period"]["verified"] = False
    else:
        execution["status"] = "running"
    # Keep the remaining receipt internally consistent so each audit boundary
    # is exercised independently.
    if corruption == "period":
        execution["audit_hash"] = p.execution_audit_hash(execution)
        w.put_state(
            db,
            "evaluation_target:" + RELEASE,
            {"release": RELEASE, "execution_id": "approved", "audit_hash": execution["audit_hash"]},
        )
    w.put_state(db, "evexecution:approved", execution)
    monkeypatch.setattr(w, "effective_config", lambda _: {"simulation": {}})
    monkeypatch.setattr(
        at, "_base", lambda *_: pytest.fail("Invalid activation cannot fall back to legacy results")
    )

    with pytest.raises(ValueError, match="plan_stale"):
        p.target(db, snapshot)


def test_target_without_activation_preserves_legacy_specification(prepared, monkeypatch):
    db, snapshot, batch, _ = prepared
    monkeypatch.setattr(w, "effective_config", lambda _: {"simulation": {}})
    payload = batch.payload
    assert p.target(db, snapshot) == {
        "period": {**snapshot.payload["period"], **payload["period"]},
        "binary_id": payload["binary_id"],
        "template_job_id": payload["job_id"],
        "simulation": payload["simulation"],
        "driver_revision": payload["driver_revision"],
    }


def test_execution_receipt_is_audited_once_per_get_and_detects_later_corruption(
    prepared, monkeypatch
):
    from app.services import read_views

    db, snapshot, _, _ = prepared
    execution = approved_target(db, snapshot)
    binding = {"execution_id": execution["id"], "audit_hash": execution["audit_hash"]}
    monkeypatch.setattr(w, "effective_config", lambda _: {"simulation": {}})
    actual_hash = p.execution_audit_hash
    audits = []

    def audit(value):
        audits.append(value.get("id"))
        return actual_hash(value)

    monkeypatch.setattr(p, "execution_audit_hash", audit)

    def load():
        p.target(db, snapshot)
        assert all(p.binding_valid(db, binding) for _ in range(100))
        return "verified"

    assert read_views.read_view(db, "audited-target", load) == "verified"
    assert audits == ["approved"]
    # The memo ends with this request, even for another read in the same Session.
    assert read_views.read_view(db, "another-target", load) == "verified"
    assert audits == ["approved", "approved"]
    changed = deepcopy(execution)
    changed["results"]["scene"]["sim_triggered"] = False
    w.put_state(db, "evexecution:approved", changed)
    assert (
        read_views.read_view(db, "binding-after-write", lambda: p.binding_valid(db, binding))
        is False
    )
    with pytest.raises(ValueError, match="plan_stale"):
        read_views.read_view(db, "audited-target", load)
    # Operational callers never reuse even a valid prior GET's audit.
    assert p.binding_valid(db, binding) is False


def test_explicit_release_selection_does_not_load_snapshot_payload(prepared):
    db, snapshot, _, _ = prepared
    db.expunge_all()
    loaded = []

    def track_load(session, instance):
        loaded.append(instance)

    event.listen(db, "loaded_as_persistent", track_load)
    try:
        assert at.selected_release(db, RELEASE) == RELEASE
        assert not loaded
        with pytest.raises(ValueError, match="unknown_release"):
            at.selected_release(db, "gen4-release-20990101")
    finally:
        event.remove(db, "loaded_as_persistent", track_load)


def test_target_without_activation_or_legacy_batch_preserves_default(db, monkeypatch):
    period = {"release": RELEASE, "binary_id": 789, "template_job_id": 456}
    snapshot = SimpleNamespace(payload={"period": period})
    monkeypatch.setattr(w, "effective_config", lambda _: {"simulation": {"priority": "HIGH"}})
    assert p.target(db, snapshot) == {
        "period": period,
        "binary_id": 789,
        "template_job_id": 456,
        "simulation": {
            "cluster": "prod_gen4",
            "max_concurrency": 1,
            "priority": "HIGH",
            "cache": "disabled",
            "dpe": True,
            "recovery_mode": "level4-independent",
        },
        "driver_revision": None,
    }


def test_timing_index_filters_other_releases_before_loading_and_keeps_ledger_checks(db):
    record = {"binding": {"release": RELEASE, "issue_id": "a"}, "trigger_events": []}
    valid = {"schema": evidence.SCHEMA, "release": RELEASE, "records": [record]}
    conflict = {**valid, "records": [{**record, "trigger_events": [{"request_timestamp": 1}]}]}
    other = {
        "schema": evidence.SCHEMA,
        "release": "gen4-release-20261023",
        "records": [{"binding": {"release": "gen4-release-20261023"}, "large": "x" * 10000}],
    }
    wrong_schema = {**valid, "schema": "unsupported"}
    for payload in (valid, conflict, other, wrong_schema):
        db.add(ReleaseWorkflowState(key="rtime:" + digest(payload)[:48], payload=payload))
    db.add(ReleaseWorkflowState(key="rtime:tampered", payload=valid))
    db.add(ReleaseWorkflowState(key="unrelated:record", payload=valid))
    db.commit()
    # Compare the result against the prior read semantics, including conflicting
    # records and malformed same-release entries.
    expected = {}
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.like("rtime:%"))
    ):
        payload = row.payload
        if (
            payload.get("release") == RELEASE
            and payload.get("schema") == evidence.SCHEMA
            and row.key == "rtime:" + digest(payload)[:48]
        ):
            for value in payload["records"]:
                expected.setdefault(digest(value["binding"]), []).append(value)
    db.expunge_all()
    loaded = []

    def track_load(session, instance):
        if isinstance(instance, ReleaseWorkflowState):
            loaded.append(instance.key)

    event.listen(db, "loaded_as_persistent", track_load)
    try:
        actual = evidence.index(db, RELEASE)
    finally:
        event.remove(db, "loaded_as_persistent", track_load)
    assert dict(actual) == expected
    assert "rtime:" + digest(other)[:48] not in loaded
    assert "unrelated:record" not in loaded
    assert "rtime:" + digest(valid)[:48] in loaded
