"""Synchronize mutable Scenario cohort tags against the accepted metric revision."""

from datetime import datetime, timezone
import logging

from app.models import ReleaseIssueSnapshot
from app.services import release_workflow as w
from app.services.auto_triage_metrics import _snapshot
from app.services.label_recovery import SCENE_FIELDS
from app.services.release_cycle import real_labels
from app.services.reproduction_evidence import standard_inputs
from app.services.result_publication import coverage_policy, effective_publication
from ra_api.release_labels import cohort_label_update, full_scene_label


def plan_changes(issues, scenes, live, period):
    label = full_scene_label(period)
    cohorts = {str(i["issue_id"]): w.cohort_for_issue(i) for i in issues}
    upstream = {s["scenario_id"]: s for s in live}
    changes = []
    for frozen in scenes:
        cohort = cohorts.get(str(frozen["issue_id"]))
        if not cohort:
            continue
        scene = upstream.get(str(frozen["scenario_id"]))
        if (
            not scene
            or any(scene.get(k) is None or scene[k] != frozen.get(k) for k in SCENE_FIELDS)
            or scene["start_timestamp"] >= scene["end_timestamp"]
        ):
            raise ValueError("scenario_input_changed")
        after = cohort_label_update(scene, label, period["release"], cohort)
        if after is not None:
            changes.append(
                {k: scene[k] for k in ("scenario_id", *SCENE_FIELDS)}
                | {"cohort": cohort, "before_labels": real_labels(scene), "after_labels": after}
            )
    return changes


def synchronize(db, config, batch, state):
    if (
        state.get("status") not in ("idle", "updated")
        or not state.get("applied_source_hash")
        or w.get_state(db, "settings").get("mode") != "auto"
        or not coverage_policy(config)["enabled"]
    ):
        return
    release = batch.release
    key = "scene_cohort_sync:" + release
    previous = w.get_state(db, key)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "checked_at": now,
        "job_id": batch.payload["job_id"],
        "revision_key": state.get("revision_key"),
        "source_hash": state["applied_source_hash"],
    }
    try:
        metrics = effective_publication(db, batch)
        if not metrics or (metrics.get("label_revision") or {}).get("revision_key") != state.get(
            "revision_key"
        ):
            raise ValueError("metric_revision_changed")
        issues, scenes, _, _ = standard_inputs(db, batch, metrics)
        snapshot = _snapshot(db, release)
        if (
            not snapshot
            or snapshot.payload.get("mapping_error")
            or not snapshot.payload.get("population_complete")
        ):
            raise ValueError("snapshot_unavailable")
        period = snapshot.payload["period"]
        label = full_scene_label(period)
        if (
            period.get("release") != release
            or not period.get("verified")
            or batch.payload.get("scenario_label", label) != label
        ):
            raise ValueError("scenario_namespace_changed")
        # Read the platform even for an idle revision. This recovers partial writes
        # and picks up label changes made after an earlier publication.
        live = w.fetch_scenarios({"scenario_query_labels": [label]})
        changes = plan_changes(issues, scenes, live, period)
        if changes:
            receipts = []
            for start in range(0, len(changes), 10):
                chunk = changes[start : start + 10]
                payload = {
                    "release": release,
                    "period": period,
                    "label": label,
                    "source_hash": state["applied_source_hash"],
                    "changes": chunk,
                    "published_binding": {
                        "job_id": record["job_id"],
                        "revision_key": state.get("revision_key"),
                        "fingerprint": batch.fingerprint,
                    },
                }
                receipt = w.driver_call(config, "reconcile_labels", payload)
                if (
                    receipt.get("ready") is not True
                    or receipt.get("verified_count") != len(chunk)
                    or receipt.get("request_hash") != w.digest(payload)
                    or not receipt.get("audit_path")
                ):
                    raise ValueError("scenario_label_receipt_invalid")
                receipts.append(receipt)
            record["last_write"] = {
                "receipts": receipts,
                "verified_count": len(changes),
                "applied_at": now,
                "revision_key": state.get("revision_key"),
            }
            live = w.fetch_scenarios({"scenario_query_labels": [label]})
            if plan_changes(issues, scenes, live, period):
                raise ValueError("scenario_label_readback_mismatch")

        # Append an observation for the dashboard. Keep the original snapshot,
        # job inputs, metric revision and labels from the execution untouched.
        upstream = {s["scenario_id"]: s for s in live}
        observed = []
        changed = False
        for row in snapshot.payload["scenarios"]:
            scene = upstream.get(str(row["scenario_id"]))
            if (
                scene
                and all(scene.get(k) == row.get(k) for k in SCENE_FIELDS)
                and real_labels(scene) != real_labels(row)
            ):
                row = {**row, "scenario_labels": real_labels(scene)}
                if "labels" in row:
                    row["labels"] = row["scenario_labels"]
                changed = True
            observed.append(row)
        if changed:
            if _snapshot(db, release).id != snapshot.id:
                raise ValueError("snapshot_changed")
            db.add(
                ReleaseIssueSnapshot(
                    release=release,
                    period_hash=snapshot.period_hash,
                    payload={**snapshot.payload, "scenarios": observed},
                )
            )
        w.put_state(
            db,
            key,
            {
                **previous,
                **record,
                "status": "complete",
                "error": None,
                "changed_count": len(changes),
            },
        )
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).exception(
            "Scenario label synchronization failed for %s", release
        )
        w.put_state(
            db,
            key,
            {
                **previous,
                **record,
                "status": "failed",
                "error": str(exc)[:300] if isinstance(exc, ValueError) else type(exc).__name__,
            },
        )
