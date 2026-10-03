"""Business-cycle KPIs and completed history, independent of legacy snapshots."""

from __future__ import annotations
from sqlalchemy import select
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services.release_workflow import status, effective_config, population_identity
from app.services.release_metrics import summarize_population


def render_kpi(current, metrics, source):
    tp, fp, fn, tn = (metrics.get(k, 0) for k in ("tp", "fp", "fn", "tn"))
    precision = metrics.get("precision")
    recall = metrics.get("recall")
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    population = metrics["eligible"]
    source_gt = {
        "data_source": "trail_view_2410_shuyi_contract",
        "online_precision": metrics.get("online_precision"),
        "online_recall": metrics.get("online_recall"),
        "total_scenarios": population,
        "auto_trigger_tp": source.get("precision_auto_tp", 0),
        "auto_trigger_fp": source.get("precision_denominator", 0)
        - source.get("precision_auto_tp", 0),
        "manual_trigger_fn": source.get("recall_denominator", 0)
        - source.get("recall_auto_tp", 0),
    }
    projection = {
        "available": True,
        "population_coverage": 1.0,
        "sim_precision": precision,
        "sim_business_recall": recall,
        "precision_gap": precision - metrics["online_precision"]
        if precision is not None and metrics.get("online_precision") is not None
        else None,
        "business_recall_gap": recall - metrics["online_recall"]
        if recall is not None and metrics.get("online_recall") is not None
        else None,
    }
    return {
        "version_key": current,
        "label": "release" + current[-8:],
        "total_cases": population,
        "road_positive_cases": source.get("precision_denominator", 0),
        "road_behavior_cases": population,
        "sim_positive_cases": tp + fp,
        "reproduced_cases": metrics["road_matches"],
        "sim_repro_rate": metrics["sim_repro_rate"],
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": tn / (tn + fp) if tn + fp else 0,
        "accuracy": (tp + tn) / population,
        "model_repro_rate": 0,
        "fn_fallback_rate": 0,
        "fp_suppress_rate": 0,
        "root_causes": {},
        "evaluated_cases": population,
        "dpe_coverage": 1,
        "quality_gate_passed": True,
        "positive_auto_repro_rate": metrics.get("positive_auto_repro_rate") or 0,
        "negative_auto_repro_rate": metrics.get("negative_auto_repro_rate") or 0,
        "positive_manual_repro_rate": metrics.get("positive_manual_repro_rate") or 0,
        "source_gt": source_gt,
        "sim_estimate": {
            "data_source": "full_release_workflow",
            "job_id": metrics.get("job_id"),
            "same_version_projection": projection,
            "estimated_tp": tp,
            "estimated_fn": fn,
            "estimated_fp": fp,
            "aggregation": metrics.get("aggregation"),
        },
    }


def context(db):
    value = status(db)
    current = value.get("current_version")
    metrics = value.get("metrics") or {}
    source = value.get("source_metrics") or {}
    kpi = (
        render_kpi(current, metrics, source)
        if metrics.get("available") and not value.get("acceptance_only")
        else None
    )
    return {
        "business_current_version": current,
        "business_metrics": kpi,
        "business_status": "complete"
        if kpi
        else "pending_simulation"
        if current
        else value["status"],
        "business_reason": metrics.get("reason", "") if not kpi else "",
        "period": value.get("current_period"),
        "metrics": metrics,
    }


def history_kpis(db):
    allowed = {
        p["release"]
        for p in effective_config(db).get("periods", [])
        if p.get("status") == "completed"
    }
    seen = set()
    items = []
    for batch in db.scalars(
        select(ReleaseSimulationBatch)
        .where(ReleaseSimulationBatch.status == "complete")
        .order_by(ReleaseSimulationBatch.updated_at.desc())
    ):
        if (
            batch.release in seen
            or batch.release not in allowed
            or batch.payload.get("acceptance_only")
            or (
                batch.payload.get("result_import")
                and not batch.payload["result_import"].get("primary")
            )
        ):
            continue
        seen.add(batch.release)
        snapshot = db.scalars(
            select(ReleaseIssueSnapshot)
            .where(ReleaseIssueSnapshot.release == batch.release)
            .order_by(ReleaseIssueSnapshot.id.desc())
            .limit(1)
        ).first()
        if not snapshot or batch.payload.get("population_hash") != population_identity(
            snapshot.payload
        ):
            continue
        metrics = batch.payload.get("summary") or {}
        if not metrics.get("available"):
            continue
        metrics = {**metrics, "job_id": batch.payload.get("job_id")}
        source = summarize_population(snapshot.payload["issues"], [], {})
        items.append(render_kpi(batch.release, metrics, source))
    return sorted(items, key=lambda item: item["version_key"])
