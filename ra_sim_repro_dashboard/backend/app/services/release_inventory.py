"""Read-only release collection inventory; never fetch upstream from a page request."""

from datetime import datetime, timezone
import json
from sqlalchemy import bindparam, func, select, text
from app.domain.labels import MAX_OBSERVATION_GAP_SECONDS, QUIET_SECONDS
from app.models import ReleaseIssueSnapshot, ReleaseWorkflowState
from app.services import release_workflow as w
from app.services.label_issue_view import applied_rows


def _is_postgresql(db) -> bool:
    try:
        bind = db.get_bind()
        return bind is not None and bind.dialect.name == "postgresql"
    except Exception:
        return False


def _pg_snapshot_summaries(db, period_keys: list[str]) -> dict[str, dict]:
    stmt = text(
        """
        SELECT
            s.period_hash,
            s.created_at,
            COALESCE((s.payload->>'population_complete')::boolean, false) AS population_complete,
            CASE
                WHEN jsonb_typeof(s.payload->'issues') = 'array'
                THEN jsonb_array_length(s.payload->'issues')
                ELSE 0
            END AS issue_count,
            COALESCE((
                SELECT count(*)
                FROM jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(s.payload->'issues') = 'array'
                        THEN s.payload->'issues'
                        ELSE '[]'::jsonb
                    END
                ) AS e
                WHERE (e->>'ra_type') = '2'
            ), 0) AS auto_count,
            COALESCE((
                SELECT count(*)
                FROM jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(s.payload->'issues') = 'array'
                        THEN s.payload->'issues'
                        ELSE '[]'::jsonb
                    END
                ) AS e
                WHERE (e->>'ra_type') = '3'
            ), 0) AS manual_count
        FROM release_issue_snapshots s
        JOIN (
            SELECT max(id) AS id
            FROM release_issue_snapshots
            WHERE period_hash IN :keys
            GROUP BY period_hash
        ) latest ON s.id = latest.id
        """
    ).bindparams(bindparam("keys", expanding=True))
    out: dict[str, dict] = {}
    for row in db.execute(stmt, {"keys": period_keys}).mappings():
        out[str(row["period_hash"])] = {
            "created_at": row["created_at"],
            "population_complete": bool(row["population_complete"]),
            "issue_count": int(row["issue_count"] or 0),
            "auto_count": int(row["auto_count"] or 0),
            "manual_count": int(row["manual_count"] or 0),
        }
    return out


def _pg_observation_summaries(db, obs_keys: list[str]) -> dict[str, dict]:
    stmt = text(
        """
        SELECT
            r.key,
            r.payload->>'activity_hash' AS activity_hash,
            r.payload->>'observed_at' AS observed_at,
            CASE
                WHEN jsonb_typeof(r.payload->'issues') = 'array'
                THEN jsonb_array_length(r.payload->'issues')
                ELSE 0
            END AS issue_count,
            COALESCE((
                SELECT count(*)
                FROM jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(r.payload->'issues') = 'array'
                        THEN r.payload->'issues'
                        ELSE '[]'::jsonb
                    END
                ) AS e
                WHERE (e->>'ra_type') = '2'
            ), 0) AS auto_count,
            COALESCE((
                SELECT count(*)
                FROM jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(r.payload->'issues') = 'array'
                        THEN r.payload->'issues'
                        ELSE '[]'::jsonb
                    END
                ) AS e
                WHERE (e->>'ra_type') = '3'
            ), 0) AS manual_count
        FROM release_workflow_state r
        WHERE r.key IN :keys
          AND r.payload <> '{}'::jsonb
        """
    ).bindparams(bindparam("keys", expanding=True))
    out: dict[str, dict] = {}
    for row in db.execute(stmt, {"keys": obs_keys}).mappings():
        out[str(row["key"])] = {
            "activity_hash": row["activity_hash"],
            "observed_at": row["observed_at"],
            "issue_count": int(row["issue_count"] or 0),
            "auto_count": int(row["auto_count"] or 0),
            "manual_count": int(row["manual_count"] or 0),
        }
    return out


