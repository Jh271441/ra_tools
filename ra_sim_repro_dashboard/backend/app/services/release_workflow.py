from __future__ import annotations

import fcntl
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.config import DATA_DIR
from app.database import SessionLocal
from app.models import (
    ReleaseIssueSnapshot,
    ReleaseWorkflowState,
    ReleaseSimulationBatch,
)
from app.services.release_cycle import (
    digest,
    load_cycle_config,
    query_contract,
    resolve_current,
    validate_period,
)
from app.services.release_metrics import (
    cohort_for_issue,
    summarize_population,
    excluded_issue,
)
from app.services.release_source import fetch_population, fetch_scenarios


def period_key(config, period):
    return digest(
        {
            "period": period,
            "contract": config["contract"],
            "query": query_contract(config, period, True),
        }
    )


def population_identity(payload):
    period = payload["period"]
    issues = [
        {
            **{k: row.get(k) for k in
               ("issue_id", "ra_type", "ra_merge_result", "issue_time", "version")},
            **({"evaluation_exclusion": row["evaluation_exclusion"]}
               if row.get("evaluation_exclusion") else {}),
        }
        for row in payload["issues"]
    ]
    scenarios = [
        {
            k: row.get(k)
            for k in (
                "scenario_id",
                "issue_id",
                "scenario_revision",
                "start_timestamp",
                "end_timestamp",
            )
        }
        for row in payload["scenarios"]
    ]
    return digest(
        {
            "period": {
                k: period.get(k)
                for k in ("release", "case_start", "case_end_exclusive", "binary_id")
            },
            "issues": sorted(issues, key=lambda row: str(row["issue_id"])),
            "scenarios": sorted(scenarios, key=lambda row: str(row["scenario_id"])),
        }
    )


def latest_snapshot(db, key):
    return db.scalars(
        select(ReleaseIssueSnapshot)
        .where(ReleaseIssueSnapshot.period_hash == key)
        .order_by(ReleaseIssueSnapshot.id.desc())
        .limit(1)
    ).first()


def get_state(db, key, default=None):
    row = db.get(ReleaseWorkflowState, key)
    return row.payload if row else (default or {})


def put_state(db, key, payload):
    row = db.get(ReleaseWorkflowState, key) or ReleaseWorkflowState(key=key)
    row.payload = payload
    db.add(row)
    db.commit()


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
    from app.services.release_catalog import (
        fetch_recent_releases,
        infer_completed_cycles,
    )
    from app.services.release_cycle import TZ

    now = datetime.now(TZ)
    week = (now.date() - timedelta(days=now.weekday())).isoformat()
    previous = get_state(db, "catalog")
    if previous.get("checked_week") == week:
        return
    if previous.get("attempt_week") == week and (
        previous.get("attempts", 0) >= 3
        or now.timestamp() < previous.get("retry_after", 0)
    ):
        return
    attempts = (
        previous.get("attempts", 0) + 1 if previous.get("attempt_week") == week else 1
    )
    try:
        periods, warnings = infer_completed_cycles(
            fetch_recent_releases(config), config["contract"]["time_field"]
        )
        # A watcher-frozen population must keep its boundaries and identity;
        # later release transitions are only evidence for missing periods.
        frozen = {
            p["release"] for p in config.get("periods", [])
            if p.get("verified") and p.get("completion_rule") in {"issue_inactivity_24h", "issue_last_time_24h"}
        }
        periods = [p for p in periods if p["release"] not in frozen]
        for period in periods:
            if config.get("simulation", {}).get("driver_command"):
                try:
                    identity = driver_call(config, "lookup_binary", period)
                    if identity.get("binary_id") and identity.get("binary_commit"):
                        period.update(identity)
                        period["template_job_id"] = config["simulation"].get(
                            "template_job_id"
                        )
                except Exception:
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


