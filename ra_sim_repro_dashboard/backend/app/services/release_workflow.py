"""Core release workflow primitives: snapshots, config, plans, batch execution, and driver calls.

High-level orchestration (status, list_issues, poll_batches, run_tick) lives in
`app.services.workflow_orchestrator` so this module remains strictly acyclic at Tier 4.2.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.domain.coverage import POLICY, assess, validate_frozen
from app.domain.cycle import TZ
from app.domain.hashing import population_identity as _population_identity
from app.domain.labels import (
    cohort_label_update,
    full_scene_label,
    scene_labels,
    validate_monitor_config,
    validate_physical_scene_labels,
    validate_scene_labels,
)
from app.models import (
    ReleaseIssueSnapshot,
    ReleaseSimulationBatch,
    ReleaseWorkflowState,
)
from app.repositories import state_store
from app.services import release_catalog
from app.services.release_cycle import (
    digest,
    load_cycle_config,
    query_contract,
    resolve_current,
    validate_period,
)
from app.services.release_metrics import (
    cohort_for_issue,
    excluded_issue,
)
from app.services.release_source import (
    artifact_source,
    cycle_scene_label,
    fetch_population,
    fetch_scenarios,
)

logger = logging.getLogger(__name__)


def period_key(config, period):
    return digest(
        {
            "period": period,
            "contract": config["contract"],
            "query": query_contract(config, period, True),
        }
    )


def population_identity(payload):
    return _population_identity(payload)


def latest_snapshot(db, key):
    return db.scalars(
        select(ReleaseIssueSnapshot)
        .where(ReleaseIssueSnapshot.period_hash == key)
        .order_by(ReleaseIssueSnapshot.id.desc())
        .limit(1)
    ).first()


def get_state(db, key, default=None):
    return state_store.get_routed_state(db, key, default)


def put_state(db, key, payload):
    state_store.put_routed_state(db, key, payload, commit=True)


def effective_config(db):
    base = load_cycle_config()
    known = {p["release"]: p for p in base.get("periods", [])}
    for observed in get_state(db, "catalog").get("periods", []):
        existing = known.get(observed["release"], {})
        if existing.get("verified") and existing.get("status") == "completed":
            continue
        known[observed["release"]] = {**existing, **observed}
    return {**base, "periods": list(known.values())}


def refresh_catalog(db, config):
    if not config.get("discover_cycles"):
        return
    now = datetime.now(TZ)
    week = (now.date() - timedelta(days=now.weekday())).isoformat()
    previous = get_state(db, "catalog")
    if previous.get("checked_week") == week:
        return
    if previous.get("attempt_week") == week and (
        previous.get("attempts", 0) >= 3 or now.timestamp() < previous.get("retry_after", 0)
    ):
        return
    attempts = previous.get("attempts", 0) + 1 if previous.get("attempt_week") == week else 1
    try:
        periods, warnings = release_catalog.infer_completed_cycles(
            release_catalog.fetch_recent_releases(config), config["contract"]["time_field"]
        )
        # A watcher-frozen population must keep its boundaries and identity;
        # later release transitions are only evidence for missing periods.
        frozen = {
            p["release"]
            for p in config.get("periods", [])
            if p.get("verified")
            and p.get("completion_rule") in {"issue_inactivity_24h", "issue_last_time_24h"}
        }
        periods = [p for p in periods if p["release"] not in frozen]
        for period in periods:
            if config.get("simulation", {}).get("driver_command"):
                try:
                    identity = driver_call(config, "lookup_binary", period)
                    if identity.get("binary_id") and identity.get("binary_commit"):
                        period.update(identity)
                        period["template_job_id"] = config["simulation"].get("template_job_id")
                except Exception:
                    logger.warning(
                        "lookup_binary failed for release=%s",
                        period.get("release"),
                        exc_info=True,
                    )
                    period["binary_lookup_status"] = "pending"
        stored = {p["release"]: p for p in previous.get("periods", [])}
        stored.update({p["release"]: p for p in periods})
        put_state(
            db,
            "catalog",
            {
                "checked_week": week,
                "attempt_week": week,
                "attempts": attempts,
                "periods": list(stored.values()),
                "warnings": warnings,
            },
        )
    except Exception as exc:
        logger.exception("refresh_catalog failed week=%s", week)
        put_state(
            db,
            "catalog",
            {
                **previous,
                "attempt_week": week,
                "attempts": attempts,
                "retry_after": now.timestamp() + 3600,
                "error": type(exc).__name__,
            },
        )


def simulation_period(config, release=None):
    """Explicit background targets do not wait for the dashboard's Monday switch."""
    if release is None:
        current = resolve_current(config)
        if current["status"] != "ready":
            raise ValueError(current["reason"])
        return current["current_period"]
    matches = [p for p in config.get("periods", []) if p["release"] == release]
    if len(matches) != 1:
        raise ValueError("自动仿真目标周期不唯一")
    return validate_period(matches[0], require_verified=True)