def inventory(db, config=None, now=None):
    config = config if config is not None else w.effective_config(db)
    now = now or datetime.now(timezone.utc)
    use_pg_sql = _is_postgresql(db)
    versions = {}
    verified_periods = [
        (period, w.period_key(config, period))
        for period in config.get("periods", [])
        if period.get("status") == "completed" and period.get("verified")
    ]
    period_keys = [key for _, key in verified_periods]
    if period_keys and use_pg_sql:
        pg_snaps = _pg_snapshot_summaries(db, period_keys)
        for period, pkey in verified_periods:
            snap = pg_snaps.get(pkey)
            complete = bool(snap and snap["population_complete"])
            versions[period["release"]] = {
                "release": period["release"],
                "collection_status": "stable" if complete else "pending",
                "collection_completed": complete,
                "source": "snapshot",
                "issue_count": snap["issue_count"] if snap else None,
                "auto_count": snap["auto_count"] if snap else None,
                "manual_count": snap["manual_count"] if snap else None,
                "synced_at": snap["created_at"].replace(tzinfo=timezone.utc).isoformat()
                if snap and snap["created_at"] is not None
                else None,
                "last_issue_at": None,
                "quiet_since": None,
                "eligible_at": None,
                "stale": False,
                "monitor_status": None,
            }
    else:
        snapshots_by_key = {}
        if period_keys:
            latest_ids = (
                select(func.max(ReleaseIssueSnapshot.id).label("id"))
                .where(ReleaseIssueSnapshot.period_hash.in_(period_keys))
                .group_by(ReleaseIssueSnapshot.period_hash)
                .subquery()
            )
            for snap in db.scalars(
                select(ReleaseIssueSnapshot).join(
                    latest_ids, ReleaseIssueSnapshot.id == latest_ids.c.id
                )
            ):
                snapshots_by_key[snap.period_hash] = snap
        for period, pkey in verified_periods:
            snapshot = snapshots_by_key.get(pkey)
            complete = bool(snapshot and snapshot.payload.get("population_complete"))
            issues = snapshot.payload["issues"] if snapshot else []
            versions[period["release"]] = {
                "release": period["release"],
                "collection_status": "stable" if complete else "pending",
                "collection_completed": complete,
                "source": "snapshot",
                "issue_count": len(issues) if snapshot else None,
                "auto_count": sum(int(i["ra_type"]) == 2 for i in issues) if snapshot else None,
                "manual_count": sum(int(i["ra_type"]) == 3 for i in issues) if snapshot else None,
                "synced_at": snapshot.created_at.replace(tzinfo=timezone.utc).isoformat()
                if snapshot
                else None,
                "last_issue_at": None,
                "quiet_since": None,
                "eligible_at": None,
                "stale": False,
                "monitor_status": None,
            }
    monitors = {
        row.payload["release"]: row.payload
        for row in db.scalars(
            select(ReleaseWorkflowState).where(
                ReleaseWorkflowState.key.startswith("release_monitor:")
            )
        )
        if row.payload.get("release")
    }
    latest = w.get_state(db, "release_monitor")
    if latest.get("release"):
        monitors[latest["release"]] = latest
    obs_keys = [f"release_observation:{rel}" for rel in monitors]
    if obs_keys and use_pg_sql:
        observations = _pg_observation_summaries(db, obs_keys)
    else:
        observations = (
            {
                row.key: row.payload
                for row in db.scalars(
                    select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.in_(obs_keys))
                )
            }
            if obs_keys
            else {}
        )
    for monitor in monitors.values():
        release = monitor["release"]
        observed = observations.get("release_observation:" + release) or {}
        last = monitor.get("last_success_at")
        stale = (
            not last
            or not 0
            <= (now - datetime.fromisoformat(last)).total_seconds()
            <= MAX_OBSERVATION_GAP_SECONDS
        )
        same = observed.get("activity_hash") == monitor.get("activity_hash") and bool(observed)
        stable = not stale and same and monitor.get("quiet_seconds", 0) >= 86400
        # A delayed poll cannot undo a previously observed full quiet window.
        # This display receipt does not authorize preparation or submission:
        # collection_status/stale retain their existing freshness gate below.
        completed = same and monitor.get("quiet_seconds", 0) >= QUIET_SECONDS
        # Keep a frozen stable population's source, but expose any late changes/error.
        item = versions.get(release)
        if (
            item
            and item["collection_status"] == "stable"
            and not monitor.get("population_changed_after_submission")
        ):
            item.update(monitor_status=monitor.get("status"), stale=stale)
        else:
            if use_pg_sql:
                obs_issue_count = (
                    observed["issue_count"] if observed else monitor.get("issue_count")
                )
                obs_auto_count = observed["auto_count"] if observed else None
                obs_manual_count = observed["manual_count"] if observed else None
            else:
                issues = observed.get("issues", [])
                obs_issue_count = len(issues) if observed else monitor.get("issue_count")
                obs_auto_count = sum(int(i["ra_type"]) == 2 for i in issues) if observed else None
                obs_manual_count = sum(int(i["ra_type"]) == 3 for i in issues) if observed else None
            versions[release] = {
                "release": release,
                "collection_status": "stable" if stable else "collecting",
                "source": "observation",
                "issue_count": obs_issue_count,
                "auto_count": obs_auto_count,
                "manual_count": obs_manual_count,
                "synced_at": observed.get("observed_at"),
                "last_issue_at": monitor.get("last_issue_at"),
                "quiet_since": monitor.get("quiet_since") if not stale else None,
                "eligible_at": monitor.get("eligible_at") if not stale else None,
                "stale": stale or not same,
                "monitor_status": monitor.get("status"),
            }
        versions[release].update(
            collection_completed=bool(versions[release].get("collection_completed") or completed),
            monitor_status=monitor.get("status"),
            monitor_error_code=monitor.get("error_code"),
            monitor_error_action=monitor.get("error_action"),
            preparation=monitor.get("preparation"),
            quiet_seconds=min(86400, max(0, monitor.get("quiet_seconds", 0)))
            if not stale and same
            else 0,
            quiet_seconds_required=monitor.get("quiet_seconds_required", 86400),
            last_issue_at=monitor.get("last_issue_at"),
            last_success_at=last,
            quiet_since=monitor.get("quiet_since") if not stale else None,
            eligible_at=monitor.get("eligible_at") if not stale else None,
            population_changed_after_submission=bool(
                monitor.get("population_changed_after_submission")
            ),
        )
    items = sorted(versions.values(), key=lambda v: v["release"], reverse=True)
    return {
        "default_release": next(
            (v["release"] for v in items if v["collection_status"] == "stable"), None
        ),
        "versions": items,
    }


def observation_issues(db, release, page, page_size, query, label):
    observed = w.get_state(db, "release_observation:" + release)
    applied = applied_rows(db, release, observed)
    items = []
    rows = (
        applied
        if applied is not None
        else [
            {
                "issue_id": str(issue["issue_id"]),
                "issue_topic": str(issue.get("issue_topic") or ""),
                "source_result": issue.get("ra_merge_result"),
                "version_key": release,
                "road_version": str(issue.get("version", "")),
                "ra_type": issue.get("ra_type"),
                "issue_time": issue.get("issue_time"),
                "scenario_id": "",
                "scenario_name": "",
                "scenario_labels": [],
                "simulation_status": "collecting",
                "sim_triggered": None,
                "reproduced": None,
                "precision_label": None,
            }
            for issue in observed.get("issues", [])
        ]
    )
    needle = query.casefold()
    for row in rows:
        if (label and label not in row["scenario_labels"]) or (
            needle and not w._issue_row_matches_query(row, needle)
        ):
            continue
        items.append(row)
    items.sort(key=lambda r: (r["issue_time"] or 0, r["issue_id"]), reverse=True)
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "status": "ready" if applied is not None else "collecting" if observed else "pending",
        "synced_at": observed.get("observed_at"),
    }