def status(db, config=None):
    config = config if config is not None else effective_config(db)
    result = resolve_current(config)
    period = result["current_period"]
    snapshot = latest_snapshot(db, period_key(config, period)) if period else None
    driver_ready = bool(config.get("simulation", {}).get("driver_command"))
    return {
        **result,
        "mode": get_state(db, "settings", {"mode": "manual"})["mode"],
        "driver_ready": driver_ready,
        "scheduler_enabled": os.getenv("RELEASE_WORKFLOW_ENABLED") == "1",
        "last_sync": get_state(db, "sync"),
        "release_monitor": get_state(db, "release_monitor"),
        "snapshot_id": snapshot.id if snapshot else None,
        "population_complete": snapshot.payload.get("population_complete", False)
        if snapshot
        else False,
        "collected_through": snapshot.payload.get("collected_through")
        if snapshot
        else None,
        "acceptance_only": bool(
            config.get("simulation", {}).get("acceptance_only", False)
        ),
        "metrics": metrics_for_snapshot(db, snapshot),
        "source_metrics": summarize_population(snapshot.payload["issues"], [], {})
        if snapshot
        else None,
        "synced_at": snapshot.created_at.replace(tzinfo=timezone.utc).isoformat()
        if snapshot
        else None,
        "issue_count": sum(int(i["ra_type"]) == 2 for i in snapshot.payload["issues"])
        if snapshot
        else 0,
        "manual_population_count": sum(
            int(i["ra_type"]) == 3 for i in snapshot.payload["issues"]
        )
        if snapshot
        else 0,
        "scenario_count": len(snapshot.payload["scenarios"]) if snapshot else 0,
        "periods": [
            {
                "release": p.get("release"),
                "cycle_end": p.get("cycle_end"),
                "verified": p.get("verified", False),
                "basis": p.get("basis"),
                "status": p.get("status"),
            }
            for p in config.get("periods", [])
        ],
        "batches": [
            {
                "fingerprint": b.fingerprint,
                "release": b.release,
                "status": b.status,
                "job_id": b.payload.get("job_id"),
                "scenario_count": len(b.payload.get("scenarios", [])),
            }
            for b in db.scalars(
                select(ReleaseSimulationBatch)
                .order_by(ReleaseSimulationBatch.created_at.desc())
                .limit(20)
            )
        ],
    }


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
            if (decision.get("release") != release or not decision.get("reason")
                    or not decision.get("approved_at") or decision.get("approved_by") != "user"):
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
        scenarios = []
        mapping_error = "场景映射查询失败，Issue 已同步，禁止提交仿真"
    ids = {str(i["issue_id"]) for i in issues}
    scenarios = [s for s in scenarios if s["issue_id"] in ids]
    if len({s["scenario_id"] for s in scenarios}) != len(scenarios):
        raise ValueError("场景 ID 不唯一")
    key = period_key(config, period)
    from app.services.release_source import artifact_source

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
        snapshot = ReleaseIssueSnapshot(
            period_hash=key, release=period["release"], payload=payload
        )
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
        self.preparation = {key: response[key] for key in ("prepared", "failed", "failures") if key in response}