def apply_issue_exclusions(db, release, issues):
    """Apply explicit local evaluation decisions without changing source GT."""
    decisions = get_state(db, "issue_exclusions:" + release).get("items", [])
    by_id = {str(d["issue_id"]): d for d in decisions}
    if len(by_id) != len(decisions):
        raise ValueError("评测排除记录包含重复 Issue")
    rows = []
    for source in issues:
        row = {k: v for k, v in source.items() if k != "evaluation_exclusion"}
        decision = by_id.get(str(row["issue_id"]))
        if decision:
            if (
                decision.get("release") != release
                or not decision.get("reason")
                or not decision.get("approved_at")
                or decision.get("approved_by") != "user"
            ):
                raise ValueError("评测排除记录缺少明确授权")
            expected = decision.get("source", {})
            if set(expected) != {"version", "ra_type", "ra_merge_result"} or any(
                row.get(k) != value for k, value in expected.items()
            ):
                raise ValueError(f"{row['issue_id']} 源标注已变化，需重新核对排除记录")
            row["evaluation_exclusion"] = decision
        rows.append(row)
    if set(by_id) - {str(row["issue_id"]) for row in rows}:
        raise ValueError("评测排除 Issue 已不在当前人口中，需重新核对")
    return rows


def sync_once(
    db,
    config=None,
    population_fetcher=fetch_population,
    scenario_fetcher=fetch_scenarios,
    *,
    release=None,
):
    config = config if config is not None else effective_config(db)
    period = simulation_period(config, release)
    issues = population_fetcher(config, period)
    if not issues:
        raise ValueError("上游返回空周期人口，保留旧快照并等待核实")
    if len({str(i["issue_id"]) for i in issues}) != len(issues):
        raise ValueError("Issue ID 不唯一")
    issues = apply_issue_exclusions(db, period["release"], issues)
    mapping_error = ""
    try:
        scenarios = scenario_fetcher(period)
    except Exception:
        logger.exception("scenario mapping lookup failed for release=%s", period.get("release"))
        scenarios = []
        mapping_error = "场景映射查询失败，Issue 已同步，禁止提交仿真"
    ids = {str(i["issue_id"]) for i in issues}
    scenarios = [s for s in scenarios if s["issue_id"] in ids]
    if len({s["scenario_id"] for s in scenarios}) != len(scenarios):
        raise ValueError("场景 ID 不唯一")
    key = period_key(config, period)
    artifact = artifact_source(period)
    payload = {
        "period": period,
        "population_complete": artifact["complete"] if artifact is not None else True,
        "source_scope": artifact.get("scope", "full_period")
        if artifact is not None
        else "full_period",
        "collected_through": artifact.get("collected_through")
        if artifact is not None
        else period["case_end_exclusive"],
        "query_attrs": query_contract(config, period, True),
        "issues": issues,
        "scenarios": scenarios,
        "mapping_error": mapping_error,
    }
    previous = latest_snapshot(db, key)
    if previous and digest(previous.payload) == digest(payload):
        snapshot = previous
    else:
        snapshot = ReleaseIssueSnapshot(period_hash=key, release=period["release"], payload=payload)
        db.add(snapshot)
        db.commit()
    put_state(
        db,
        "sync",
        {
            "status": "complete",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_id": snapshot.id,
            "mapping_error": mapping_error,
        },
    )
    return snapshot


