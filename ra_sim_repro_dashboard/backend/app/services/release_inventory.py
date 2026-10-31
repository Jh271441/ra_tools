"""Read-only release collection inventory; never fetch upstream from a page request."""
from datetime import datetime, timezone
from sqlalchemy import select
from app.models import ReleaseWorkflowState

from app.services import release_workflow as w
from app.services.release_watch import MAX_OBSERVATION_GAP_SECONDS


def inventory(db, config=None, now=None):
    config = config if config is not None else w.effective_config(db)
    now = now or datetime.now(timezone.utc)
    versions = {}
    for period in config.get("periods", []):
        if period.get("status") != "completed" or not period.get("verified"):
            continue
        snapshot = w.latest_snapshot(db, w.period_key(config, period))
        complete = bool(snapshot and snapshot.payload.get("population_complete"))
        issues = snapshot.payload["issues"] if snapshot else []
        versions[period["release"]] = {
            "release": period["release"], "collection_status": "stable" if complete else "pending",
            "source": "snapshot", "issue_count": len(issues) if snapshot else None,
            "auto_count": sum(int(i["ra_type"]) == 2 for i in issues) if snapshot else None,
            "manual_count": sum(int(i["ra_type"]) == 3 for i in issues) if snapshot else None,
            "synced_at": snapshot.created_at.replace(tzinfo=timezone.utc).isoformat() if snapshot else None,
            "last_issue_at": None, "quiet_since": None, "eligible_at": None,
            "stale": False, "monitor_status": None,
        }
    monitors = {row.payload["release"]: row.payload for row in db.scalars(select(ReleaseWorkflowState).where(
        ReleaseWorkflowState.key.startswith("release_monitor:"))) if row.payload.get("release")}
    latest = w.get_state(db, "release_monitor")
    if latest.get("release"):
        monitors[latest["release"]] = latest
    for monitor in monitors.values():
        release = monitor["release"]
        observed = w.get_state(db, "release_observation:" + release)
        last = monitor.get("last_success_at")
        stale = not last or not 0 <= (now - datetime.fromisoformat(last)).total_seconds() <= MAX_OBSERVATION_GAP_SECONDS
        same = observed.get("activity_hash") == monitor.get("activity_hash") and bool(observed)
        stable = (not stale and same and monitor.get("quiet_seconds", 0) >= 86400)
        # Keep a frozen stable population's source, but expose any late changes/error.
        item = versions.get(release)
        if item and item["collection_status"] == "stable" and not monitor.get("population_changed_after_submission"):
            item.update(monitor_status=monitor.get("status"), stale=stale)
        else:
            issues = observed.get("issues", [])
            versions[release] = {
                "release": release, "collection_status": "stable" if stable else "collecting",
                "source": "observation", "issue_count": len(issues) if observed else monitor.get("issue_count"),
                "auto_count": sum(int(i["ra_type"]) == 2 for i in issues) if observed else None,
                "manual_count": sum(int(i["ra_type"]) == 3 for i in issues) if observed else None,
                "synced_at": observed.get("observed_at"), "last_issue_at": monitor.get("last_issue_at"),
                "quiet_since": monitor.get("quiet_since") if not stale else None,
                "eligible_at": monitor.get("eligible_at") if not stale else None,
                "stale": stale or not same, "monitor_status": monitor.get("status"),
            }
        versions[release].update(
            monitor_status=monitor.get("status"),
            monitor_error_code=monitor.get("error_code"),
            monitor_error_action=monitor.get("error_action"),
            preparation=monitor.get("preparation"),
            quiet_seconds=min(86400, max(0, monitor.get("quiet_seconds", 0))) if not stale and same else 0,
            quiet_seconds_required=monitor.get("quiet_seconds_required", 86400),
            last_issue_at=monitor.get("last_issue_at"),
            last_success_at=last,
            quiet_since=monitor.get("quiet_since") if not stale else None,
            eligible_at=monitor.get("eligible_at") if not stale else None,
            population_changed_after_submission=bool(monitor.get("population_changed_after_submission")),
        )
    items = sorted(versions.values(), key=lambda v: v["release"], reverse=True)
    return {"default_release": next((v["release"] for v in items if v["collection_status"] == "stable"), None),
            "versions": items}


def observation_issues(db, release, page, page_size, query, label):
    observed = w.get_state(db, "release_observation:" + release)
    items = []
    for issue in observed.get("issues", []):
        row = {
            "issue_id": str(issue["issue_id"]), "issue_topic": str(issue.get("issue_topic") or ""),
            "source_result": issue.get("ra_merge_result"), "version_key": release,
            "road_version": str(issue.get("version", "")), "ra_type": issue.get("ra_type"),
            "issue_time": issue.get("issue_time"), "scenario_id": "", "scenario_name": "",
            "scenario_labels": [], "simulation_status": "collecting",
            "sim_triggered": None, "reproduced": None, "precision_label": None,
        }
        if label or (query and query.lower() not in (row["issue_id"] + " " + row["issue_topic"] + " " + row["road_version"]).lower()):
            continue
        items.append(row)
    items.sort(key=lambda r: (r["issue_time"] or 0, r["issue_id"]), reverse=True)
    return {"items": items[(page - 1) * page_size:page * page_size], "total": len(items),
            "page": page, "page_size": page_size, "status": "collecting" if observed else "pending",
            "synced_at": observed.get("observed_at")}