def reconcile_preparation_labels(db, config, snapshot, *, release=None):
    """Synchronize changed GT cohorts before any external submission exists."""
    batches = db.scalars(select(ReleaseSimulationBatch).where(
        ReleaseSimulationBatch.release == snapshot.release)).all()
    if any(b.payload.get('job_id') or b.status in ('submitting', 'submission_uncertain', 'running', 'verifying') for b in batches):
        return snapshot
    from ra_api.release_labels import full_scene_label, cohort_label_update, scene_labels

    period = snapshot.payload['period']
    label = full_scene_label(period)
    cohorts = {str(i['issue_id']): cohort_for_issue(i) for i in snapshot.payload['issues']}
    changes = []
    for scene in snapshot.payload['scenarios']:
        cohort = cohorts.get(str(scene['issue_id']))
        if not cohort:
            continue
        updated = cohort_label_update(scene, label, period['release'], cohort)
        if updated is not None:
            changes.append({**{k:scene.get(k) for k in ('scenario_id', 'issue_id', 'scenario_revision', 'start_timestamp', 'end_timestamp')},
                'cohort':cohort, 'before_labels':sorted(scene_labels(scene)), 'after_labels':updated})
    if not changes:
        return snapshot
    payload = {'release':period['release'], 'period':period, 'label':label,
        'source_hash':population_identity(snapshot.payload), 'changes':changes}
    receipt = driver_call(config, 'reconcile_labels', payload)
    if receipt.get('ready') is not True or receipt.get('verified_count') != len(changes) or receipt.get('request_hash') != digest(payload):
        raise ValueError('Scenario cohort label synchronization failed')
    put_state(db, 'scenario_labels:' + period['release'], {
        'checked_at':datetime.now(timezone.utc).isoformat(), 'snapshot_id':snapshot.id,
        'source_hash':payload['source_hash'], 'scenario_ids':[c['scenario_id'] for c in changes],
        'count':len(changes), 'request_hash':receipt['request_hash'], 'audit_path':receipt.get('audit_path')})
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
    from app.services.release_source import cycle_scene_label

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
        from ra_api.release_tolerance import assess
        rows = refreshed.payload["issues"]
        eligible = {str(i["issue_id"]) for i in rows if cohort_for_issue(i)}
        remaining = eligible - {str(s["issue_id"]) for s in refreshed.payload["scenarios"]}
        failures = response.get("failures") or []
        failed_ids = [str(f.get("issue_id", "")) for f in failures]
        # Only a complete, explicit failure receipt and a successful full requery
        # can authorize exceptions. Timeouts and incomplete mappings still block.
        if (refreshed.payload.get("mapping_error") or not remaining
                or type(response.get("failed")) is not int
                or response["failed"] != len(failures) or len(set(failed_ids)) != len(failures)
                or set(failed_ids) != remaining
                or not remaining <= {str(i["issue_id"]) for i in missing}
                or any(f.get("reason") not in ("missing_bag", "upstream_error") for f in failures)):
            raise ScenePreparationError(response)
        try:
            assess(eligible, remaining)
        except ValueError:
            raise ScenePreparationError(response) from None
        put_state(db, "preparation_tolerance:" + period["release"], {
            "population_hash": population_identity(refreshed.payload),
            "failures": sorted(failures, key=lambda f: str(f["issue_id"])),
        })