class ScenePreparationError(ValueError):
    def __init__(self, response):
        super().__init__("场景准备失败：" + str(response.get("error", "请查看失败清单")))
        self.preparation = {
            key: response[key] for key in ("prepared", "failed", "failures") if key in response
        }


def reconcile_preparation_labels(db, config, snapshot, *, release=None):
    """Synchronize changed GT cohorts before any external submission exists."""
    batches = db.scalars(
        select(ReleaseSimulationBatch).where(ReleaseSimulationBatch.release == snapshot.release)
    ).all()
    if any(
        b.payload.get("job_id")
        or b.status in ("submitting", "submission_uncertain", "running", "verifying")
        for b in batches
    ):
        return snapshot
    period = snapshot.payload["period"]
    label = full_scene_label(period)
    cohorts = {str(i["issue_id"]): cohort_for_issue(i) for i in snapshot.payload["issues"]}
    changes = []
    for scene in snapshot.payload["scenarios"]:
        cohort = cohorts.get(str(scene["issue_id"]))
        if not cohort:
            continue
        updated = cohort_label_update(scene, label, period["release"], cohort)
        if updated is not None:
            changes.append(
                {
                    **{
                        k: scene.get(k)
                        for k in (
                            "scenario_id",
                            "issue_id",
                            "scenario_revision",
                            "start_timestamp",
                            "end_timestamp",
                        )
                    },
                    "cohort": cohort,
                    "before_labels": sorted(scene_labels(scene)),
                    "after_labels": updated,
                }
            )
    if not changes:
        return snapshot
    payload = {
        "release": period["release"],
        "period": period,
        "label": label,
        "source_hash": population_identity(snapshot.payload),
        "changes": changes,
    }
    receipt = driver_call(config, "reconcile_labels", payload)
    if (
        receipt.get("ready") is not True
        or receipt.get("verified_count") != len(changes)
        or receipt.get("request_hash") != digest(payload)
    ):
        raise ValueError("Scenario cohort label synchronization failed")
    put_state(
        db,
        "scenario_labels:" + period["release"],
        {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_id": snapshot.id,
            "source_hash": payload["source_hash"],
            "scenario_ids": [c["scenario_id"] for c in changes],
            "count": len(changes),
            "request_hash": receipt["request_hash"],
            "audit_path": receipt.get("audit_path"),
        },
    )
    return sync_once(db, config, release=release)


