"""Business-cycle KPIs and completed history, independent of legacy snapshots."""

from __future__ import annotations

from sqlalchemy import select

from app.domain.cycle import resolve_current
from app.domain.metrics import summarize_population
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services.business_population import (
    display_retained_scope,
    historical_scope,
    scope_for_batch,
)
from app.services.ordinary_evaluation import history_kpis as ordinary_kpis
from app.services.read_views import read_projection, read_view
from app.services.release_inventory import inventory as collection_inventory
from app.services.release_workflow import effective_config, population_identity
from app.services.result_publication import effective_publication, published_batch
from app.services.workflow_orchestrator import status


def pending_kpi(release, scope, job_id=None):
    """Keep the release visible without drawing a partial execution as full KPIs."""
    total = scope.get("collected_issue_count") or 0
    return {
        "version_key": release,
        "label": "release" + release[-8:],
        "collection_scope": scope,
        "total_cases": total,
        "road_positive_cases": 0,
        "road_behavior_cases": 0,
        "sim_positive_cases": 0,
        "reproduced_cases": 0,
        "sim_repro_rate": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "specificity": None,
        "accuracy": None,
        "model_repro_rate": 0,
        "fn_fallback_rate": 0,
        "fp_suppress_rate": 0,
        "root_causes": {},
        "positive_auto_repro_rate": None,
        "negative_auto_repro_rate": None,
        "positive_manual_repro_rate": None,
        "evaluated_cases": scope.get("evaluated_issue_count") or 0,
        "dpe_coverage": 0,
        "quality_gate_passed": False,
        "sim_estimate": {
            "job_id": job_id,
            "data_source": "collection_pending",
            "estimated_tp": None,
            "estimated_fp": None,
            "estimated_fn": None,
            "same_version_projection": {"available": False},
        },
    }


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
        "manual_trigger_fn": source.get("recall_denominator", 0) - source.get("recall_auto_tp", 0),
    }
    projection = {
        "available": True,
        "population_coverage": metrics.get("publication", {}).get("coverage", 1.0),
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
        "sim_repro_rate": metrics.get("covered_repro_rate", metrics["sim_repro_rate"]),
        **({"reproduction": metrics["reproduction"]} if metrics.get("reproduction") else {}),
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
        "dpe_coverage": metrics.get("publication", {}).get("coverage", 1.0),
        "quality_gate_passed": metrics.get("quality_gate_passed", True),
        "publication": metrics.get("publication"),
        **{
            key: metrics.get(key) if metrics.get("reproduction") else metrics.get(key) or 0
            for key in (
                "positive_auto_repro_rate",
                "negative_auto_repro_rate",
                "positive_manual_repro_rate",
            )
        },
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


def context(db, value=None):
    value = status(db) if value is None else value
    current = value.get("current_version")
    metrics = value.get("metrics") or {}
    source = value.get("source_metrics") or {}
    approved = published_batch(db, current) if current else None
    scope = scope_for_batch(db, approved) if approved else None
    display_scope = display_retained_scope(scope, is_current=True) if scope else None
    scope_ready = bool(
        display_scope and (display_scope["available"] or display_scope.get("display_retained"))
    )
    if approved and scope_ready:
        metrics = effective_publication(db, approved)
        source = metrics
    elif display_scope:
        metrics = {
            "available": False,
            "reason": display_scope["reason_code"],
            "generated_at": display_scope.get("observed_at"),
        }
    kpi = (
        render_kpi(current, metrics, source)
        if metrics.get("available") and not value.get("acceptance_only")
        else None
    )
    return {
        "business_current_version": current,
        "business_metrics": kpi,
        "business_status": "collecting"
        if display_scope and not scope_ready and display_scope["collection_status"] == "collecting"
        else "pending_simulation"
        if display_scope and not scope_ready
        else "published_with_exclusions"
        if approved
        else "complete"
        if kpi
        else "pending_simulation"
        if current
        else value["status"],
        "business_reason": metrics.get("reason", "") if not kpi else "",
        "period": value.get("current_period"),
        "metrics": metrics,
        "business_collection": display_scope,
    }


def history_kpis(db):
    config = effective_config(db)
    current_version = resolve_current(config).get("current_version")
    allowed = {p["release"] for p in config.get("periods", []) if p.get("status") == "completed"}
    collections = collection_inventory(db, config)
    by_release: dict[str, dict] = {}

    # Highest priority first: ordinary_kpis overrides published_batch and raw batches.
    for item in ordinary_kpis(db):
        by_release[item["version_key"]] = item

    # Second priority: approved published batches (skip releases already covered above).
    for release in sorted(allowed):
        if release in by_release:
            continue

        def _load_published(rel=release):
            approved = published_batch(db, rel)
            if not approved:
                return None
            scope = display_retained_scope(
                historical_scope(
                    scope_for_batch(db, approved, collections=collections),
                    is_current=rel == current_version,
                ),
                is_current=rel == current_version,
            )
            if (
                scope["available"]
                or scope.get("historical_frozen")
                or scope.get("display_retained")
            ):
                metrics = effective_publication(db, approved)
                item = render_kpi(rel, metrics, metrics)
                if scope.get("historical_frozen") or scope.get("display_retained"):
                    item["collection_scope"] = scope
                return item
            return pending_kpi(rel, scope, approved.payload.get("job_id"))

        published_item = read_projection(
            db,
            ("history-kpi-published", release, release == current_version),
            _load_published,
            max_age=1800,
            scope_releases=[release],
        )
        if published_item is not None:
            by_release[release] = published_item

    # Third priority: latest complete non-backfill batch for remaining releases.
    remaining = allowed - by_release.keys()
    if remaining:
        seen = set()
        for batch in db.scalars(
            select(ReleaseSimulationBatch)
            .where(
                ReleaseSimulationBatch.status == "complete",
                ReleaseSimulationBatch.release.in_(remaining),
            )
            .order_by(ReleaseSimulationBatch.updated_at.desc())
        ):
            if (
                batch.release in seen
                or batch.payload.get("backfill")
                or batch.payload.get("acceptance_only")
                or (
                    batch.payload.get("result_import")
                    and not batch.payload["result_import"].get("primary")
                )
            ):
                continue
            seen.add(batch.release)

            def _load_batch(b=batch):
                snapshot = db.scalars(
                    select(ReleaseIssueSnapshot)
                    .where(ReleaseIssueSnapshot.release == b.release)
                    .order_by(ReleaseIssueSnapshot.id.desc())
                    .limit(1)
                ).first()
                if not snapshot:
                    return None
                snap_hash = getattr(snapshot, "population_hash", None) or population_identity(
                    snapshot.payload
                )
                if b.payload.get("population_hash") != snap_hash:
                    return None
                metrics = b.payload.get("summary") or {}
                if not metrics.get("available"):
                    return None
                scope = display_retained_scope(
                    historical_scope(
                        scope_for_batch(db, b, collections=collections),
                        is_current=b.release == current_version,
                    ),
                    is_current=b.release == current_version,
                )
                if (
                    not scope["available"]
                    and not scope.get("historical_frozen")
                    and not scope.get("display_retained")
                ):
                    return pending_kpi(b.release, scope, b.payload.get("job_id"))
                metrics = {**metrics, "job_id": b.payload.get("job_id")}
                source = summarize_population(snapshot.payload["issues"], [], {})
                item = render_kpi(b.release, metrics, source)
                if scope.get("historical_frozen") or scope.get("display_retained"):
                    item["collection_scope"] = scope
                return item

            batch_item = read_projection(
                db,
                (
                    "history-kpi-batch",
                    batch.release,
                    batch.fingerprint,
                    batch.release == current_version,
                ),
                _load_batch,
                max_age=1800,
                scope_releases=[batch.release],
            )
            if batch_item is not None:
                by_release[batch.release] = batch_item

    return sorted(by_release.values(), key=lambda item: item["version_key"])


def workflow_status(db):
    return read_view(db, "workflow-status", lambda: status(db), max_age=1800)


def business_context(db):
    return read_view(db, "business-context", lambda: context(db, workflow_status(db)), max_age=1800)


def cached_history_kpis(db):
    return read_view(db, "history-kpis", lambda: history_kpis(db), max_age=1800)
