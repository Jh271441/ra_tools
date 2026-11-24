"""Ordinary Shuyi metrics over an independently frozen population and shared physics.

The original native batches, the active AutoTriage profile and Trail sample index
stay unchanged. Offline publication is explicit; page reads never query upstream.
"""

from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select
from app.models import ReleaseWorkflowState
from app.services import evaluation_pipeline as p, release_workflow as w
from app.services import (
    auto_triage_metrics as at,
    auto_triage_warehouse as warehouse,
    metric_profiles as profiles,
)
from app.services.release_cycle import digest

BASIS = "ordinary_shuyi_report_v1"
POINTER = "normalmetrics:"
REVISION = "normalrevision:"


def audit(value):
    return digest(
        {
            k: value[k]
            for k in (
                "basis",
                "context",
                "source",
                "payload",
                "specification",
                "target_binding",
                "lineage",
                "rows",
                "metrics",
            )
        }
    )


def calculate(db, dashboard, physical, definition):
    warehouse.validate_receipt(dashboard)
    if (
        dashboard.get("schema_version") != 2
        or dashboard.get("baseline_available") is False
        or definition.get("normal_report_field") != "merged_ra_result"
        or definition.get("normal_column_code") != warehouse.FIELDS["merged_ra_result"][0]
        or definition.get("report_id") != warehouse.REPORT_ID
    ):
        raise ValueError("ordinary_source_unverified")
    release = dashboard["scope"]["release"]
    snapshot = at._snapshot(db, release)
    if snapshot is None or not p.target_identity(db, release):
        raise ValueError("ordinary_execution_unverified")
    dashboard = deepcopy(dashboard)
    dashboard.pop("sample_snapshot_id", None)
    dashboard["sample_snapshot_id"] = digest({"dashboard": dashboard, "physical": physical})
    payload, labels, changed = p.physical_payload(snapshot, dashboard, physical)
    specification = p.target(db, snapshot)
    ctx = {**dashboard["scope"], "profile_id": BASIS}
    deferred, _ = p.prepared_inputs(db, ctx, dashboard, payload, specification)
    p.activated_scene_inputs(db, release, payload, specification)
    results, lineage, warnings, incompatible = p.reuse(db, snapshot, payload, specification)
    projected = at.project(payload, labels, results, incompatible_scenes=incompatible)
    for row in projected["rows"]:
        # Use this report's ordinary column directly. Never reuse an AutoTriage
        # cohort, TP/FP/FN, membership or label from the physical task.
        flags = profiles.membership(profiles.DEFAULT_CONFIG, row["ra_type"], row["baseline_label"])
        row["eligible"] = bool(flags["precision_denominator"] or flags["recall_denominator"])
        row["ordinary_memberships"] = flags
        row["ordinary_sim_memberships"] = (
            profiles.membership(
                profiles.DEFAULT_CONFIG, 2 if row["sim_triggered"] else 3, row["baseline_label"]
            )
            if row["result_status"] == "reused"
            else None
        )
        if row["issue_id"] in changed and row["result_status"] == "missing_scenario":
            row["result_status"] = "input_changed"
        if row["issue_id"] in deferred and not row["scenario_ids"]:
            row["result_status"] = deferred[row["issue_id"]]
    metrics = p.summarize(projected["rows"], profiles.DEFAULT_CONFIG, "baseline_label")
    expected = {k: dashboard["counts"]["baseline_" + k] for k in metrics["counts"]}
    if metrics["counts"] != expected:
        raise ValueError("ordinary_count_mismatch")
    value = {
        "basis": BASIS,
        "context": ctx,
        "source": {
            "dashboard": dashboard,
            "labels": deepcopy(physical),
            "definition": deepcopy(definition),
        },
        "payload": payload,
        "specification": specification,
        "target_binding": p.target_identity(db, release),
        "lineage": lineage,
        "rows": projected["rows"],
        "metrics": metrics,
        "source_count": len(dashboard["rows"]),
        "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    value["audit_hash"] = audit(value)
    value["revision_key"] = REVISION + value["audit_hash"][:48]
    return value


def publish(db, value):
    if value.get("audit_hash") != audit(value):
        raise ValueError("ordinary_revision_changed")
    key = value["revision_key"]
    existing = w.get_state(db, key)
    if existing and existing["audit_hash"] != value["audit_hash"]:
        raise ValueError("ordinary_revision_changed")
    if not existing:
        w.put_state(db, key, value)
    w.put_state(
        db,
        POINTER + value["context"]["release"],
        {
            "release": value["context"]["release"],
            "revision_key": key,
            "audit_hash": value["audit_hash"],
            "published_at": value["generated_at"],
        },
    )


def read(db, release):
    pointer = w.get_state(db, POINTER + str(release))
    if not pointer:
        return None
    value = w.get_state(db, pointer.get("revision_key", "normalrevision:none"))
    if (
        not value
        or value.get("audit_hash") != pointer.get("audit_hash")
        or value["audit_hash"] != audit(value)
        or value["context"]["release"] != release
        or value["target_binding"] != p.target_identity(db, release)
        or not p.same_runtime(value["specification"], p.target(db, at._snapshot(db, release)))
    ):
        raise ValueError("ordinary_revision_changed")
    seen = set()
    for binding in value["lineage"].values():
        key = (binding["execution_id"], binding["audit_hash"])
        if key not in seen and not p.binding_valid(db, binding):
            raise ValueError("ordinary_execution_changed")
        seen.add(key)
    return value


def kpi(value):
    m, release = value["metrics"], value["context"]["release"]
    source, sim, paired = m["counts"], m["sim_counts"], m["covered_source_counts"]
    ratio = lambda a, b: a / b if b else None
    scope = {
        "complete": m["available"],
        "covered": m["covered"],
        "eligible": m["eligible"],
        "precision": m["covered_precision"],
        "recall": m["covered_recall"],
        "repro_rate": m["covered_repro_rate"],
        "road_precision": ratio(paired["precision_numerator"], paired["precision_denominator"]),
        "road_recall": ratio(paired["recall_numerator"], paired["recall_denominator"]),
        "road_counts": paired,
        "sim_counts": sim,
    }
    lineage_jobs = {b["job_id"] for b in value["lineage"].values()}
    return {
        "version_key": release,
        "label": "release" + release[-8:],
        "total_cases": value["source_count"],
        "road_positive_cases": m["eligible"],
        "road_behavior_cases": m["eligible"],
        "sim_positive_cases": sim["precision_denominator"],
        "reproduced_cases": m["road_matches"],
        "sim_repro_rate": m["sim_repro_rate"],
        "precision": m["precision"],
        "recall": m["recall"],
        "evaluation_scope": scope,
        "f1": None,
        "specificity": None,
        "accuracy": None,
        "model_repro_rate": 0,
        "fn_fallback_rate": 0,
        "fp_suppress_rate": 0,
        "positive_auto_repro_rate": None,
        "negative_auto_repro_rate": None,
        "positive_manual_repro_rate": None,
        "evaluated_cases": m["covered"],
        "dpe_coverage": m["coverage"],
        "quality_gate_passed": m["available"],
        "root_causes": {},
        "source_gt": {
            "data_source": "shuyi_current_report",
            "total_scenarios": m["eligible"],
            "online_precision": m["online_precision"],
            "online_recall": m["online_recall"],
            "auto_trigger_tp": source["precision_numerator"],
            "auto_trigger_fp": source["precision_denominator"] - source["precision_numerator"],
            "manual_trigger_fn": source["recall_denominator"] - source["recall_numerator"],
            **source,
        },
        "sim_estimate": {
            "data_source": "shared_execution",
            "job_id": next(iter(lineage_jobs)) if len(lineage_jobs) == 1 else None,
            "estimated_tp": sim["precision_numerator"],
            "estimated_fp": sim["precision_denominator"] - sim["precision_numerator"],
            "estimated_fn": sim["recall_denominator"] - sim["recall_numerator"],
            "terminal_failed": m["missing_results"],
            "normal_revision_key": value["revision_key"],
            "aggregation": "one_issue_any_scenario_triggered",
            "same_version_projection": {
                "available": m["available"],
                "population_coverage": m["coverage"],
                "sim_precision": m["precision"],
                "sim_business_recall": m["recall"],
                "reason": "" if m["available"] else "coverage_pending",
            },
        },
    }


def history_kpis(db):
    releases = [
        r.payload["release"]
        for r in db.scalars(
            select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith(POINTER))
        )
    ]
    return [kpi(read(db, release)) for release in releases]


