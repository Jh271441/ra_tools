"""Versioned AutoTriage business metrics over audited, unchanged simulation inputs.

This lane never creates scenarios, changes their platform labels, or submits jobs.
The original source snapshots, executions and publication decisions stay immutable.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import fcntl
import os
from pathlib import Path
import re

from sqlalchemy import func, select

from app.config import DATA_DIR
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch, ReleaseWorkflowState
from app.services import release_workflow as workflow
from app.services.label_recovery import INPUT_FIELDS, SCENE_FIELDS
from app.services.release_cycle import digest
from app.services.release_metrics import GOOD_RESULTS, EXCLUDED_RESULTS, ratio
from app.services.result_publication import audit_hash, publication
from app.services import auto_triage_warehouse as warehouse

BASIS = "auto_triage_sql_v2"
LABEL_FIELDS = ("ra_stuck_auto_result", "ra_result")
QUERY_FIELDS = (
    "issue_id",
    *INPUT_FIELDS,
    "issue_topic",
    "ra_merge_result",
    *LABEL_FIELDS,
    "is_deleted",
)
RAW_RESULTS = {
    0: "未填写",
    1: "成功",
    2: "失败",
    3: "限制使用",
    4: "无需协助",
    5: "误触发",
    6: "未接起",
}
KNOWN_RESULTS = GOOD_RESULTS | EXCLUDED_RESULTS | {"误触发", "正确触发"}
RELEASE = re.compile(r"gen4-release-\d{8}")
STALE_SECONDS = 30 * 60


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def business_label(value):
    """Map only the original RA enum, without rewriting model/warehouse labels."""
    if value is None or isinstance(value, str) and value in KNOWN_RESULTS:
        return value
    if type(value) is int or isinstance(value, str) and value.isdecimal():
        return RAW_RESULTS.get(int(value), str(value))
    return str(value)


def resolve_label(row):
    # A missing projection is different from an explicitly observed SQL NULL.
    if "merged_ra_auto_result" in row:
        value = row["merged_ra_auto_result"]
        if all(key in row for key in LABEL_FIELDS):
            model = row["ra_stuck_auto_result"]
            raw = str(model) if model is not None else business_label(row["ra_result"])
            if raw == value:
                return value, "model" if model is not None else "ra_result", True
        return value, "warehouse", True
    if not all(key in row for key in LABEL_FIELDS):
        return None, "missing", False
    if row["ra_stuck_auto_result"] is not None:
        return str(row["ra_stuck_auto_result"]), "model", True
    return business_label(row["ra_result"]), "ra_result", True


def cohort(ra_type, label):
    if label in GOOD_RESULTS:
        return "positive_auto" if ra_type == 2 else "positive_manual" if ra_type == 3 else None
    if ra_type == 2 and label == "误触发":
        return "negative_auto"
    if label is not None and label not in EXCLUDED_RESULTS | {"误触发"}:
        return (
            "recall_only_auto" if ra_type == 2 else "recall_only_manual" if ra_type == 3 else None
        )
    return None


def _physical(row):
    result = {key: row.get(key) for key in INPUT_FIELDS}
    for key in ("ra_type", "issue_time", "ra_start_timestamp", "trip_start_time", "trip_end_time"):
        value = result[key]
        if isinstance(value, str) and value.isdecimal():
            result[key] = int(value)
    return result


def source_identity(payload):
    return digest(
        {
            "period": {
                k: payload["period"].get(k)
                for k in ("release", "case_start", "case_end_exclusive", "binary_id")
            },
            "issues": sorted(
                (
                    {
                        "issue_id": str(i["issue_id"]),
                        **_physical(i),
                        "user_exclusion": i.get("evaluation_exclusion")
                        if (i.get("evaluation_exclusion") or {}).get("approved_by") == "user"
                        else None,
                    }
                    for i in payload["issues"]
                ),
                key=lambda i: i["issue_id"],
            ),
            "scenarios": sorted(
                (
                    {k: s.get(k) for k in ("scenario_id", *SCENE_FIELDS)}
                    for s in payload["scenarios"]
                ),
                key=lambda s: str(s["scenario_id"]),
            ),
        }
    )


def _summary(rows, label_key):
    values = [r for r in rows if not r["scope_excluded"]]
    counts = {
        "precision_auto_tp": 0,
        "precision_denominator": 0,
        "recall_auto_tp": 0,
        "recall_denominator": 0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 0,
        "road_matches": 0,
        "eligible": 0,
        "covered": 0,
        "unclassified": 0,
        "excluded": 0,
        "missing_labels": 0,
        "sim_precision_numerator": 0,
        "sim_precision_denominator": 0,
        "sim_recall_numerator": 0,
        "sim_recall_denominator": 0,
    }
    cohorts = Counter()
    for row in values:
        label, ra_type = row[label_key], row["ra_type"]
        if label_key == "auto_label" and not row["label_observed"]:
            counts["missing_labels"] += 1
            continue
        # Keep the two SQL numerators independent, including SQL NULL semantics.
        counts["precision_auto_tp"] += int(ra_type == 2 and label in GOOD_RESULTS)
        counts["precision_denominator"] += int(
            ra_type == 2 and label is not None and label not in EXCLUDED_RESULTS
        )
        counts["recall_auto_tp"] += int(
            ra_type == 2 and label is not None and label not in EXCLUDED_RESULTS | {"误触发"}
        )
        counts["recall_denominator"] += int(
            ra_type in (2, 3) and label is not None and label not in EXCLUDED_RESULTS | {"误触发"}
        )
        group = cohort(ra_type, label)
        if group is None:
            counts[
                "excluded"
                if label is None or label in EXCLUDED_RESULTS or ra_type == 3 and label == "误触发"
                else "unclassified"
            ] += 1
            continue
        counts["unclassified"] += int(label not in KNOWN_RESULTS)
        cohorts[group] += 1
        counts["eligible"] += 1
        if row["result_status"] != "reused":
            continue
        counts["covered"] += 1
        triggered = row["sim_triggered"]
        simulated = warehouse.membership("自触发" if triggered else "人工触发", label)
        for key, value in simulated.items():
            counts["sim_" + key] += value
        counts["tn"] += int(group == "negative_auto" and not triggered)
        counts["road_matches"] += int(not triggered if ra_type == 3 else triggered)
    counts.update(
        tp=counts["sim_precision_numerator"],
        fp=counts["sim_precision_denominator"] - counts["sim_precision_numerator"],
        fn=counts["sim_recall_denominator"] - counts["sim_recall_numerator"],
    )
    complete = (
        bool(counts["eligible"])
        and not counts["missing_labels"]
        and counts["covered"] == counts["eligible"]
    )
    p = ratio(counts["sim_precision_numerator"], counts["sim_precision_denominator"])
    r = ratio(counts["sim_recall_numerator"], counts["sim_recall_denominator"])
    return {
        **counts,
        "available": complete,
        "missing_results": counts["eligible"] - counts["covered"],
        "coverage": ratio(counts["covered"], counts["eligible"]),
        "cohorts": dict(cohorts),
        "online_precision": ratio(counts["precision_auto_tp"], counts["precision_denominator"])
        if not counts["missing_labels"]
        else None,
        "online_recall": ratio(counts["recall_auto_tp"], counts["recall_denominator"])
        if not counts["missing_labels"]
        else None,
        "precision": p if complete else None,
        "recall": r if complete else None,
        "covered_precision": p,
        "covered_recall": r,
        "sim_repro_rate": ratio(counts["road_matches"], counts["covered"]) if complete else None,
    }


def project(payload, labels, results, *, incompatible_scenes=()):
    """Pure issue-level projection; never reuse a previous TP/FP/FN or cohort."""
    source = {str(i["issue_id"]): i for i in payload["issues"]}
    if len(source) != len(payload["issues"]):
        raise ValueError("invalid_population")
    if set(source) != set(labels):
        raise ValueError("label_population_mismatch")
    scenes = defaultdict(list)
    scene_ids = set()
    for scene in payload["scenarios"]:
        sid, iid = str(scene["scenario_id"]), str(scene["issue_id"])
        if sid in scene_ids:
            raise ValueError("duplicate_scenario")
        scene_ids.add(sid)
        scenes[iid].append(sid)
    rows = []
    incompatible = set(incompatible_scenes)
    for iid, original in source.items():
        observed = labels[iid]
        label, origin, known = resolve_label(observed)
        physical = _physical(observed)
        ra_type = physical["ra_type"]
        if ra_type not in (2, 3):
            raise ValueError("trigger_type_changed")
        old_label = observed.get("ra_merge_result", original.get("ra_merge_result"))
        old_group, new_group = cohort(ra_type, old_label), cohort(ra_type, label)
        ids = scenes[iid]
        reason = "reused"
        if any(
            original.get(k) in (None, "") or observed.get(k) in (None, "")
            for k in ("version", "trip_id", "ra_start_timestamp")
        ):
            reason = "input_unverified"
        elif _physical(original) != physical:
            reason = "input_changed"
        elif not ids:
            reason = "missing_scenario"
        elif any(
            sid not in results or type(results[sid].get("sim_triggered")) is not bool for sid in ids
        ):
            reason = "incompatible_result" if set(ids) & incompatible else "missing_result"
        trigger = any(results[sid]["sim_triggered"] for sid in ids) if reason == "reused" else None
        scope_excluded = observed.get("is_deleted", 0) not in (0, "0", False)
        if (original.get("evaluation_exclusion") or {}).get("approved_by") == "user":
            reason, trigger = "user_exclusion", None
        simulated = (
            warehouse.membership("自触发" if trigger else "人工触发", label)
            if trigger is not None and new_group and not scope_excluded
            else None
        )
        rows.append(
            {
                "issue_id": iid,
                "issue_topic": str(original.get("issue_topic") or ""),
                "ra_type": ra_type,
                "baseline_label": old_label,
                "auto_label": label,
                "label_source": origin,
                "label_observed": known,
                "old_cohort": old_group,
                "new_cohort": new_group,
                "changed": old_label != label,
                "scope_excluded": scope_excluded,
                "scenario_ids": ids,
                "result_status": reason,
                "sim_triggered": trigger,
                "sim_memberships": simulated,
                "auto_memberships": warehouse.membership(
                    "自触发" if ra_type == 2 else "人工触发", label
                ),
                "baseline_memberships": warehouse.membership(
                    "自触发" if ra_type == 2 else "人工触发", old_label
                ),
                "raw_model_result": observed.get("ra_stuck_auto_result"),
                "precision_label": None
                if trigger is None or new_group is None or scope_excluded
                else ("FP" if trigger else "TN")
                if new_group == "negative_auto"
                else ("TP" if trigger else "FN"),
                "job_ids": sorted({results[sid]["job_id"] for sid in ids if sid in results}),
            }
        )
    baseline, auto = _summary(rows, "baseline_label"), _summary(rows, "auto_label")
    eligible = [r for r in rows if r["new_cohort"] and not r["scope_excluded"]]
    gaps = [r for r in eligible if r["result_status"] != "reused"]
    transitions = Counter(
        (r["old_cohort"] or "excluded", r["new_cohort"] or "excluded")
        for r in rows
        if not r["scope_excluded"]
    )
    return {
        "basis": BASIS,
        "aggregation": "one_issue_any_scenario_triggered",
        "source_count": len(source),
        "baseline": baseline,
        "metrics": auto,
        "rows": rows,
        "label_sources": dict(Counter(r["label_source"] for r in rows)),
        "coverage_reasons": dict(Counter(r["result_status"] for r in gaps)),
        "transitions": [
            {"before": a, "after": b, "count": n} for (a, b), n in sorted(transitions.items())
        ],
        "changed_count": sum(r["changed"] for r in rows),
        "newly_eligible": sum(
            not r["old_cohort"] and bool(r["new_cohort"]) and not r["scope_excluded"] for r in rows
        ),
        "no_longer_eligible": sum(
            bool(r["old_cohort"]) and not r["new_cohort"] and not r["scope_excluded"] for r in rows
        ),
        "scope_excluded_count": sum(r["scope_excluded"] for r in rows),
        "source_job_ids": sorted(
            {j for r in eligible if r["result_status"] == "reused" for j in r["job_ids"]}
        ),
    }


def fetch_labels(issue_ids):
    from app.services.release_source import signed_query, trail_credentials

    app_id, token = trail_credentials()
    base = os.getenv("TRAIL_ISSUE_BASE_URL", "http://10.88.128.83").rstrip("/")
    result = {}
    for offset in range(0, len(issue_ids), 200):
        ids = issue_ids[offset : offset + 200]
        rows = signed_query(
            base + "/paladin/issue/pool/query_by_issue_id_list/",
            {"source_id": 1, "issue_id_list": ids, "select_field_list": list(QUERY_FIELDS)},
            app_id,
            token,
        )
        if not isinstance(rows, dict) or set(rows) != set(ids):
            raise ValueError("label_population_mismatch")
        for iid, row in rows.items():
            if (
                not isinstance(row, dict)
                or str(row.get("issue_id")) != iid
                or not all(k in row for k in QUERY_FIELDS)
            ):
                raise ValueError("label_projection_incomplete")
            result[iid] = row
    return result


def _snapshot(db, release):
    return db.scalars(
        select(ReleaseIssueSnapshot)
        .where(ReleaseIssueSnapshot.release == release)
        .order_by(ReleaseIssueSnapshot.id.desc())
        .limit(1)
    ).first()


def _base(db, release):
    from app.services.read_views import read_memo

    def load():
        for batch in db.scalars(
            select(ReleaseSimulationBatch)
            .where(ReleaseSimulationBatch.release == release)
            .order_by(ReleaseSimulationBatch.updated_at.desc())
        ):
            if not batch.payload.get("backfill") and publication(batch):
                return batch
        return None

    return read_memo(db, ("autotriage-base", release), load)


def versions(db):
    rows = db.execute(
        select(ReleaseIssueSnapshot.release, func.max(ReleaseIssueSnapshot.id))
        .group_by(ReleaseIssueSnapshot.release)
        .order_by(ReleaseIssueSnapshot.release.desc())
    )
    result = []
    for release, sid in rows:
        snap, base = db.get(ReleaseIssueSnapshot, sid), _base(db, release)
        result.append(
            {
                "release": release,
                "snapshot_id": sid,
                "source_count": len(snap.payload["issues"]),
                "source_complete": bool(snap.payload.get("population_complete")),
                "job_id": base.payload.get("job_id") if base else None,
            }
        )
    return result


def selected_release(db, release):
    if release in ("@current", "@stable", ""):
        candidates = versions(db)
        return next(
            (r["release"] for r in candidates if r["job_id"]),
            candidates[0]["release"] if candidates else None,
        )
    if not RELEASE.fullmatch(release):
        raise ValueError("unknown_release")
    # Selection validates existence; context loads the chosen snapshot once.
    # Avoid transferring/decoding the same large JSON twice for an explicit URL.
    if (
        db.scalar(
            select(ReleaseIssueSnapshot.id).where(ReleaseIssueSnapshot.release == release).limit(1)
        )
        is None
    ):
        raise ValueError("unknown_release")
    return release


def execution_inputs(db, batch):
    """Legacy plans deliberately stored only Issue ID, trigger type and GT.

    Bind those plans to the last matching source snapshot that already existed
    when the batch was registered. A later snapshot must not rewrite its inputs.
    """
    p = batch.payload
    ids = {str(i["issue_id"]) for i in p.get("issues", [])}
    if all(all(k in i for k in INPUT_FIELDS) for i in p.get("issues", [])):
        rows = {str(i["issue_id"]): i for i in p["issues"]}
        kind, sid = "execution", None
    else:
        rows, sid = {}, None
        snapshots = db.scalars(
            select(ReleaseIssueSnapshot)
            .where(
                ReleaseIssueSnapshot.release == batch.release,
                ReleaseIssueSnapshot.created_at <= batch.created_at,
            )
            .order_by(ReleaseIssueSnapshot.created_at.desc(), ReleaseIssueSnapshot.id.desc())
            .execution_options(yield_per=1)
        )
        try:
            for snapshot in snapshots:
                if workflow.population_identity(snapshot.payload) != p.get("population_hash"):
                    continue
                candidate = {
                    str(i["issue_id"]): i
                    for i in snapshot.payload["issues"]
                    if str(i["issue_id"]) in ids
                }
                if set(candidate) == ids and all(
                    all(k in i for k in INPUT_FIELDS) for i in candidate.values()
                ):
                    rows, sid = candidate, snapshot.id
                    break
        finally:
            snapshots.close()
        kind = "source_snapshot"
    if not rows:
        return {}, {"kind": "unverified", "snapshot_id": None, "input_hash": None}
    return rows, {
        "kind": kind,
        "snapshot_id": sid,
        "input_hash": digest(
            sorted(
                ({"issue_id": iid, **_physical(row)} for iid, row in rows.items()),
                key=lambda r: r["issue_id"],
            )
        ),
    }


def reusable_results(db, base, payload):
    """Use the approved primary and its audited recovery children, never reruns."""
    if base is None:
        return {}, {}, [], set()
    requested_binary = payload.get("period", {}).get("binary_id")
    if requested_binary is not None and str(requested_binary) != str(base.payload.get("binary_id")):
        return (
            {},
            {},
            [{"job_id": base.payload.get("job_id"), "reason": "binary_changed"}],
            {str(s["scenario_id"]) for s in payload["scenarios"]},
        )
    expected = {str(s["scenario_id"]): s for s in payload["scenarios"]}
    originals = {str(i["issue_id"]): i for i in payload["issues"]}
    cached = workflow.get_state(db, "label_runtime:" + base.fingerprint[:48])
    expected_contract = base.payload.get("result_import", {}).get("execution_contract_hash")
    if not expected_contract and cached.get("base_audit_hash") == audit_hash(base.payload):
        expected_contract = cached.get("execution_contract_hash")
    candidates = [
        base,
        *[
            b
            for b in db.scalars(
                select(ReleaseSimulationBatch)
                .where(ReleaseSimulationBatch.release == base.release)
                .order_by(ReleaseSimulationBatch.created_at)
            )
            if b.payload.get("backfill", {}).get("base_fingerprint") == base.fingerprint
        ],
    ]
    results, lineage, warnings, incompatible = {}, {}, [], set()
    for batch in candidates:
        p = batch.payload
        if not p.get("result_import", {}).get("primary"):
            continue
        trusted = batch is base or (
            expected_contract
            and p["result_import"].get("execution_contract_hash") == expected_contract
        )
        trusted = trusted and all(
            p.get(k) == base.payload.get(k) for k in ("binary_id", "simulation", "driver_revision")
        )
        if not trusted:
            incompatible.update(str(s["scenario_id"]) for s in p.get("scenarios", []))
            warnings.append({"job_id": p.get("job_id"), "reason": "execution_contract_changed"})
            continue
        inputs, source_binding = execution_inputs(db, batch)
        fingerprint = audit_hash(p)
        for scene in p.get("scenarios", []):
            sid, iid = str(scene["scenario_id"]), str(scene["issue_id"])
            if sid not in expected or iid not in originals:
                continue
            if (
                any(scene.get(k) != expected[sid].get(k) for k in SCENE_FIELDS)
                or iid not in inputs
                or _physical(inputs[iid]) != _physical(originals[iid])
            ):
                incompatible.add(sid)
                continue
            row = p.get("results", {}).get(sid)
            detail = p.get("scenario_results", {}).get(sid, {})
            if (
                sid in results
                or not row
                or type(row.get("sim_triggered")) is not bool
                or detail.get("status") != "result_ready"
                or detail.get("errors")
            ):
                continue
            results[sid] = {"sim_triggered": row["sim_triggered"], "job_id": p["job_id"]}
            lineage[sid] = {
                "fingerprint": batch.fingerprint,
                "audit_hash": fingerprint,
                "job_id": p["job_id"],
                "source_binding": source_binding,
            }
    return results, lineage, warnings, incompatible


def view_context(db, release, date_start=None, date_end=None):
    release = selected_release(db, release)
    snapshot = _snapshot(db, release)
    if snapshot is None:
        raise ValueError("source_missing")
    scope = warehouse.scope_for(snapshot.payload["period"], date_start, date_end)
    suffix = release + ":" + digest({"basis": BASIS, "scope": scope})[:16]
    return release, snapshot, scope, "at_view:" + suffix, "at_refresh:" + suffix


def dashboard_population(snapshot, dashboard, physical):
    warehouse.validate_receipt(dashboard)
    rows = {r["issue_id"]: r for r in dashboard["rows"]}
    if set(rows) != set(physical):
        raise ValueError("label_population_mismatch")
    original = {str(r["issue_id"]): r for r in snapshot.payload["issues"]}
    payload = deepcopy(snapshot.payload)
    scope = dashboard["scope"]
    payload["period"].update(
        case_start=scope["date_start"] + "T00:00:00+08:00",
        case_end_exclusive=(date.fromisoformat(scope["date_end"]) + timedelta(days=1)).isoformat()
        + "T00:00:00+08:00",
    )
    payload["issues"] = [deepcopy(original.get(iid, physical[iid])) for iid in sorted(rows)]
    payload["scenarios"] = [s for s in payload["scenarios"] if str(s["issue_id"]) in rows]
    payload["population_complete"] = True
    payload.pop("mapping_error", None)
    labels = {}
    for iid, row in rows.items():
        observed = deepcopy(physical[iid])
        if not all(k in observed for k in QUERY_FIELDS):
            raise ValueError("label_projection_incomplete")
        trigger = 2 if row["ra_trigger_type"] == "自触发" else 3
        if _physical(observed)["ra_type"] != trigger:
            raise ValueError("dashboard_trigger_type_changed")
        observed.update(
            merged_ra_auto_result=row["merged_ra_auto_result"],
            ra_merge_result=row["merged_ra_result"]
            if dashboard.get("baseline_available", True)
            else None,
            is_deleted=row["is_deleted"],
        )
        labels[iid] = observed
    return payload, labels


def verify_dashboard_projection(projected, dashboard):
    actual_rows = {r["issue_id"]: r for r in projected["rows"]}
    for row in dashboard["rows"]:
        actual = actual_rows[row["issue_id"]]
        for prefix, key in (("auto", "auto_memberships"), ("baseline", "baseline_memberships")):
            if any(actual[key][name] != row[prefix + "_" + name] for name in actual[key]):
                raise ValueError("dashboard_membership_mismatch")
    fields = {
        "precision_auto_tp": "precision_numerator",
        "precision_denominator": "precision_denominator",
        "recall_auto_tp": "recall_numerator",
        "recall_denominator": "recall_denominator",
    }
    for prefix, key in (("auto", "metrics"), ("baseline", "baseline")):
        if any(
            projected[key][name] != dashboard["counts"][prefix + "_" + alias]
            for name, alias in fields.items()
        ):
            raise ValueError("dashboard_count_mismatch")


def recalculate(
    db,
    release,
    *,
    refresh_labels=None,
    fetcher=None,
    warehouse_fetcher=None,
    date_start=None,
    date_end=None,
    observed=None,
    observed_at=None,
):
    if observed is not None:
        raise ValueError("dashboard_receipt_required")
    # Explicit injected acquisition is retained for offline reconciliation tools.
    # The browser endpoint rejects refresh_labels=True before it is queued.
    if refresh_labels is None:
        refresh_labels = fetcher is not None or warehouse_fetcher is not None
    if refresh_labels and fetcher is None:
        raise ValueError("offline_sample_update_required")
    release, snapshot, scope, view_key, _ = view_context(db, release, date_start, date_end)
    inventory_identity = source_identity(snapshot.payload)
    pointer = workflow.get_state(db, view_key)
    prior = workflow.get_state(db, pointer.get("label_key", "at_labels:none"))
    from app.services import evaluation_samples

    if refresh_labels:
        dashboard = (warehouse_fetcher or warehouse.fetch)(scope)
        if dashboard["scope"] != scope:
            raise ValueError("dashboard_scope_mismatch")
        ids = sorted(r["issue_id"] for r in dashboard["rows"])
        physical = (fetcher or fetch_labels)(ids) if ids else {}
        payload, labels = dashboard_population(snapshot, dashboard, physical)
        checked_at = dashboard["observed_at"]
    elif evaluation_samples.status(db, scope)["status"] == "ready":
        dashboard, physical = evaluation_samples.read(db, scope)
        payload, labels = dashboard_population(snapshot, dashboard, physical)
        checked_at = dashboard["observed_at"]
    elif prior.get("inventory_identity") == inventory_identity and prior.get("basis") == BASIS:
        labels = prior["rows"]
        payload = workflow.get_state(db, prior["population_key"])["payload"]
        dashboard = prior["dashboard"]
        checked_at = pointer["label_checked_at"]
    else:
        dashboard, physical = evaluation_samples.read(db, scope)
        payload, labels = dashboard_population(snapshot, dashboard, physical)
        checked_at = dashboard["observed_at"]
    if not all(resolve_label(row)[2] for row in labels.values()):
        raise ValueError("label_projection_incomplete")
    source_hash = source_identity(payload)
    population_key = (
        "at_population:" + digest({"basis": BASIS, "payload": payload, "scope": scope})[:48]
    )
    base = _base(db, release)
    results, lineage, warnings, incompatible = reusable_results(db, base, payload)
    projected = project(payload, labels, results, incompatible_scenes=incompatible)
    verify_dashboard_projection(projected, dashboard)
    source_complete = bool(payload.get("population_complete")) and not payload.get("mapping_error")
    if not source_complete:
        projected["metrics"].update(
            available=False, precision=None, recall=None, sim_repro_rate=None
        )
    # Store query metadata once; duplicated row fields are already in the label receipt.
    label_receipt = {
        "basis": BASIS,
        "source_identity": source_hash,
        "rows": labels,
        "dashboard": dashboard,
        "inventory_identity": inventory_identity,
        "population_key": population_key,
    }
    label_hash = digest(label_receipt)
    label_key = "at_labels:" + label_hash[:48]
    revision_core = {
        "basis": BASIS,
        "source_identity": source_hash,
        "label_hash": label_hash,
        "lineage": lineage,
        "base_fingerprint": base.fingerprint if base else None,
        "base_audit_hash": audit_hash(base.payload) if base else None,
        "source_complete": source_complete,
        "inventory_identity": inventory_identity,
        "scope": scope,
        "population_key": population_key,
    }
    revision_key = "at_revision:" + digest(revision_core)[:48]
    applied = now_iso()
    receipt = {
        **revision_core,
        **projected,
        "revision_key": revision_key,
        "label_key": label_key,
        "release": release,
        "source_snapshot_id": snapshot.id,
        "source_as_of": snapshot.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "source_complete": source_complete,
        "label_synced_at": applied,
        "generated_at": applied,
        "base_job_id": base.payload.get("job_id") if base else None,
        "binary_id": payload["period"].get("binary_id")
        or (base.payload.get("binary_id") if base else None),
        "warnings": warnings,
        "simulation_submitted": False,
        "reconciliation": {
            "status": "matched",
            "checked_issues": len(dashboard["rows"]),
            "counts": dashboard["counts"],
            "dashboard_only_ids": sorted(
                set(labels) - {str(r["issue_id"]) for r in snapshot.payload["issues"]}
            ),
            "inventory_only_ids": sorted(
                {str(r["issue_id"]) for r in snapshot.payload["issues"]} - set(labels)
            ),
            "references": dashboard.get("references", []),
            "report_id": warehouse.REPORT_ID,
            "slice_id": warehouse.SLICE_ID,
        },
    }
    # A source/binary/result change during the upstream read invalidates this attempt.
    db.expire_all()
    latest = _snapshot(db, release)
    if latest is None or source_identity(latest.payload) != inventory_identity:
        raise ValueError("source_changed")
    if base:
        db.refresh(base)
        if audit_hash(base.payload) != revision_core["base_audit_hash"] or not publication(base):
            raise ValueError("execution_changed")
    for key, value in (
        (population_key, {"payload": payload}),
        (label_key, label_receipt),
        (revision_key, receipt),
    ):
        if db.get(ReleaseWorkflowState, key) is None:
            db.add(ReleaseWorkflowState(key=key, payload=value))
    state = db.get(ReleaseWorkflowState, view_key) or ReleaseWorkflowState(key=view_key)
    state.payload = {
        "revision_key": revision_key,
        "label_key": label_key,
        "updated_at": applied,
        "label_checked_at": checked_at,
        "scope": scope,
    }
    db.add(state)
    db.commit()
    return workflow.get_state(db, revision_key)


def report(db, release="@current", date_start=None, date_end=None):
    release = selected_release(db, release)
    if not release:
        return {"release": None, "status": "source_missing", "refresh": {}, "result": None}
    release, snapshot, scope, view_key, refresh_key = view_context(
        db, release, date_start, date_end
    )
    pointer = workflow.get_state(db, view_key)
    value = workflow.get_state(db, pointer.get("revision_key", "at_revision:none"))
    status = "dashboard_required"
    if value:
        status = "complete" if value["metrics"]["available"] else "needs_simulation"
        if not value["metrics"]["eligible"]:
            status = "no_eligible_cases"
        if value["metrics"]["missing_labels"]:
            status = "labels_required"
        if value["inventory_identity"] != source_identity(snapshot.payload):
            status = "source_changed"
        bindings = {v["fingerprint"]: v for v in value.get("lineage", {}).values()}
        for fingerprint, item in bindings.items():
            batch = db.get(ReleaseSimulationBatch, fingerprint)
            if (
                batch is None
                or audit_hash(batch.payload) != item["audit_hash"]
                or execution_inputs(db, batch)[1] != item.get("source_binding")
            ):
                status = "execution_changed"
                break
        base = (
            db.get(ReleaseSimulationBatch, value["base_fingerprint"])
            if value.get("base_fingerprint")
            else None
        )
        if base is None:
            status = "execution_missing"
        elif audit_hash(base.payload) != value["base_audit_hash"] or not publication(base):
            status = "execution_changed"
        if not value["source_complete"]:
            status = "source_incomplete"
    invalid = (
        status in ("source_changed", "execution_changed", "source_incomplete")
        or status == "execution_missing"
        and bool(value.get("base_fingerprint"))
    )
    refresh = dict(workflow.get_state(db, refresh_key))
    if refresh.get("status") in ("queued", "running"):
        try:
            if (
                datetime.now(timezone.utc) - datetime.fromisoformat(refresh["requested_at"])
            ).total_seconds() >= STALE_SECONDS:
                refresh.update(status="failed", error="refresh_interrupted")
        except (KeyError, ValueError, TypeError):
            refresh.update(status="failed", error="refresh_interrupted")
    return {
        "release": release,
        "status": status,
        "scope": scope,
        "source_count": len(snapshot.payload["issues"]),
        "source_snapshot_id": snapshot.id,
        "refresh": refresh,
        "result": {k: v for k, v in value.items() if k not in ("rows", "lineage")}
        if value and not invalid
        else None,
        "previous_generated_at": value.get("generated_at"),
        "label_checked_at": pointer.get("label_checked_at"),
    }


def issue_page(
    db,
    release="@current",
    page=1,
    page_size=20,
    query="",
    coverage="",
    changed_only=False,
    date_start=None,
    date_end=None,
):
    if page < 1 or page_size not in (10, 20, 25, 50, 100, 200):
        raise ValueError("invalid_pagination")
    value = report(db, release, date_start, date_end)
    if not value["result"]:
        return {**value, "items": [], "total": 0, "page": page, "page_size": page_size, "pages": 0}
    rows = workflow.get_state(db, value["result"]["revision_key"])["rows"]
    needle = query.casefold().strip()
    rows = [
        r
        for r in rows
        if (
            not needle
            or needle in r["issue_id"].casefold()
            or needle in str(r.get("issue_topic") or "").casefold()
        )
        and (not changed_only or r["changed"])
        and (
            not coverage
            or (
                coverage == "gap"
                and bool(r["new_cohort"])
                and not r["scope_excluded"]
                and r["result_status"] != "reused"
            )
            or (
                coverage == "reused"
                and bool(r["new_cohort"])
                and not r["scope_excluded"]
                and r["result_status"] == "reused"
            )
        )
    ]
    total = len(rows)
    return {
        "release": value["release"],
        "revision_key": value["result"]["revision_key"],
        "items": rows[(page - 1) * page_size : page * page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def gap_plan(db, release="@current", date_start=None, date_end=None):
    value = report(db, release, date_start, date_end)
    if not value["result"]:
        raise ValueError(value["status"])
    result = workflow.get_state(db, value["result"]["revision_key"])
    gaps = [
        r
        for r in result["rows"]
        if r["new_cohort"] and not r["scope_excluded"] and r["result_status"] != "reused"
    ]
    payload = workflow.get_state(db, result["population_key"])["payload"]
    sources = {str(row["issue_id"]): row for row in payload["issues"]}
    labels = workflow.get_state(db, result["label_key"])["rows"]
    scenes = {str(row["scenario_id"]): row for row in payload["scenarios"]}
    planned = [
        {
            **row,
            "source_inputs": _physical(sources[row["issue_id"]]),
            "observed_inputs": _physical(labels[row["issue_id"]]),
            "evaluation_exclusion": sources[row["issue_id"]].get("evaluation_exclusion"),
            "scenarios": [scenes[sid] for sid in row["scenario_ids"]],
        }
        for row in gaps
    ]
    return {
        "schema_version": "auto_triage_gap_plan_v1",
        "release": value["release"],
        "basis": BASIS,
        "source_identity": result["source_identity"],
        "revision_key": result["revision_key"],
        "source_snapshot_id": result["source_snapshot_id"],
        "label_key": result["label_key"],
        "label_checked_at": value["label_checked_at"],
        "period": payload["period"],
        "scope": result["scope"],
        "reconciliation": result["reconciliation"],
        "binary_id": result["binary_id"],
        "base_job_id": result["base_job_id"],
        "source_job_ids": result["source_job_ids"],
        "reuse_count": result["metrics"]["covered"],
        "gap_count": len(gaps),
        "issues": planned,
        "can_reuse_all": result["metrics"]["available"],
        "requires_label_verification": bool(result["metrics"]["missing_labels"]),
        "requires_user_review": any(r["result_status"] == "user_exclusion" for r in gaps),
        "requires_source_refresh": any(
            r["result_status"] in ("input_changed", "input_unverified") for r in gaps
        ),
        "simulation_submitted": False,
        "requires_execution_preflight": True,
    }


def queue_refresh(db, release, refresh_labels=False, date_start=None, date_end=None):
    if refresh_labels:
        raise ValueError("offline_sample_update_required")
    release, _, scope, _, refresh_key = view_context(db, release, date_start, date_end)
    previous = workflow.get_state(db, refresh_key)
    if previous.get("status") in ("queued", "running") and previous.get("requested_at"):
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(previous["requested_at"])
        ).total_seconds()
        if age < STALE_SECONDS:
            return {"release": release, **previous}
    requested_at = now_iso()
    state = {
        "status": "queued",
        "requested_at": requested_at,
        "refresh_labels": refresh_labels,
        "request_id": digest({"scope": scope, "requested_at": requested_at})[:20],
        "scope": scope,
    }
    workflow.put_state(db, refresh_key, state)
    return {"release": release, **state}


def _lock_path(release, scope):
    lock = Path(
        os.getenv("RELEASE_WORKFLOW_LOCK", str(DATA_DIR / "release-workflow.lock"))
    ).with_name("auto-triage-metrics-" + release + "-" + digest(scope)[:16] + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    return lock


def process_refresh(release, date_start=None, date_end=None):
    from app.database import SessionLocal

    if not RELEASE.fullmatch(release):
        raise ValueError("unknown_release")
    with SessionLocal() as db:
        _, _, scope, _, refresh_key = view_context(db, release, date_start, date_end)
    with _lock_path(release, scope).open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        while True:
            with SessionLocal() as db:
                state = workflow.get_state(db, refresh_key)
                if state.get("status") != "queued":
                    return
                workflow.put_state(db, refresh_key, {**state, "status": "running"})
                try:
                    value = recalculate(
                        db,
                        release,
                        refresh_labels=state.get("refresh_labels", False),
                        date_start=scope["date_start"],
                        date_end=scope["date_end"],
                    )
                    outcome = {"status": "complete", "revision_key": value["revision_key"]}
                except Exception as exc:
                    db.rollback()
                    outcome = {
                        "status": "failed",
                        "error": str(exc) if isinstance(exc, ValueError) else "upstream_error",
                    }
                db.expire_all()
                current = workflow.get_state(db, refresh_key)
                if current.get("request_id") != state.get("request_id"):
                    continue
                workflow.put_state(db, refresh_key, {**state, **outcome, "finished_at": now_iso()})
                return


def refresh_observed(db, release):
    """Merge new execution receipts without replacing dashboard labels by Trail."""
    pointers = list(
        db.scalars(
            select(ReleaseWorkflowState).where(
                ReleaseWorkflowState.key.startswith("at_view:" + release + ":")
            )
        )
    )
    for pointer in pointers:
        scope = pointer.payload.get("scope")
        if not scope:
            continue
        with _lock_path(release, scope).open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            try:
                recalculate(
                    db,
                    release,
                    refresh_labels=False,
                    date_start=scope["date_start"],
                    date_end=scope["date_end"],
                )
            except ValueError:
                db.rollback()