def prepare_missing_scenes(db, config, *, release=None):
    """Automatic mode explicitly prepares the missing eligible source scenes."""
    period = simulation_period(config, release)
    validate_period(period, require_verified=True)
    snapshot = latest_snapshot(db, period_key(config, period))
    if not snapshot or not snapshot.payload.get("population_complete"):
        raise ValueError("完整人口尚未就绪")
    if snapshot.payload.get("mapping_error"):
        raise ValueError("场景查询失败，不能猜测缺失集合并创建")
    snapshot = reconcile_preparation_labels(db, config, snapshot, release=release)
    mapped = {s["issue_id"] for s in snapshot.payload["scenarios"]}
    missing = [
        i
        for i in snapshot.payload["issues"]
        if cohort_for_issue(i) and str(i["issue_id"]) not in mapped
    ]
    if not missing:
        return
    payload = {
        "period": period,
        "release": period["release"],
        "label": cycle_scene_label(period),
        "issues": [{**i, "cohort": cohort_for_issue(i)} for i in missing],
    }
    response = driver_call(config, "prepare_scenes", payload)
    # Keep successfully created scenes visible even if one source bag is missing.
    refreshed = sync_once(db, config, release=release)
    if response.get("ready") is not True:
        rows = refreshed.payload["issues"]
        eligible = {str(i["issue_id"]) for i in rows if cohort_for_issue(i)}
        remaining = eligible - {str(s["issue_id"]) for s in refreshed.payload["scenarios"]}
        failures = response.get("failures") or []
        failed_ids = [str(f.get("issue_id", "")) for f in failures]
        # Only a complete, explicit failure receipt and a successful full requery
        # can authorize exceptions. Timeouts and incomplete mappings still block.
        if (
            refreshed.payload.get("mapping_error")
            or not remaining
            or type(response.get("failed")) is not int
            or response["failed"] != len(failures)
            or len(set(failed_ids)) != len(failures)
            or set(failed_ids) != remaining
            or not remaining <= {str(i["issue_id"]) for i in missing}
            or any(f.get("reason") not in ("missing_bag", "upstream_error") for f in failures)
        ):
            raise ScenePreparationError(response)
        try:
            assess(eligible, remaining)
        except ValueError:
            raise ScenePreparationError(response) from None
        put_state(
            db,
            "preparation_tolerance:" + period["release"],
            {
                "population_hash": population_identity(refreshed.payload),
                "failures": sorted(failures, key=lambda f: str(f["issue_id"])),
            },
        )


def _issue_row_matches_query(row: dict, needle: str) -> bool:
    for field in (
        "issue_id",
        "issue_topic",
        "scenario_id",
        "scenario_name",
        "version",
        "ra_merge_result",
        "source_result",
        "simulation_status",
        "job_id",
        "trip_id",
        "precision_label",
        "root_cause",
    ):
        val = row.get(field)
        if val is not None and needle in str(val).casefold():
            return True
    labels = row.get("scenario_labels")
    if isinstance(labels, list) and any(needle in str(item).casefold() for item in labels):
        return True
    return False


def execution_overrides(config, release):
    """Freeze explicit execution policy identically for main and sidecar plans."""
    sim = config.get("simulation", {})
    result = {}
    warmup = sim.get("warmup_ms_by_release", {}).get(release, sim.get("warmup_ms"))
    if warmup is not None:
        if type(warmup) is not int or not 0 <= warmup <= 60000:
            raise ValueError("simulation_warmup_invalid")
        result["warmup_ms"] = warmup
    history = sim.get("feature_history_by_release", {}).get(release, sim.get("feature_history"))
    if history is not None:
        if history != "release-native":
            raise ValueError("simulation_feature_history_invalid")
        result["feature_history"] = history
    return result


