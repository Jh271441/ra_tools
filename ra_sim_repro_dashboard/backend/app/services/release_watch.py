"""Persisted last-Issue inactivity checks for each tracked road release.

Called under the workflow lock every hour. An unsuccessful/missed observation
cannot authorize submission. Recovery uses the last Issue time, without a new wait.
A release gets at most one automatic batch, even on failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re
import subprocess

from sqlalchemy import select

from app.models import ReleaseSimulationBatch, ReleaseWorkflowState
from app.services.release_cycle import BASE_FILTERS, TZ, digest, validate_period
from app.services.release_catalog import fetch_recent_releases
from app.services.release_source import complete_query, trail_credentials

QUIET_SECONDS = 24 * 3600
MAX_OBSERVATION_GAP_SECONDS = 3 * 3600
RULE = "issue_last_time_24h"
AUTOMATIC_RULES = {RULE, "issue_inactivity_24h"}


def validate_monitor_config(config):
    contract = config.get("contract", {})
    if not all(contract.get(k) for k in ("verified", "reference", "time_field")):
        raise ValueError("自动观察要求已核实的数易查询口径")
    if config.get("simulation", {}).get("acceptance_only"):
        raise ValueError("验收子集禁止开启自动仿真")


def release_key(row):
    match = re.fullmatch(r"(?:1\.)?(gen4-release-\d{8})(?:\.\d+)?", str(row.get("version", "")))
    if not match:
        raise ValueError("观察到无法识别的release版本")
    datetime.strptime(match[1][-8:], "%Y%m%d")
    return match[1]


def fetch_activity(config, release=None):
    """Discover in 60 days, then query the selected release without a time cutoff."""
    validate_monitor_config(config)
    if release is None:
        recent = fetch_recent_releases(config)
        if not recent:
            raise ValueError("最新release查询为空，不能视为周期结束")
        release = max(release_key(row) for row in recent)
    release_key({"version": release})
    attrs = [{**f, "val": [2, 3]} if f["attr_id"] == "ra_type" else f for f in BASE_FILTERS]
    app_id, token = trail_credentials()
    base = os.getenv("TRAIL_ISSUE_BASE_URL", "http://10.88.128.83").rstrip("/")
    rows = complete_query(
        base + "/paladin/issue/pool/query/",
        {"view_id": config["contract"].get("view_id", 2410), "user_location": "cn",
         "query_attrs": [*attrs, {"attr_id": "version", "operator": "like", "val": [release]}]},
        app_id, token, "issue_id",
    )
    if not rows or any(release_key(row) != release for row in rows):
        raise ValueError("最新release全量查询为空或版本不匹配")
    return release, rows


def activity_identity(rows, time_field):
    # Identity guards preparation/submission against concurrent Issue or label edits.
    values = [{k: row.get(k) for k in
               ("issue_id", time_field, "version", "ra_type", "ra_merge_result")}
              for row in rows]
    ids = [str(row.get("issue_id") or "") for row in rows]
    if not rows or any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("观察人口为空、重复或缺少Issue ID")
    return digest(sorted(values, key=lambda row: str(row["issue_id"])))


def observe(previous, release, rows, now, config):
    identity = activity_identity(rows, config["contract"]["time_field"])
    if previous.get("release", "") > release:
        raise ValueError("最新版本查询回退，保留原观察目标")
    if any(release_key(row) != release for row in rows):
        raise ValueError("观察人口混入其它release")
    times = [datetime.fromtimestamp(float(row[config["contract"]["time_field"]]) / 1000, timezone.utc)
             for row in rows]
    if max(times) > now:
        raise ValueError("Issue时间位于未来，不能证明静默窗口")
    # A successful full query supplies the latest Issue timestamp. Observation gaps
    # and label edits do not reset its age; weekends count as ordinary elapsed time.
    quiet_start = max(times)
    quiet_since = quiet_start.isoformat()
    elapsed = (now - quiet_start).total_seconds()
    return {
        "release": release, "status": "ready" if elapsed >= QUIET_SECONDS else "observing",
        "rule": RULE, "quiet_seconds_required": QUIET_SECONDS,
        "poll_interval_seconds": 3600, "max_observation_gap_seconds": MAX_OBSERVATION_GAP_SECONDS,
        "activity_hash": identity, "contract_hash": digest(config["contract"]),
        "issue_count": len(rows), "first_issue_at": min(times).isoformat(),
        "last_issue_at": max(times).isoformat(), "quiet_since": quiet_since,
        "quiet_seconds": int(elapsed), "eligible_at": (quiet_start + timedelta(seconds=QUIET_SECONDS)).isoformat(),
        "last_success_at": now.isoformat(), "checked_at": now.isoformat(),
    }


def make_period(state, rows, existing=None):
    start = datetime.fromisoformat(state["first_issue_at"]).astimezone(TZ)
    last = datetime.fromisoformat(state["last_issue_at"]).astimezone(TZ)
    period = {
        "release": state["release"], "status": "completed", "basis": "observed", "verified": True,
        "cycle_end": last.date().isoformat(),
        "case_start": start.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "case_end_exclusive": (last + timedelta(milliseconds=1)).isoformat(),
        "completion_rule": RULE, "quiet_since": state["quiet_since"],
        "observed_at": state["checked_at"], "last_issue_at": state["last_issue_at"],
        "activity_hash": state["activity_hash"],
        "road_versions": sorted({str(r["version"]) for r in rows}),
        "evidence": f"Trail全分页观察{state['issue_count']}条；最近Issue距查询时间已满24小时（含周末），最后Issue {state['last_issue_at']}",
    }
    # Retain an established full namespace; never invent a second cycle namespace.
    for key in ("scenario_creation_label", "scenario_query_labels", "scenario_query_label_sets"):
        if existing and key in existing:
            period[key] = existing[key]
    from ra_api.release_labels import full_scene_label
    period["scenario_creation_label"] = full_scene_label(period)
    period["scenario_query_labels"] = [period["scenario_creation_label"]]
    period.pop("scenario_query_label_sets", None)
    return validate_period(period, require_verified=True)


def monitor_tick(db, config, *, now=None, activity_fetcher=None, release=None, update_latest=True):
    from app.services import release_workflow as w
    supplied_now = now
    now = now or datetime.now(timezone.utc)
    fetch = activity_fetcher or (lambda c: fetch_activity(c, release))
    previous = w.get_state(db, "release_monitor:" + release) if release else w.get_state(db, "release_monitor")
    if release and not previous:
        legacy = w.get_state(db, "release_monitor")
        previous = legacy if legacy.get("release") == release else {"release": release}
    state = previous

    def save(value):
        if update_latest:
            w.put_state(db, "release_monitor", value)
        if value.get("release"):
            w.put_state(db, "release_monitor:" + value["release"], value)
        return value

    try:
        validate_monitor_config(config)
        fetched_release, rows = fetch(config)
        if release and fetched_release != release:
            raise ValueError("观察结果与目标release不匹配")
        release = fetched_release
        now = supplied_now or datetime.now(timezone.utc)
        state = observe(previous, release, rows, now, config)
    except Exception as exc:
        db.rollback()
        return save({**previous, "status": "source_error", "quiet_since": None,
                     "last_success_at": None, "checked_at": now.isoformat(),
                     "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})

    # Persist every successful observation before any potentially long side effect.
    # Separate read model for Issue browsing, never a simulation population/plan.
    w.put_state(db, "release_observation:" + release, {
        "release": release, "observed_at": now.isoformat(),
        "activity_hash": state["activity_hash"],
        "issues": [{k: row.get(k) for k in
                    ("issue_id", "issue_topic", "issue_time", "version", "ra_type", "ra_merge_result",
                     "trip_id", "ra_start_timestamp", "trip_start_time", "trip_end_time")}
                   for row in rows],
    })
    save(state)
    batches = db.scalars(select(ReleaseSimulationBatch).where(ReleaseSimulationBatch.release == release)).all()
    auto_queued = [b for b in batches if b.status == "queued" and b.payload.get("period", {}).get("completion_rule") in AUTOMATIC_RULES]
    other = [b for b in batches if b not in auto_queued
             and (b.payload.get("job_id") or b.status not in ("cancelled_stale", "preflight_failed"))]
    if other:
        return save({**state, "status": "already_submitted", "batches": [
            {"fingerprint": b.fingerprint, "status": b.status, "job_id": b.payload.get("job_id")}
            for b in other], "population_changed_after_submission": any(
                b.payload.get("period", {}).get("activity_hash") not in (None, state["activity_hash"]) for b in other)})
    if state["status"] != "ready":
        return state
    if w.get_state(db, "settings", {"mode": "manual"})["mode"] != "auto":
        return save({**state, "status": "ready_manual"})

    try:
        if len(auto_queued) > 1:
            raise ValueError("存在多个待提交批次，禁止自动选择")
        if auto_queued:
            period = {**auto_queued[0].payload["period"],
                      "scenario_creation_label": auto_queued[0].payload["scenario_label"],
                      "scenario_query_labels": [auto_queued[0].payload["scenario_label"]]}
            if period.get("activity_hash") != state["activity_hash"]:
                auto_queued[0].status = "cancelled_stale"
                db.commit()
                raise ValueError("已排队人口发生变化，保留审计并等待人工处理")
        else:
            existing = next((p for p in config.get("periods", []) if p["release"] == release), None)
            period = make_period(state, rows, existing)
            identity = w.driver_call(config, "lookup_binary", period)
            if not all(identity.get(k) for k in ("binary_id", "binary_commit", "binary_evidence")):
                raise ValueError("最新release未找到唯一有效的binary")
            period.update(identity)
            period["template_job_id"] = config.get("simulation", {}).get("template_job_id")
        target = {**config, "periods": [p for p in config.get("periods", []) if p["release"] != release] + [period]}
        snapshot = w.sync_once(db, target, release=release)
        if activity_identity(snapshot.payload["issues"], config["contract"]["time_field"]) != state["activity_hash"]:
            raise ValueError("同步人口与静默观察不一致，请重新观察")
        save({**state, "status": "preparing_scenes"})
        w.prepare_missing_scenes(db, target, release=release)
        # Recheck this release after preparation. A newer release must not starve it.
        final_release, final_rows = fetch(config)
        if final_release != release or activity_identity(final_rows, config["contract"]["time_field"]) != state["activity_hash"]:
            return save(observe(state, final_release, final_rows, supplied_now or datetime.now(timezone.utc), config))
        w.sync_once(db, target, release=release)
        plan = w.make_plan(db, target, release=release)
        if activity_identity(w.latest_snapshot(db, w.period_key(target, period)).payload["issues"],
                             config["contract"]["time_field"]) != state["activity_hash"]:
            raise ValueError("提交前人口发生变化，请重新观察")
        catalog = w.get_state(db, "catalog")
        w.put_state(db, "catalog", {**catalog, "periods": [p for p in catalog.get("periods", []) if p["release"] != release] + [period]})
        batch = w.queue_plan(db, plan["fingerprint"], target, release=release)
        save({**state, "status": "queued", "fingerprint": batch.fingerprint})
        batch = w.execute_batch(db, batch, target, release=release)
        return save({**state, "status": batch.status, "fingerprint": batch.fingerprint,
                     "job_id": batch.payload.get("job_id"), "error": batch.payload.get("error")})
    except Exception as exc:
        db.rollback()
        timeout = isinstance(exc, subprocess.TimeoutExpired)
        return save({**state, "status": "blocked", "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                     "error_code": "driver_timeout" if timeout else "scene_preparation_failed" if isinstance(exc, w.ScenePreparationError) else None,
                     "error_action": getattr(exc, "action", None) if timeout else None,
                     "preparation": getattr(exc, "preparation", None)})


def monitor_releases(db, config, *, now=None, discovery_fetcher=None, activity_fetcher=None):
    """Retain every observed target and discover intervening releases after downtime.

    The oldest persisted observer is the tracking boundary, so enabling this on an
    existing installation does not unexpectedly launch its entire historical archive.
    Each release keeps its own quiet window and submission receipts.
    """
    from app.services import release_workflow as w
    previous = w.get_state(db, "release_monitor")
    tracked = {row.payload["release"] for row in db.scalars(select(ReleaseWorkflowState).where(
        ReleaseWorkflowState.key.startswith("release_monitor:"))) if row.payload.get("release")}
    if previous.get("release"):
        tracked.add(previous["release"])
    latest = max(tracked) if tracked else None
    try:
        validate_monitor_config(config)
        discovered = {release_key(row) for row in (discovery_fetcher or fetch_recent_releases)(config)}
        if not discovered or (latest and max(discovered) < latest):
            raise ValueError("release发现为空或回退，保留各版本观察目标")
        latest = max(discovered)
        boundary = min(tracked) if tracked else latest
        tracked.update(release for release in discovered if release >= boundary)
        # Persist discovery before querying individual populations; a failed query
        # must not lose a release that falls out of the discovery window later.
        for release in tracked:
            if not w.get_state(db, "release_monitor:" + release):
                value = previous if previous.get("release") == release else {"release": release, "status": "observing"}
                w.put_state(db, "release_monitor:" + release, value)
        w.put_state(db, "release_monitor_discovery", {"checked_at": (now or datetime.now(timezone.utc)).isoformat(), "status": "complete"})
    except Exception as exc:
        db.rollback()
        w.put_state(db, "release_monitor_discovery", {"checked_at": (now or datetime.now(timezone.utc)).isoformat(),
                    "status": "source_error", "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
        if not tracked:
            return []
    results = []
    for release in sorted(tracked):
        fetch = (lambda c, target=release: activity_fetcher(c, target)) if activity_fetcher else None
        results.append(monitor_tick(db, config, now=now, activity_fetcher=fetch,
                                    release=release, update_latest=release == latest))
    return results