def list_issues(db, release=None, page=1, page_size=25, query="", label=""):
    config = effective_config(db)
    from app.services.release_inventory import inventory, observation_issues
    catalog = inventory(db, config)
    if release == "@stable":
        release = catalog["default_release"]
        if not release:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "status": "pending"}
    selected = next((v for v in catalog["versions"] if v["release"] == release), None)
    if selected and selected["source"] == "observation":
        return observation_issues(db, release, page, page_size, query, label)
    current = resolve_current(config)
    if release in (None, "", "@current"):
        period = current["current_period"]
    else:
        candidates = [
            p
            for p in config.get("periods", [])
            if p.get("release") == release
            and p.get("status") == "completed"
            and (p.get("verified") or p.get("basis") == "inferred")
        ]
        period = candidates[0] if len(candidates) == 1 else None
    snapshot = latest_snapshot(db, period_key(config, period)) if period else None
    if snapshot is None:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "status": current["status"],
        }
    scenarios = snapshot.payload["scenarios"]
    scenes_by_issue = {}
    for scene in scenarios:
        scenes_by_issue.setdefault(scene["issue_id"], []).append(scene)
    batches = db.scalars(
        select(ReleaseSimulationBatch)
        .where(ReleaseSimulationBatch.release == snapshot.release)
        .order_by(ReleaseSimulationBatch.updated_at)
    ).all()
    population_hash = population_identity(snapshot.payload)
    batch_by_scene = {}
    batches.sort(key=lambda b: bool(b.payload.get("result_import", {}).get("primary")))
    from app.services.release_backfill import frozen_snapshot_valid
    for batch in batches:
        if batch.payload.get("population_hash") == population_hash or frozen_snapshot_valid(db, batch):
            for scene in batch.payload.get("scenarios", []):
                previous = batch_by_scene.get(scene["scenario_id"])
                if not previous or scene["scenario_id"] not in previous.payload.get("results", {}):
                    batch_by_scene[scene["scenario_id"]] = batch
    items = []
    for issue in snapshot.payload["issues"]:
        if int(issue["ra_type"]) != 2:
            continue
        mapped = scenes_by_issue.get(str(issue["issue_id"]), [])
        for scenario in mapped or [None]:
            row = {
                "issue_id": str(issue["issue_id"]),
                "issue_topic": str(issue.get("issue_topic") or ""),
                "source_result": issue.get("ra_merge_result"),
                "version_key": snapshot.release,
                "road_version": str(issue.get("version", "")),
                "scenario_id": scenario["scenario_id"] if scenario else "",
                "scenario_name": scenario.get("scenario_name", "") if scenario else "",
                "scenario_labels": scenario["scenario_labels"] if scenario else [],
                "simulation_status": "excluded"
                if excluded_issue(issue)
                else "pending_gt"
                if cohort_for_issue(issue) is None
                else "pending_simulation"
                if scenario
                else "pending_mapping",
                "sim_triggered": None,
                "reproduced": None,
                "precision_label": None,
            }
            # A result from another population/config cannot silently evaluate this snapshot.
            batch = batch_by_scene.get(row["scenario_id"])
            if batch:
                row["simulation_status"] = batch.status
                result = batch.payload.get("results", {}).get(row["scenario_id"])
                imported = batch.payload.get("result_import", {}).get("primary", False)
                detail = (
                    batch.payload.get("scenario_results", {}).get(
                        row["scenario_id"], {}
                    )
                    if imported
                    else {}
                )
                if detail:
                    row.update(
                        simulation_status=detail["status"],
                        job_id=detail["job_id"],
                        result_note=(
                            str(detail.get("outcome") or "")
                            + "\n"
                            + str(detail.get("outcome_detail") or "")
                        )
                        if detail.get("errors")
                        else "两次执行触发结果不一致"
                        if detail.get("conflict")
                        else "",
                        execution_conflict=detail.get("conflict", False),
                    )
                if (batch.status == "complete" or imported) and result:
                    row.update(
                        {
                            k: result.get(k)
                            for k in ("sim_triggered", "reproduced", "precision_label")
                        }
                    )
            if (
                query
                and query.lower() not in json.dumps(row, ensure_ascii=False).lower()
            ):
                continue
            if label and label not in row["scenario_labels"]:
                continue
            items.append(row)
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "status": "ready",
    }


def make_plan(db, config=None, *, release=None):
    config = config if config is not None else effective_config(db)
    period = simulation_period(config, release)
    snapshot = latest_snapshot(db, period_key(config, period))
    if not snapshot:
        raise ValueError("请先完整同步当前周期 Issue")
    if snapshot.payload.get("mapping_error"):
        raise ValueError(snapshot.payload["mapping_error"])
    validate_period(period, require_verified=True)
    if not snapshot.payload.get("population_complete", False):
        raise ValueError("当前周期人口尚未完整采集，不能提交全量仿真")
    if snapshot.payload.get("source_scope") == "acceptance_subset" and not config.get(
        "simulation", {}
    ).get("acceptance_only"):
        raise ValueError("验收子集不能作为正式全量人口提交")
    cohorts = {
        str(i["issue_id"]): cohort_for_issue(i) for i in snapshot.payload["issues"]
    }
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
            "cohort": cohorts[s["issue_id"]],
        }
        for s in snapshot.payload["scenarios"]
        if cohorts.get(s["issue_id"])
    ]
    mapped = {s["issue_id"] for s in scenarios}
    missing = {iid for iid, cohort in cohorts.items() if cohort} - mapped
    from ra_api.release_tolerance import POLICY, assess, validate_frozen
    preparation = get_state(db, "preparation_tolerance:" + period["release"])
    failures = preparation.get("failures", []) if missing else []
    if missing and (preparation.get("population_hash") != population_identity(snapshot.payload)
                    or {str(f["issue_id"]) for f in failures} != missing):
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
    from ra_api.release_labels import full_scene_label, validate_scene_labels

    scenario_label = full_scene_label(period)
    for scene in snapshot.payload['scenarios']:
        cohort = cohorts.get(scene['issue_id'])
        if cohort:
            validate_scene_labels(scene, scenario_label, period['release'], cohort)
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
            )
            if k not in ("completion_rule", "activity_hash", "quiet_since", "observed_at", "last_issue_at") or k in period
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
        },
        "issues": [
            {**{k: i.get(k) for k in ("issue_id", "ra_type", "ra_merge_result")},
             **({"evaluation_exclusion": i["evaluation_exclusion"]}
                if i.get("evaluation_exclusion") else {})}
            for i in snapshot.payload["issues"]
        ],
        "driver_revision": sim.get("driver_revision"),
        "acceptance_only": bool(sim.get("acceptance_only", False)),
    }
    for issue in body["issues"]:
        failure = next((f for f in failures if str(f["issue_id"]) == str(issue["issue_id"])), None)
        if failure:
            issue["evaluation_exclusion"] = {"approved_by": POLICY["version"],
                "reason": failure["reason"], "stage": "preparation"}
    body["issue_tolerance"] = {"policy": dict(POLICY),
        "population_hash": body["population_hash"], "eligible_issue_ids": eligible_ids,
        "preparation_failures": failures}
    validate_frozen(body)
    return {**body, "fingerprint": digest(body)}