def make_plan(db, config=None, *, release=None):
    config = config if config is not None else effective_config(db)
    period = simulation_period(config, release)
    snapshot = latest_snapshot(db, period_key(config, period))
    if not snapshot:
        raise ValueError("请先完整同步当前周期 Issue")
    if snapshot.payload.get("mapping_error"):
        raise ValueError(snapshot.payload["mapping_error"])
    validate_period(period, require_verified=True)
    physical = period.get("execution_schema") == "physical_v2"
    if not snapshot.payload.get("population_complete", False):
        raise ValueError("当前周期人口尚未完整采集，不能提交全量仿真")
    if snapshot.payload.get("source_scope") == "acceptance_subset" and not config.get(
        "simulation", {}
    ).get("acceptance_only"):
        raise ValueError("验收子集不能作为正式全量人口提交")
    cohorts = {str(i["issue_id"]): cohort_for_issue(i) for i in snapshot.payload["issues"]}
    unknown = [
        i
        for i in snapshot.payload["issues"]
        if cohorts[str(i["issue_id"])] is None and not excluded_issue(i)
    ]
    if unknown:
        raise ValueError(f"{len(unknown)} 个 Issue 的 GT 尚未明确，不能发布完整准召")
    scenarios = [
        {
            **{
                k: s.get(k)
                for k in (
                    "scenario_id",
                    "issue_id",
                    "scenario_revision",
                    "start_timestamp",
                    "end_timestamp",
                )
            },
            "cohort": (
                "source_manual" if cohorts[s["issue_id"]] == "positive_manual" else "source_auto"
            )
            if physical
            else cohorts[s["issue_id"]],
        }
        for s in snapshot.payload["scenarios"]
        if cohorts.get(s["issue_id"])
    ]
    mapped = {s["issue_id"] for s in scenarios}
    missing = {iid for iid, cohort in cohorts.items() if cohort} - mapped
    preparation = get_state(db, "preparation_tolerance:" + period["release"])
    failures = preparation.get("failures", []) if missing else []
    if missing and (
        preparation.get("population_hash") != population_identity(snapshot.payload)
        or {str(f["issue_id"]) for f in failures} != missing
    ):
        raise ValueError(f"{len(missing)} 个 Issue 尚未匹配场景，暂不提交全量仿真")
    eligible_ids = sorted(iid for iid, cohort in cohorts.items() if cohort)
    assess(eligible_ids, missing)
    sim = config.get("simulation", {})
    max_concurrency = sim.get("max_concurrency", 1)
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 1000:
        raise ValueError("并发上限必须是 1 到 1000 的整数")
    priority = sim.get("priorities_by_release", {}).get(
        period["release"], sim.get("priority", "NORMAL")
    )
    if priority not in ("NORMAL", "HIGH"):
        raise ValueError("提交优先级必须是 NORMAL 或 HIGH")
    if not period.get("binary_id") or not period.get("template_job_id"):
        raise ValueError("当前 release 缺少已核实的 binary 和任务模板")
    scenario_label = full_scene_label(period)
    for scene in snapshot.payload["scenarios"]:
        cohort = cohorts.get(scene["issue_id"])
        if cohort:
            if physical:
                validate_physical_scene_labels(
                    scene,
                    scenario_label,
                    period["release"],
                    "source_manual" if cohort == "positive_manual" else "source_auto",
                )
            else:
                validate_scene_labels(scene, scenario_label, period["release"], cohort)
    body = {
        "scenario_label": scenario_label,
        "period": {
            k: period.get(k)
            for k in (
                "release",
                "status",
                "basis",
                "verified",
                "cycle_end",
                "case_start",
                "case_end_exclusive",
                "evidence",
                "binary_id",
                "template_job_id",
                "target_road_version",
                "binary_commit",
                "binary_evidence",
                "completion_rule",
                "activity_hash",
                "quiet_since",
                "observed_at",
                "last_issue_at",
                "execution_schema",
            )
            if k
            not in (
                "completion_rule",
                "activity_hash",
                "quiet_since",
                "observed_at",
                "last_issue_at",
                "execution_schema",
            )
            or k in period
        },
        "release": period["release"],
        "binary_id": period["binary_id"],
        "template_job_id": period["template_job_id"],
        "population_hash": population_identity(snapshot.payload),
        "query_attrs": snapshot.payload["query_attrs"],
        "scenarios": sorted(scenarios, key=lambda s: s["scenario_id"]),
        "simulation": {
            "cluster": "prod_gen4",
            "max_concurrency": max_concurrency,
            "priority": priority,
            "cache": "disabled",
            "recovery_mode": sim.get("recovery_mode", "baseline"),
            "dpe": True,
            **execution_overrides(config, period["release"]),
        },
        "issues": [
            {
                **{k: i.get(k) for k in ("issue_id", "ra_type", "ra_merge_result")},
                **(
                    {"evaluation_exclusion": i["evaluation_exclusion"]}
                    if i.get("evaluation_exclusion")
                    else {}
                ),
            }
            for i in snapshot.payload["issues"]
        ],
        "driver_revision": sim.get("driver_revision"),
        "acceptance_only": bool(sim.get("acceptance_only", False)),
        **({"execution_schema": "physical_v2"} if physical else {}),
    }
    for issue in body["issues"]:
        failure = next((f for f in failures if str(f["issue_id"]) == str(issue["issue_id"])), None)
        if failure:
            issue["evaluation_exclusion"] = {
                "approved_by": POLICY["version"],
                "reason": failure["reason"],
                "stage": "preparation",
            }
    body["issue_tolerance"] = {
        "policy": dict(POLICY),
        "population_hash": body["population_hash"],
        "eligible_issue_ids": eligible_ids,
        "preparation_failures": failures,
    }
    validate_frozen(body)
    return {**body, "fingerprint": digest(body)}