def issue_page(db, release, page, page_size, query, label):
    value = read(db, release)
    if value is None:
        return None
    originals = {str(i["issue_id"]): i for i in value["payload"]["issues"]}
    scenes = {str(s["scenario_id"]): s for s in value["payload"]["scenarios"]}
    rows = []
    for row in value["rows"]:
        original = originals[row["issue_id"]]
        scene = scenes.get(row["scenario_ids"][0], {}) if row["scenario_ids"] else {}
        source_label, trigger = row["baseline_label"], row["sim_triggered"]
        positive = source_label is not None and source_label not in set(profiles.EXCLUDED) | {
            "误触发"
        }
        sim_class = (
            None
            if trigger is None or not row["eligible"]
            else ("TP" if trigger else "FN")
            if positive
            else ("FP" if trigger else "TN")
        )
        jobs = {
            value["lineage"][sid]["job_id"]
            for sid in row["scenario_ids"]
            if sid in value["lineage"]
        }
        item = {
            "issue_id": row["issue_id"],
            "issue_topic": row["issue_topic"],
            "version_key": release,
            "road_version": original.get("version", ""),
            "ra_type": row["ra_type"],
            "issue_time": original.get("issue_time"),
            "source_result": source_label,
            "scenario_id": str(scene.get("scenario_id", "")),
            "scenario_name": scene.get("scenario_name", scene.get("name", "")),
            "scenario_labels": scene.get("scenario_labels", scene.get("labels", [])),
            "simulation_status": "result_ready"
            if row["result_status"] == "reused"
            else row["result_status"],
            "sim_triggered": trigger,
            "precision_label": sim_class,
            "reproduced": trigger == (row["ra_type"] == 2) if trigger is not None else None,
            "job_id": next(iter(jobs)) if len(jobs) == 1 else None,
            "result_note": "",
            "execution_conflict": False,
        }
        if (not label or label in item["scenario_labels"]) and (
            not query or query.casefold() in str(item).casefold()
        ):
            rows.append(item)
    rows.sort(key=lambda r: (r.get("issue_time") or 0, r["issue_id"]), reverse=True)
    return {
        "items": rows[(page - 1) * page_size : page * page_size],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "status": "published",
        "basis": BASIS,
        "revision_key": value["revision_key"],
    }
