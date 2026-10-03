"""Import completed executions of one evaluation without double-counting scenes."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from sqlalchemy import select
from app.models import ReleaseSimulationBatch, ReleaseWorkflowState
from app.services.release_cycle import digest
from app.services.release_metrics import summarize_population

TRIGGER = "dpe_assist_channel_triggered__group1"


def checks(row):
    errors = []
    if row.get("task_status") != 3 or not str(row.get("task_outcome", "")).startswith(
        "Done"
    ):
        errors.append("task_failed")
    if row.get("simulator_cache_hit") is not False:
        errors.append("cache_unverified")
    for key in ("inference_log_count", "dpe_output_count", "output_bag_count"):
        if not isinstance(row.get(key), (int, float)) or row[key] <= 0:
            errors.append(key)
    for key in ("failed_evaluation_count", "unexpected_warning_count"):
        if row.get(key) != 0:
            errors.append(key)
    value = row.get(TRIGGER)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < -1
    ):
        errors.append("dpe_missing")
    return errors


def integrate(plan, exports, primary_job_id):
    expected = {str(s["scenario_id"]): s for s in plan["scenarios"]}
    if len(expected) != len(plan["scenarios"]) or not expected:
        raise ValueError("Scenario population is empty or duplicated")
    indexes = {}
    for export in exports:
        jid = int(export["job_id"])
        progress = export["progress"]
        rows = {str(r["scenario_id"]): r for r in export["rows"]}
        if (
            jid in indexes
            or len(rows) != len(export["rows"])
            or set(rows) != set(expected)
        ):
            raise ValueError("Execution scenario population mismatch")
        if any(
            export.get(k) != plan.get(k)
            for k in ("release", "binary_id", "population_hash")
        ):
            raise ValueError("Execution release, binary or population mismatch")
        if (
            progress.get("job_id") != jid
            or progress.get("state") != "COMPLETED"
            or progress.get("total") != len(expected)
        ):
            raise ValueError("Execution is not terminal and complete")
        counts = {3: 0, 4: 0, 5: 0}
        for sid, row in rows.items():
            if (
                row.get("issue_id") != expected[sid]["issue_id"]
                or row.get("cohort") != expected[sid]["cohort"]
            ):
                raise ValueError("Execution source cohort mismatch")
            if row.get("task_status") not in counts or not row.get("argument_hash"):
                raise ValueError("Task audit missing or not terminal")
            counts[row["task_status"]] += 1
        if [counts[3], counts[4], counts[5]] != [
            progress["completed"],
            progress["failed"],
            progress["cancelled"],
        ]:
            raise ValueError("Task counts differ from execution receipt")
        indexes[jid] = rows
    if primary_job_id not in indexes:
        raise ValueError("Primary execution missing")
    primary = indexes[primary_job_id]
    for other in indexes.values():
        if any(
            other[sid]["argument_hash"] != primary[sid]["argument_hash"]
            for sid in expected
        ):
            raise ValueError("Actual execution parameters differ")
    conflicts = []
    comparable = 0
    if len(indexes) > 1:
        for sid in expected:
            values = [
                r[sid][TRIGGER] >= 1 for r in indexes.values() if not checks(r[sid])
            ]
            if len(values) == len(indexes):
                comparable += 1
                if len(set(values)) > 1:
                    conflicts.append(sid)
    task_id = digest(
        {
            "release": plan["release"],
            "binary_id": plan["binary_id"],
            "population_hash": plan["population_hash"],
            "scenario_ids": sorted(expected),
            "driver_revision": plan.get("driver_revision"),
            "simulation": {
                k: v
                for k, v in plan["simulation"].items()
                if k not in ("priority", "max_concurrency")
            },
        }
    )
    details = {}
    valid = {}
    for sid, row in primary.items():
        errors = checks(row)
        details[sid] = {
            "task_id": str(row["task_id"]),
            "status": "result_ready"
            if not errors
            else "failed"
            if row["task_status"] != 3
            else "quality_failed",
            "errors": errors,
            "outcome": row.get("task_outcome", ""),
            "outcome_detail": str(row.get("task_outcome_detail") or "")[:5000],
            "job_id": primary_job_id,
            "conflict": sid in conflicts,
        }
        if errors:
            continue
        triggered = row[TRIGGER] >= 1
        cohort = expected[sid]["cohort"]
        label = (
            ("FP" if triggered else "TN")
            if cohort == "negative_auto"
            else ("TP" if triggered else "FN")
        )
        valid[sid] = {
            "sim_triggered": triggered,
            "reproduced": not triggered if cohort == "positive_manual" else triggered,
            "precision_label": label,
            "cohort": cohort,
            "issue_id": expected[sid]["issue_id"],
        }
    full = summarize_population(plan["issues"], plan["scenarios"], valid)
    valid_issues = {str(expected[sid]["issue_id"]) for sid in valid}
    # Exclude an entire issue if one of its associated scenarios is missing.
    invalid_issues = {
        str(expected[sid]["issue_id"]) for sid in expected if sid not in valid
    }
    valid_issues -= invalid_issues
    subset = summarize_population(
        [i for i in plan["issues"] if str(i["issue_id"]) in valid_issues],
        [s for s in plan["scenarios"] if str(s["issue_id"]) in valid_issues],
        valid,
    )
    passed = (
        full["available"]
        and not conflicts
        and all(not checks(r) for r in primary.values())
    )
    return {
        "schema_version": 1,
        "task_key": task_id,
        "release": plan["release"],
        "binary_id": plan["binary_id"],
        "population_hash": plan["population_hash"],
        "primary_job_id": primary_job_id,
        "job_ids": sorted(indexes),
        "scenario_count": len(expected),
        "valid_scenario_count": len(valid),
        "missing_scenario_count": len(expected) - len(valid),
        "coverage": len(valid) / len(expected),
        "quality_gate_passed": bool(passed),
        "status": "complete" if passed else "quality_failed",
        "comparison": {
            "comparable": comparable,
            "agree": comparable - len(conflicts),
            "conflicts": conflicts,
        },
        "results": valid,
        "scenario_results": details,
        "summary": full,
        "subset_summary": subset,
        "failures": [
            dict(scenario_id=sid, issue_id=expected[sid]["issue_id"], **row)
            for sid, row in details.items()
            if row["errors"]
        ],
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "rule": "one_primary_execution_no_cross_job_result_union",
    }


def import_executions(db, plan, exports, primary_job_id):
    integrated = integrate(plan, exports, primary_job_id)
    batches = {}
    for export in exports:
        jid = int(export["job_id"])
        matches = [
            b
            for b in db.scalars(
                select(ReleaseSimulationBatch).where(
                    ReleaseSimulationBatch.release == plan["release"]
                )
            )
            if int(b.payload.get("job_id") or 0) == jid
        ]
        if len(matches) != 1:
            raise ValueError("Registered execution not unique")
        batch = matches[0]
        if (
            batch.payload.get("population_hash") != plan["population_hash"]
            or batch.payload.get("binary_id") != plan["binary_id"]
        ):
            raise ValueError("Registered plan differs from import")
        if {str(s["scenario_id"]) for s in batch.payload.get("scenarios", [])} != {
            str(s["scenario_id"]) for s in plan["scenarios"]
        }:
            raise ValueError("Registered population differs from import")
        batches[jid] = batch
    for export in exports:
        jid = int(export["job_id"])
        batch = batches[jid]
        metadata = {
            k: v
            for k, v in integrated.items()
            if k not in ("results", "scenario_results", "summary")
        }
        batch.payload = {
            **batch.payload,
            "result_import": {**metadata, "primary": jid == primary_job_id},
            "quality": export["quality"]["quality"],
            "execution_progress": export["progress"],
        }
        if jid == primary_job_id:
            batch.payload = {
                **batch.payload,
                "results": integrated["results"],
                "scenario_results": integrated["scenario_results"],
                "summary": integrated["summary"],
            }
            batch.status = integrated["status"]
        else:
            batch.status = (
                "quality_failed"
                if not integrated["quality_gate_passed"]
                else "complete"
            )
    for export in exports:
        key = f"job-progress:{export['job_id']}"
        cache = db.get(ReleaseWorkflowState, key) or ReleaseWorkflowState(key=key)
        cache.payload = {
            "value": export["progress"],
            "attempt_at": datetime.now(timezone.utc).timestamp(),
        }
        db.add(cache)
    db.commit()
    return integrated