def driver_call(config, action, payload):
    command = config.get("simulation", {}).get("driver_command")
    if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
        raise ValueError("新版本 Orion 提交与结果校验驱动尚未配置")
    # Scene creation can upload thousands of Issues through four workers. Keep
    # its batch budget separate from the short submit/lookup request budget.
    timeout = 1800 if action == "prepare_scenes" else 600 if action == "poll" else 120
    try:
        response = subprocess.run(
            command,
            input=json.dumps({"action": action, "payload": payload}),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("Orion driver action=%s timed out after %ss", action, timeout)
        exc.action = action
        raise
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "")[-2000:].strip()
        logger.error(
            "Orion driver action=%s failed rc=%s stderr=%s",
            action,
            exc.returncode,
            stderr_tail,
        )
        raise
    return json.loads(response.stdout)


def _driver_preflight(config, plan):
    check = driver_call(config, "preflight", plan)
    if check.get("fingerprint") != plan["fingerprint"] or check.get("ready") is not True:
        raise ValueError("Orion 预检未通过：" + str(check.get("error", "配置与计划不一致")))
    return check


def evaluation_execution_active(db, release):
    # Some authorized/offline submitters persist an execution without evstart.
    # Its durable intent must protect the same shared lane after a restart.
    if state_store.count_active_executions(db, release=release) > 0:
        return True
    for row in db.scalars(
        select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith("evstart:"))
    ):
        value = row.payload
        if (
            value.get("status") in state_store.ACTIVE_EXECUTION_STATUSES
            and value.get("context", {}).get("release") == release
        ):
            execution = state_store.get_execution(
                db, value.get("execution_id", ""), include_heavy=False
            )
            if not execution or execution.get("status") in state_store.ACTIVE_EXECUTION_STATUSES:
                return True
    return False


def queue_plan(db, fingerprint, config=None, *, release=None):
    config = config if config is not None else effective_config(db)
    plan = make_plan(db, config, release=release)
    if plan["fingerprint"] != fingerprint:
        raise ValueError("周期、人口或任务配置已变化，请重新预览")
    existing = db.get(ReleaseSimulationBatch, fingerprint)
    if existing:
        return existing
    # Share physical execution with independent evaluation profiles.
    if evaluation_execution_active(db, plan["release"]):
        raise ValueError(
            "AutoTriage physical execution is active; wait before preparing another batch"
        )
    active = db.scalars(
        select(ReleaseSimulationBatch).where(
            ReleaseSimulationBatch.release == plan["release"],
            ReleaseSimulationBatch.status.in_(
                ["queued", "submitting", "submission_uncertain", "running", "verifying"]
            ),
        )
    ).all()
    if any(b.payload.get("binary_id") == plan["binary_id"] for b in active):
        raise ValueError("该 release/binary 已有活动批次，待其完成后再更新人口")
    if not config.get("simulation", {}).get("driver_command"):
        raise ValueError("Orion 驱动尚未配置")
    batch = ReleaseSimulationBatch(
        fingerprint=fingerprint, release=plan["release"], status="queued", payload=plan
    )
    db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.get(ReleaseSimulationBatch, fingerprint)
    return batch