def driver_call(config, action, payload):
    command = config.get("simulation", {}).get("driver_command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(v, str) for v in command)
    ):
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
        exc.action = action
        raise
    return json.loads(response.stdout)


def _driver_preflight(config, plan):
    check = driver_call(config, "preflight", plan)
    if (
        check.get("fingerprint") != plan["fingerprint"]
        or check.get("ready") is not True
    ):
        raise ValueError(
            "Orion 预检未通过：" + str(check.get("error", "配置与计划不一致"))
        )
    return check


def queue_plan(db, fingerprint, config=None, *, release=None):
    config = config if config is not None else effective_config(db)
    plan = make_plan(db, config, release=release)
    if plan["fingerprint"] != fingerprint:
        raise ValueError("周期、人口或任务配置已变化，请重新预览")
    existing = db.get(ReleaseSimulationBatch, fingerprint)
    if existing:
        return existing
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


def execute_batch(db, batch, config, *, release=None):
    if batch.status != "queued":
        return batch
    if batch.payload.get("backfill"):
        from app.services.release_backfill import validate_delta
        validate_delta(db, batch, config)
        current_plan = batch.payload
    else:
        current_plan = make_plan(db, config, release=release)
    if current_plan["fingerprint"] != batch.fingerprint:
        batch.status = "cancelled_stale"
        db.commit()
        return batch
    try:
        _driver_preflight(config, batch.payload)
    except Exception as exc:
        batch.status = "preflight_failed"
        batch.payload = {
            **batch.payload,
            "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
        }
        db.commit()
        return batch
    batch.status = "submitting"
    db.commit()  # Persist before side effect. A restart never relaunches submitting.
    try:
        receipt = driver_call(config, "submit", batch.payload)
        if receipt.get("fingerprint") != batch.fingerprint or not receipt.get("job_id"):
            raise ValueError("提交回执不完整")
        batch.payload = {**batch.payload, "job_id": receipt["job_id"]}
        batch.status = "running"
    except Exception:
        batch.status = "submission_uncertain"
    db.commit()
    return batch


def submit_plan(db, fingerprint, config=None):
    """Synchronous service entry, also used by scheduler and regression tests."""
    config = config if config is not None else effective_config(db)
    batch = queue_plan(db, fingerprint, config)
    return execute_batch(db, batch, config)


def process_queued():
    """Dispatch queue without fetching a new source population first."""
    run_tick(sync_source=False)


