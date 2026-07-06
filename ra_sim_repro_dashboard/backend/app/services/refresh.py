from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import config_hash, load_versions_config
from app.metrics import as_float, classify_result, first_present, normalize_reasons, summarize_rows
from app.models import DashboardSnapshot, Issue, RefreshJob, Scenario, ScenarioVersionResult, Version
from app.services.cache import cache
from app.services.issue_client import IssueClient
from app.services.scenario_client import ScenarioClient, build_source_scenario_index, source_counts_from_index
from app.services.sim_result_client import DataSourceUnavailable, SimResultClient


def create_refresh_job(db: Session) -> RefreshJob:
    payload = load_versions_config()
    job = RefreshJob(
        job_id=uuid.uuid4().hex,
        status="queued",
        progress=0,
        message="Queued refresh",
        config_hash=config_hash(payload),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def sync_versions_from_config(db: Session, payload: dict[str, Any]) -> list[Version]:
    current = str(payload.get("current_version") or "")
    ordered_keys = [*payload.get("compare_versions", []), current]
    ordered_keys = [key for key in ordered_keys if key]
    seen: set[str] = set()
    versions: list[Version] = []
    for idx, version_key in enumerate(ordered_keys):
        if version_key in seen:
            continue
        seen.add(version_key)
        item = dict(payload.get("versions", {}).get(version_key, {}))
        version = db.get(Version, version_key) or Version(version_key=version_key)
        runtime_metadata = {
            key: value
            for key, value in (version.metadata_json or {}).items()
            if str(key).startswith("_")
        }
        version.label = str(item.get("label") or version_key)
        version.sim_job_id = _optional_int(item.get("sim_job_id"))
        version.baseline_job_id = _optional_int(item.get("baseline_job_id"))
        version.sort_order = idx
        version.is_current = version_key == current
        version.metadata_json = {**item, **runtime_metadata}
        db.add(version)
        versions.append(version)
    db.commit()
    return versions


def refresh_dashboard(job_id: str, db: Session | None = None) -> None:
    own_session = db is None
    if db is None:
        from app.database import SessionLocal

        db = SessionLocal()
    try:
        _refresh_dashboard(job_id, db)
    finally:
        if own_session:
            db.close()


def _refresh_dashboard(job_id: str, db: Session) -> None:
    job = db.get(RefreshJob, job_id)
    if job is None:
        raise ValueError(f"Refresh job not found: {job_id}")

    payload = load_versions_config()
    lock_key = f"ra:lock:refresh:{config_hash(payload)}"
    if not cache.lock(lock_key, ttl=900):
        job.status = "failed"
        job.error = "A refresh for this version config is already running."
        job.finished_at = datetime.utcnow()
        db.commit()
        return

    sim_client = SimResultClient()
    scenario_client = ScenarioClient()
    issue_client = IssueClient()
    refresh_warnings: list[str] = []
    try:
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.message = "Syncing version config"
        job.progress = 5
        db.commit()

        versions = sync_versions_from_config(db, payload)
        total_versions = max(len(versions), 1)
        all_issue_ids: set[str] = set()

        for index, version in enumerate(versions, start=1):
            metadata = dict(version.metadata_json or {})
            positive_job_id, negative_job_id = _eval_job_pair(version)
            if version.sim_job_id is None and (positive_job_id is None or negative_job_id is None):
                continue
            job.message = f"Fetching source scenarios for {version.label}"
            job.progress = 5 + int(index / total_versions * 60)
            db.commit()

            source_index, source_warning = _safe_fetch_source_index(metadata, scenario_client)
            if source_warning:
                refresh_warnings.append(f"{version.version_key}: {source_warning}")
            source_counts = source_counts_from_index(source_index) if source_index else {}
            metadata = {
                **metadata,
                "_source_gt_status": "live" if source_counts else "config_fallback",
                "_source_gt_live": source_counts,
            }
            if source_warning:
                metadata["_source_gt_error"] = source_warning
            else:
                metadata.pop("_source_gt_error", None)
            version.metadata_json = metadata
            db.add(version)
            db.commit()

            job.message = f"Fetching sim jobs for {version.label}"
            db.commit()

            sim_rows_loaded = False
            try:
                if positive_job_id is not None and negative_job_id is not None:
                    rows = sim_client.query_eval_jobs(
                        positive_job_id=positive_job_id,
                        negative_job_id=negative_job_id,
                        version_key=version.version_key,
                    )
                else:
                    rows = sim_client.query_job(version.sim_job_id, version.baseline_job_id)  # type: ignore[arg-type]
                sim_rows_loaded = True
            except DataSourceUnavailable as exc:
                rows = []
                refresh_warnings.append(f"{version.version_key}: {exc}")
            except Exception as exc:
                rows = []
                refresh_warnings.append(f"{version.version_key}: sim API failed: {exc}")

            if sim_rows_loaded:
                db.execute(
                    delete(ScenarioVersionResult).where(
                        ScenarioVersionResult.version_key == version.version_key
                    )
                )
                db.commit()

            for raw in rows:
                scenario_id = str(raw.get("scenario_id") or "").strip()
                if not scenario_id:
                    continue
                source_info = source_index.get(scenario_id, {})
                issue_id = _clean_optional(raw.get("issue_id") or source_info.get("issue_id"))
                if issue_id:
                    all_issue_ids.add(issue_id)

                scenario = db.get(Scenario, scenario_id) or Scenario(scenario_id=scenario_id)
                scenario.scenario_name = str(
                    raw.get("scenario_name")
                    or source_info.get("scenario_name")
                    or scenario.scenario_name
                    or ""
                )
                scenario.issue_id = issue_id
                scenario.signature = str(raw.get("signature") or source_info.get("signature") or scenario.signature or "")
                scenario.raw_info = {
                    "scenario_id": scenario_id,
                    "scenario_name": scenario.scenario_name,
                    "issue_id": issue_id,
                    "signature": scenario.signature,
                    "source_groups": source_info.get("source_groups", []),
                    "source_labels": source_info.get("source_labels", []),
                }
                db.add(scenario)

                normalized = _normalize_result_raw(raw)
                normalized["data_source"] = "query_report"
                normalized["source_groups"] = source_info.get("source_groups", [])
                normalized["source_labels"] = source_info.get("source_labels", [])
                normalized["source_gt_status"] = metadata.get("_source_gt_status")
                classified = classify_result(normalized)
                result = db.execute(
                    select(ScenarioVersionResult).where(
                        ScenarioVersionResult.version_key == version.version_key,
                        ScenarioVersionResult.scenario_id == scenario_id,
                    )
                ).scalar_one_or_none()
                if result is None:
                    result = ScenarioVersionResult(
                        version_key=version.version_key,
                        scenario_id=scenario_id,
                    )
                result.issue_id = issue_id
                result.road_triggered = classified.road_triggered
                result.sim_triggered = classified.sim_triggered
                result.reproduced = classified.reproduced
                result.precision_label = classified.precision_label
                result.trigger_type = classified.trigger_type
                result.root_cause = classified.root_cause
                result.model_score_max = as_float(normalized.get("model_score_max"))
                result.threshold = as_float(normalized.get("threshold"))
                result.unstuck_status = str(normalized.get("unstuck_status") or "")
                result.fp_reasons = normalize_reasons(normalized.get("fp_reasons"))
                result.fn_reasons = normalize_reasons(normalized.get("fn_reasons"))
                result.raw_metrics = normalized
                db.add(result)

            version.last_refreshed_at = datetime.utcnow()
            db.add(version)
            db.commit()

        job.message = "Fetching issue metadata"
        job.progress = 80
        db.commit()
        issues = issue_client.query_issues(sorted(all_issue_ids))
        for issue_id, payload in issues.items():
            issue = db.get(Issue, issue_id) or Issue(issue_id=issue_id)
            issue.issue_topic = str(payload.get("issue_topic") or payload.get("title") or "")
            issue.status = str(payload.get("status") or "")
            issue.priority = str(payload.get("priority") or "")
            issue.poi = str(payload.get("poi") or "")
            issue.issue_time = str(payload.get("issue_time") or "")
            issue.url = str(payload.get("url") or _issue_url(issue_id))
            issue.raw_issue = payload
            db.add(issue)
        db.commit()

        snapshot = build_snapshot(db, payload)
        db.add(
            DashboardSnapshot(
                config_hash=config_hash(payload),
                current_version=str(payload.get("current_version") or ""),
                snapshot=snapshot,
            )
        )
        job.status = "completed"
        job.progress = 100
        job.message = _refresh_complete_message(refresh_warnings)
        job.finished_at = datetime.utcnow()
        db.commit()
        cache.delete_prefix("ra:")
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.finished_at = datetime.utcnow()
        db.commit()
        raise
    finally:
        cache.unlock(lock_key)


def build_snapshot(db: Session, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or load_versions_config()
    configured_keys = _ordered_version_keys(payload)
    versions_stmt = select(Version)
    if configured_keys:
        versions_stmt = versions_stmt.where(Version.version_key.in_(configured_keys))
    versions = db.execute(versions_stmt.order_by(Version.sort_order)).scalars().all()
    comparison = []
    for version in versions:
        rows = db.execute(
            select(ScenarioVersionResult).where(
                ScenarioVersionResult.version_key == version.version_key
            )
        ).scalars().all()
        summary = _summary_from_live_rows(rows, version.metadata_json) if rows else None
        summary = summary or _summary_from_metadata(version.metadata_json) or summarize_rows(rows)
        comparison.append(
            {
                "version_key": version.version_key,
                "label": version.label,
                "sort_order": version.sort_order,
                **summary,
            }
        )
    current_key = str(payload.get("current_version") or "")
    current = next((item for item in comparison if item["version_key"] == current_key), None)
    previous = comparison[-2] if len(comparison) >= 2 else None
    deltas = {}
    if current and previous:
        for key in ["sim_repro_rate", "precision", "recall", "f1", "fp_suppress_rate"]:
            deltas[key] = round(float(current.get(key, 0)) - float(previous.get(key, 0)), 4)
    return {
        "config_hash": config_hash(payload),
        "generated_at": datetime.utcnow().isoformat(),
        "current": current,
        "previous": previous,
        "deltas": deltas,
        "comparison": comparison,
    }


def _normalize_result_raw(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    if "dpe_assist_channel_triggered" not in data:
        data["dpe_assist_channel_triggered"] = first_present(
            data,
            "dpe_assist_channel_triggered__group1",
            "group1__dpe_assist_channel_triggered",
            "assist_channel_triggered",
        )
    data["sim_triggered"] = first_present(data, "sim_triggered", "dpe_assist_channel_triggered")
    data["road_triggered"] = first_present(data, "road_triggered")
    if data["road_triggered"] is None:
        data["road_triggered"] = True
    data["model_score_max"] = first_present(
        data,
        "model_score_max",
        "max_scen_dnn",
        "scenario_dnn_stuck_likelihood_from_ra_vnode",
    )
    data["threshold"] = first_present(data, "threshold", "stuck_threshold")
    data["fp_reasons"] = normalize_reasons(first_present(data, "fp_reasons", "fp_process_reasons"))
    data["fn_reasons"] = normalize_reasons(first_present(data, "fn_reasons", "fn_process_reasons"))
    return data


def _summary_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    metadata = metadata or {}
    source = _source_gt_payload(metadata)
    sim = metadata.get("sim_eval") or {}
    if not source and not sim:
        return None

    source_tp = _int_value(source.get("auto_trigger_tp"))
    source_fn = _int_value(source.get("manual_trigger_fn"))
    source_fp = _int_value(source.get("auto_trigger_fp"))
    source_total = _int_value(source.get("total_scenarios")) or (
        source_tp
        + source_fn
        + source_fp
        + _int_value(source.get("manual_trigger_irrelevant"))
        + _int_value(source.get("normal_wait_tn_partial"))
    )
    source_positive = source_tp + source_fn

    precision = _float_value(sim.get("precision"))
    recall = _float_value(sim.get("recall"))
    if precision is None:
        precision = _float_value(source.get("calculated_precision"))
    if recall is None:
        recall = _float_value(source.get("calculated_recall"))
    if precision is None:
        precision = _rate(source_tp, source_tp + source_fp)
    if recall is None:
        recall = _rate(source_tp, source_positive)

    estimated_tp = _int_value(sim.get("tp"))
    estimated_fp = _int_value(sim.get("fp"))
    estimated_fn = _int_value(sim.get("fn"))
    if not estimated_tp and recall is not None and source_positive:
        estimated_tp = round(recall * source_positive)
    if not estimated_fp and precision is not None and precision > 0 and estimated_tp:
        estimated_fp = max(round(estimated_tp / precision - estimated_tp), 0)
    if not estimated_fn and estimated_tp and source_positive:
        estimated_fn = max(source_positive - estimated_tp, 0)

    precision = round(float(precision or 0), 4)
    recall = round(float(recall or 0), 4)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
    sim_positive = estimated_tp + estimated_fp

    return {
        "total_cases": source_total,
        "road_positive_cases": source_positive,
        "sim_positive_cases": sim_positive,
        "reproduced_cases": estimated_tp,
        "sim_repro_rate": recall,
        "model_repro_rate": recall,
        "fn_fallback_rate": 0.0,
        "fp_suppress_rate": _rate(estimated_fp, max(source_total, 1)),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "root_causes": {
            "SOURCE_TP": source_tp,
            "SOURCE_FP": source_fp,
            "SOURCE_FN": source_fn,
        },
        "source_gt": source,
        "sim_estimate": {
            **sim,
            "estimated_tp": estimated_tp,
            "estimated_fp": estimated_fp,
            "estimated_fn": estimated_fn,
            "data_source": "config_fallback",
        },
    }


def _summary_from_live_rows(rows: list[ScenarioVersionResult], metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not rows:
        return None
    summary = summarize_rows(rows)
    tp = sum(1 for row in rows if row.precision_label == "TP")
    fp = sum(1 for row in rows if row.precision_label == "FP")
    fn = sum(1 for row in rows if row.precision_label == "FN")
    tn = sum(1 for row in rows if row.precision_label == "TN")
    metadata = metadata or {}
    source = _source_gt_payload(metadata)
    summary["source_gt"] = source
    summary["sim_estimate"] = {
        "estimated_tp": tp,
        "estimated_fp": fp,
        "estimated_fn": fn,
        "estimated_tn": tn,
        "pos_job_id": (metadata.get("sim_jobs") or {}).get("positive_job_id"),
        "neg_job_id": (metadata.get("sim_jobs") or {}).get("negative_job_id"),
        "data_source": "query_report",
        "source_gt_status": metadata.get("_source_gt_status", "unknown"),
        "source_gt_error": metadata.get("_source_gt_error", ""),
    }
    return summary


def _source_gt_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    configured = dict(metadata.get("source_gt_counts") or {})
    live = dict(metadata.get("_source_gt_live") or {})
    if live:
        return {**configured, **live, "data_source": "scenario_api"}
    if configured:
        return {**configured, "data_source": "config_fallback"}
    return {}


def _safe_fetch_source_index(
    metadata: dict[str, Any],
    scenario_client: ScenarioClient,
) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        return build_source_scenario_index(metadata, scenario_client), ""
    except Exception as exc:
        return {}, f"source scenario API fallback: {exc}"


def _eval_job_pair(version: Version) -> tuple[int | None, int | None]:
    metadata = version.metadata_json or {}
    sim_jobs = metadata.get("sim_jobs") or {}
    sim_eval = metadata.get("sim_eval") or {}
    positive = _optional_int(
        sim_jobs.get("positive_job_id")
        or sim_eval.get("pos_job_id")
        or sim_eval.get("positive_job_id")
        or version.sim_job_id
    )
    negative = _optional_int(
        sim_jobs.get("negative_job_id")
        or sim_eval.get("neg_job_id")
        or sim_eval.get("negative_job_id")
    )
    return positive, negative


def _refresh_complete_message(warnings: list[str]) -> str:
    if not warnings:
        return "Refresh completed from real APIs"
    if len(warnings) <= 2:
        return "Refresh completed with fallback: " + " | ".join(warnings)
    return f"Refresh completed with {len(warnings)} API fallback warnings"


def _ordered_version_keys(payload: dict[str, Any]) -> list[str]:
    current = str(payload.get("current_version") or "")
    keys = [str(key) for key in payload.get("compare_versions", []) if key]
    if current:
        keys.append(current)
    return list(dict.fromkeys(keys))


def _int_value(value: Any) -> int:
    if value in {None, ""}:
        return 0
    return int(value)


def _float_value(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _issue_url(issue_id: str) -> str:
    return f"https://voyager.intra.xiaojukeji.com/paladin/issue/detail/{issue_id}"