def attach_job(db, fingerprint, job_id):
    config = effective_config(db)
    plan = make_plan(db, config)
    if fingerprint != plan["fingerprint"] or int(job_id) <= 0:
        raise ValueError("计划已变化或 Job ID 无效")
    if not config.get("simulation", {}).get("driver_command"):
        raise ValueError("Orion 核验驱动尚未配置")
    existing = db.get(ReleaseSimulationBatch, fingerprint)
    if existing:
        if str(existing.payload.get("job_id")) != str(job_id):
            raise ValueError("该计划已有其它 Job，不能覆盖回执")
        return existing
    batch = ReleaseSimulationBatch(
        fingerprint=fingerprint,
        release=plan["release"],
        status="verifying",
        payload={**plan, "job_id": int(job_id), "attached_job": True},
    )
    db.add(batch)
    db.commit()
    return batch


def execute_batch(db, batch, config, *, release=None, delta_validator=None):
    if batch.status != "queued":
        return batch
    if evaluation_execution_active(db, batch.release):
        return batch  # Retain queued work until the shared execution lane is free.
    if batch.payload.get("backfill", {}).get("kind") == "label_changes" and (
        get_state(db, "settings", {"mode": "manual"}).get("mode") != "auto"
        or config.get("result_publication", {}).get("enabled", True) is not True
    ):
        return batch
    if batch.payload.get("backfill"):
        if delta_validator is None:
            raise ValueError("delta_validator_required")
        delta_validator(db, batch, config)
        current_plan = batch.payload
    else:
        current_plan = make_plan(db, config, release=release)
    if current_plan["fingerprint"] != batch.fingerprint:
        batch.status = "cancelled_stale"
        db.commit()
        return batch
    # Phase 1: short DB validation before external driver preflight (no open write tx)
    payload_snapshot = dict(batch.payload)
    db.commit()
    try:
        _driver_preflight(config, payload_snapshot)
    except Exception as exc:
        logger.warning(
            "execute_batch preflight failed batch=%s release=%s",
            batch.fingerprint,
            batch.release,
            exc_info=True,
        )
        batch.status = "preflight_failed"
        batch.payload = {
            **batch.payload,
            "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
        }
        db.commit()
        return batch
    # Phase 2: persist submitting intent & close transaction before subprocess side effect
    batch.status = "submitting"
    db.commit()  # Persist before side effect. A restart never relaunches submitting.
    # Phase 3: lockless external submit, followed by short receipt commit
    try:
        receipt = driver_call(config, "submit", payload_snapshot)
        if receipt.get("fingerprint") != batch.fingerprint or not receipt.get("job_id"):
            raise ValueError("提交回执不完整")
        batch.payload = {**batch.payload, "job_id": receipt["job_id"]}
        batch.status = "running"
    except Exception:
        logger.exception(
            "execute_batch submission uncertain batch=%s release=%s",
            batch.fingerprint,
            batch.release,
        )
        batch.status = "submission_uncertain"
    db.commit()
    return batch


def submit_plan(db, fingerprint, config=None):
    """Synchronous service entry, also used by scheduler and regression tests."""
    config = config if config is not None else effective_config(db)
    batch = queue_plan(db, fingerprint, config)
    return execute_batch(db, batch, config)


def set_mode(db, mode):
    if mode not in ("manual", "auto"):
        raise ValueError("无效的仿真模式")
    if mode == "auto":
        config = effective_config(db)
        if config.get("release_monitor", {}).get("enabled"):
            validate_monitor_config(config)
            if not config.get("simulation", {}).get("driver_command"):
                raise ValueError("Orion 驱动尚未配置")
        else:
            plan = make_plan(db, config)
            _driver_preflight(config, plan)
        if os.getenv("RELEASE_WORKFLOW_ENABLED") != "1":
            raise ValueError("服务端定时调度尚未启用")
    put_state(db, "settings", {"mode": mode})