def set_mode(db, mode):
    if mode not in ("manual", "auto"):
        raise ValueError("无效的仿真模式")
    if mode == "auto":
        config = effective_config(db)
        if config.get("release_monitor", {}).get("enabled"):
            from app.services.release_watch import validate_monitor_config
            validate_monitor_config(config)
            if not config.get("simulation", {}).get("driver_command"):
                raise ValueError("Orion 驱动尚未配置")
        else:
            plan = make_plan(db, config)
            _driver_preflight(config, plan)
        if os.getenv("RELEASE_WORKFLOW_ENABLED") != "1":
            raise ValueError("服务端定时调度尚未启用")
    put_state(db, "settings", {"mode": mode})


def poll_batches(db, config):
    for batch in db.scalars(
        select(ReleaseSimulationBatch).where(
            ReleaseSimulationBatch.status.in_(
                ["running", "verifying", "submitting", "submission_uncertain"]
            )
        )
    ).all():
        try:
            if batch.status in ("submitting", "submission_uncertain"):
                receipt = driver_call(config, "receipt", batch.payload)
                if receipt.get("fingerprint") == batch.fingerprint and receipt.get(
                    "job_id"
                ):
                    batch.payload = {**batch.payload, "job_id": receipt["job_id"]}
                    batch.status = "running"
                    db.commit()
                else:
                    batch.status = "submission_uncertain"
                    db.commit()
                    continue
            result = driver_call(config, "poll", batch.payload)
            if result.get("fingerprint") != batch.fingerprint or str(
                result.get("job_id")
            ) != str(batch.payload["job_id"]):
                raise ValueError("结果与提交批次不匹配")
            state = result.get("status")
            if state == "audited":
                from app.services.result_integration import import_executions

                from app.services.release_backfill import frozen_snapshot_valid
                if not frozen_snapshot_valid(db, batch):
                    raise ValueError("当前来源或场景输入与提交快照不一致，停止结果导入")
                # Existing multi-job comparisons/publication decisions are immutable
                # here; refreshing those requires their explicit integration plan.
                if batch.payload.get("result_import"):
                    raise ValueError("已有评测整合记录，请按原整合计划核验")
                export = result.get("execution_export") or {}
                if str(export.get("job_id")) != str(batch.payload["job_id"]):
                    raise ValueError("核验导出与提交 Job 不匹配")
                import_executions(db, batch.payload, [export], int(batch.payload["job_id"]))
            elif state == "complete":
                expected = {s["scenario_id"] for s in batch.payload["scenarios"]}
                if (
                    result.get("quality_gate_passed") is not True
                    or set(result.get("results", {})) != expected
                ):
                    batch.status = "quality_failed"
                    batch.payload = {
                        **batch.payload,
                        "error": "结果覆盖或质量门禁未通过",
                    }
                else:
                    for row in result["results"].values():
                        if not all(
                            isinstance(row.get(k), bool)
                            for k in ("sim_triggered", "reproduced")
                        ) or row.get("precision_label") not in ("TP", "FP", "FN", "TN"):
                            raise ValueError("仿真结果不完整")
                    summary = summarize_population(
                        batch.payload["issues"],
                        batch.payload["scenarios"],
                        result["results"],
                    )
                    batch.payload = {
                        **batch.payload,
                        "results": result["results"],
                        "summary": summary,
                    }
                    batch.status = (
                        "complete" if summary["available"] else "quality_failed"
                    )
            elif state in ("running", "verifying"):
                batch.status = state
                batch.payload = {**batch.payload, "quality": result.get("quality", {})}
            elif state == "failed":
                # Legacy drivers used failed for a single task while the job was
                # still running. Never freeze monitoring on that ambiguous signal.
                batch.status = "verifying"
                batch.payload = {**batch.payload, "quality": result.get("quality", {})}
            elif state == "cancelled":
                batch.status = "cancelled"
            else:
                raise ValueError("结果驱动返回未知核验状态")
            batch.payload = {
                k: v for k, v in batch.payload.items() if k != "last_poll_error"
            }
            db.commit()
        except Exception as exc:
            db.rollback()
            batch.payload = {
                **batch.payload,
                "last_poll_error": str(exc)
                if isinstance(exc, ValueError)
                else type(exc).__name__,
            }
            db.commit()

    from app.services.result_publication import reconcile_publications
    reconcile_publications(db, config)


def metrics_for_snapshot(db, snapshot):
    if not snapshot:
        return {"available": False, "reason": "尚无完整周期人口快照"}
    population_hash = population_identity(snapshot.payload)
    from app.services.result_publication import published_batch, effective_publication
    published = published_batch(db, snapshot.release)
    from app.services.release_backfill import frozen_snapshot_valid
    if published and frozen_snapshot_valid(db, published):
        return effective_publication(db, published)
    batches = db.scalars(
        select(ReleaseSimulationBatch)
        .where(
            ReleaseSimulationBatch.release == snapshot.release,
            ReleaseSimulationBatch.status == "complete",
        )
        .order_by(ReleaseSimulationBatch.updated_at.desc())
    ).all()
    for batch in batches:
        if batch.payload.get("backfill"):
            continue
        if batch.payload.get("result_import") and not batch.payload[
            "result_import"
        ].get("primary"):
            continue
        if batch.payload.get("population_hash") == population_hash:
            return {
                **batch.payload.get("summary", {}),
                "job_id": batch.payload.get("job_id"),
                "release": snapshot.release,
                "generated_at": batch.updated_at.replace(
                    tzinfo=timezone.utc
                ).isoformat(),
            }
    return {"available": False, "reason": "当前人口尚无通过验收的完整仿真结果"}


def run_tick(sync_source=True, source_interval_seconds=0):
    lock_path = Path(
        os.getenv("RELEASE_WORKFLOW_LOCK", str(DATA_DIR / "release-workflow.lock"))
    )
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with SessionLocal() as db:
            config = effective_config(db)
            if sync_source and source_interval_seconds:
                now = datetime.now(timezone.utc)
                last = get_state(db, 'source_poll').get('started_at')
                try:
                    age = (now - datetime.fromisoformat(last)).total_seconds()
                    sync_source = not 0 <= age < source_interval_seconds
                except (TypeError, ValueError):
                    pass
                if sync_source:
                    put_state(db, 'source_poll', {'started_at':now.isoformat(), 'interval_seconds':source_interval_seconds})
            watch_enabled = config.get("release_monitor", {}).get("enabled", False)
            if sync_source and watch_enabled:
                from app.services.release_watch import monitor_releases
                monitor_releases(db, config)
                config = effective_config(db)
            if sync_source:
                # Discover historical releases even while the watcher observes
                # each tracked release. Discovery never queues simulations.
                refresh_catalog(db, config)
                config = effective_config(db)
                try:
                    sync_once(db, config)
                    if not watch_enabled and get_state(db, "settings", {"mode": "manual"})["mode"] == "auto":
                        prepare_missing_scenes(db, config)
                        queue_plan(db, make_plan(db, config)["fingerprint"], config)
                except Exception as exc:
                    db.rollback()
                    put_state(
                        db,
                        "sync",
                        {
                            "status": "failed",
                            "reason": str(exc)
                            if isinstance(exc, ValueError)
                            else type(exc).__name__,
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            for batch in db.scalars(
                select(ReleaseSimulationBatch).where(
                    ReleaseSimulationBatch.status == "queued"
                )
            ).all():
                # Quiet-window batches must be freshly observed by monitor_tick,
                # including queued batches recovered after a process restart.
                if not batch.payload.get("backfill") and batch.payload.get("period", {}).get("completion_rule") in {"issue_inactivity_24h", "issue_last_time_24h"}:
                    continue
                try:
                    execute_batch(db, batch, config, release=batch.release)
                except ValueError as exc:
                    batch.status = "cancelled_stale"
                    batch.payload = {**batch.payload, "error": str(exc)}
                    db.commit()
            poll_batches(
                db, config
            )  # Track active jobs even after switching to manual mode.
            from app.services.release_resume import process_requests
            process_requests(db, config)
            from app.services.release_backfill import tick as backfill_tick
            backfill_tick(db, config)


def tick():
    run_tick(source_interval_seconds=3600)
