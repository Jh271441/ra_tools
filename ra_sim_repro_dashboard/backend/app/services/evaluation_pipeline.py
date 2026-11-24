"""Independent metric revisions and manually started physical simulation plans.

The ledger uses the existing JSON state table. Legacy executions remain untouched.
All side effects persist an intent first; ambiguous Orion submissions are reconciled,
never automatically launched again. Source polling never starts a simulation.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import os
from pathlib import Path
from sqlalchemy import select, cast, func, JSON
from sqlalchemy.dialects.postgresql import JSONB
from app.config import DATA_DIR
from app.database import SessionLocal
from app.models import ReleaseWorkflowState, ReleaseSimulationBatch, ReleaseIssueSnapshot
from app.services import release_workflow as w, auto_triage_metrics as at
from app.services import (
    metric_profiles as profiles,
    auto_triage_warehouse as warehouse,
    evaluation_samples as samples,
)
from app.services import recall_comparison as recall_diff
from app.services.release_cycle import digest, validate_period
from app.services.label_recovery import SCENE_FIELDS
from app.services.result_integration import checks, TRIGGER

ACTIVE = ("preparing", "submitting", "submission_uncertain", "running", "verifying")


def now():
    return datetime.now(timezone.utc).isoformat()


def execution_audit_hash(execution):
    return digest({k: execution.get(k) for k in ("plan", "export", "results")})


def execution_receipt(db, identifier):
    """Load and hash once per clean GET; writers always re-read and re-audit."""
    from app.services.read_views import read_memo

    def load():
        value = w.get_state(db, "evexecution:" + identifier)
        return value, execution_audit_hash(value)

    return read_memo(db, ("evaluation-execution", identifier), load)


def rows(db, prefix):
    return [
        r.payload
        for r in db.scalars(
            select(ReleaseWorkflowState).where(ReleaseWorkflowState.key.startswith(prefix))
        )
    ]


def public_executions(db, release=None):
    """Project status metadata in SQL; never transfer raw exports for a board."""
    payload = ReleaseWorkflowState.payload
    if db.get_bind().dialect.name == "postgresql":
        public = cast(payload, JSONB)
        for field in ("plan", "results", "export"):
            public = public.op("-")(field)
    else:
        public = func.json_remove(payload, "$.plan", "$.results", "$.export", type_=JSON)
    source_release = payload["plan"]["release"].as_string()
    statement = select(source_release, public).where(
        ReleaseWorkflowState.key.startswith("evexecution:")
    )
    if release:
        statement = statement.where(source_release == release)
    grouped = {}
    for key, value in db.execute(statement):
        if key:
            grouped.setdefault(key, []).append(value)
    return grouped


def navigation_versions(db):
    """The metric page needs source navigation, not ordinary publication audits."""
    latest = (
        select(func.max(ReleaseIssueSnapshot.id).label("id"))
        .group_by(ReleaseIssueSnapshot.release)
        .subquery()
    )
    statement = (
        select(
            ReleaseIssueSnapshot.release,
            func.json_array_length(ReleaseIssueSnapshot.payload["issues"]),
        )
        .join(latest, ReleaseIssueSnapshot.id == latest.c.id)
        .order_by(ReleaseIssueSnapshot.release.desc())
    )
    return [{"release": release, "source_count": count} for release, count in db.execute(statement)]


@contextmanager
def lock(name, shared=False):
    path = Path(os.getenv("RELEASE_WORKFLOW_LOCK", str(DATA_DIR / "release-workflow.lock")))
    if not shared:
        path = path.with_name("evaluation-" + digest(name)[:20] + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("pipeline_busy") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def context(db, release="@current", profile_id=None, date_start=None, date_end=None):
    release = at.selected_release(db, release)
    if not release:
        raise ValueError("source_missing")
    snapshot = at._snapshot(db, release)
    if snapshot is None:
        raise ValueError("source_missing")
    profile = profiles.get(db, profile_id)
    # The default is the latest explicitly reconciled scope, shown and canonicalized
    # in the URL. Never silently substitute another range for an explicit range.
    if not date_start and not date_end:
        known = [
            r
            for r in samples.records(db, samples.INDEX)
            if r["scope"]["release"] == release
            and samples.compatible_filters(
                r["population_filters"], profile["config"]["population"]["filters"]
            )
        ]
        if not known and profile["config"]["schema_version"] == 1:
            known = [r for r in rows(db, "at_view:" + release + ":") if r.get("scope")]
        if known:
            selected = max(
                known, key=lambda r: r.get("observed_at") or r.get("label_checked_at") or ""
            )["scope"]
            date_start, date_end = selected["date_start"], selected["date_end"]
    scope = warehouse.scope_for(snapshot.payload["period"], date_start, date_end)
    ctx = {
        "release": release,
        "profile_id": profile["id"],
        "date_start": scope["date_start"],
        "date_end": scope["date_end"],
    }
    return ctx, snapshot, profile, "evcontext:" + digest(ctx)[:48]


def current_revision(db, release="@current", profile_id=None, date_start=None, date_end=None):
    _, _, _, key = context(db, release, profile_id, date_start, date_end)
    pointer = w.get_state(db, key)
    return w.get_state(db, pointer.get("revision_key", "evrevision:none"))


def cached_source(db, snapshot, scope, profile):
    return samples.read(db, scope, profile["config"]["population"]["filters"])


def physical_payload(snapshot, dashboard, observed):
    payload, labels = at.dashboard_population(snapshot, dashboard, observed)
    prior = {str(i["issue_id"]): i for i in payload["issues"]}
    changed = {iid for iid, row in labels.items() if at._physical(prior[iid]) != at._physical(row)}
    payload["issues"] = [{**prior[iid], **at._physical(row)} for iid, row in labels.items()]
    payload["scenarios"] = [s for s in payload["scenarios"] if str(s["issue_id"]) not in changed]
    return payload, labels, changed


def preparation_core(value):
    return {
        k: value[k]
        for k in (
            "context",
            "sample_snapshot_id",
            "specification",
            "issues",
            "scenarios",
            "failures",
        )
    }


def save_preparation(db, revision, issues, receipt):
    """Keep verified partial work before generating a separately reviewed plan."""
    expected = {str(i["issue_id"]) for i in issues}
    scenes = receipt.get("scenarios", [])
    failures = receipt.get("failures", [])
    succeeded = {str(s["issue_id"]) for s in scenes}
    failed = {str(f["issue_id"]) for f in failures}
    if (
        len({str(s["scenario_id"]) for s in scenes}) != len(scenes)
        or len(failed) != len(failures)
        or succeeded & failed
        or succeeded | failed != expected
        or receipt.get("prepared") != len(succeeded)
        or receipt.get("failed") != len(failed)
        or receipt.get("ready") is not (not failed)
        or any(f.get("reason") not in ("missing_bag", "upstream_error") for f in failures)
        or any(
            type(s.get("scenario_revision")) is not int
            or s["scenario_revision"] < 0
            or type(s.get("start_timestamp")) is not int
            or type(s.get("end_timestamp")) is not int
            or s["end_timestamp"] <= s["start_timestamp"]
            for s in scenes
        )
    ):
        raise ValueError("scene_preparation_receipt_invalid")
    core = {
        "context": revision["context"],
        "sample_snapshot_id": revision["source"]["dashboard"]["sample_snapshot_id"],
        "specification": revision["specification"],
        "issues": deepcopy(issues),
        "scenarios": deepcopy(scenes),
        "failures": deepcopy(failures),
    }
    identifier = digest(core)
    if not w.get_state(db, "evpreparation:" + identifier[:48]):
        w.put_state(
            db, "evpreparation:" + identifier[:48], {**core, "id": identifier, "created_at": now()}
        )


def same_scene_preparation(left, right):
    # These execution settings change evaluation, not the original trip,
    # anchor/window or Scenario revision. Reuse verified preparation receipts
    # while requiring a fresh simulation under the new runtime contract.
    def identity(specification):
        return {
            **specification,
            "simulation": {
                k: v
                for k, v in specification.get("simulation", {}).items()
                if k not in ("warmup_ms", "feature_history")
            },
        }

    return identity(left) == identity(right)


def prepared_inputs(db, ctx, dashboard, payload, specification):
    by_issue = {str(i["issue_id"]): i for i in payload["issues"]}
    scenes = {str(s["scenario_id"]): s for s in payload["scenarios"]}
    deferred, bindings = {}, []
    for receipt in sorted(rows(db, "evpreparation:"), key=lambda r: r["created_at"]):
        if receipt.get("id") != digest(preparation_core(receipt)):
            raise ValueError("scene_preparation_receipt_invalid")
        if receipt["context"]["release"] != ctx["release"] or not same_scene_preparation(
            receipt["specification"], specification
        ):
            continue
        inputs = {str(i["issue_id"]): i for i in receipt["issues"]}
        matching = {
            iid
            for iid in inputs
            if iid in by_issue and at._physical(inputs[iid]) == at._physical(by_issue[iid])
        }
        used = False
        for scene in receipt["scenarios"]:
            sid, iid = str(scene["scenario_id"]), str(scene["issue_id"])
            if iid not in matching:
                continue
            if sid in scenes and any(scenes[sid].get(k) != scene.get(k) for k in SCENE_FIELDS):
                raise ValueError("scene_preparation_receipt_invalid")
            scenes[sid] = deepcopy(scene)
            used = True
        if receipt["sample_snapshot_id"] == dashboard["sample_snapshot_id"]:
            for failure in receipt["failures"]:
                if str(failure["issue_id"]) in matching:
                    deferred[str(failure["issue_id"])] = failure["reason"]
                    used = True
        if used:
            bindings.append(receipt["id"])
    payload["scenarios"] = list(scenes.values())
    return deferred, bindings


def audited_execution_target(db, release):
    """Use an explicitly activated audited replay without replacing legacy batches."""
    binding = w.get_state(db, "evaluation_target:" + release)
    if not binding:
        return None
    execution, actual_hash = execution_receipt(db, str(binding.get("execution_id", "")))
    plan, export = execution.get("plan", {}), execution.get("export", {})
    fields = ("period", "binary_id", "template_job_id", "simulation", "driver_revision")
    if (
        binding.get("release") != release
        or not binding.get("audit_hash")
        or execution.get("status") not in ("complete", "quality_failed")
        or execution.get("id") != binding.get("execution_id")
        or execution.get("audit_hash") != binding["audit_hash"]
        or actual_hash != binding["audit_hash"]
        or not execution.get("results")
        or plan.get("release") != release
        or any(field not in plan for field in fields)
        or export.get("release") != release
        or export.get("binary_id") != plan.get("binary_id")
        or export.get("job_id") != execution.get("job_id")
        or not export.get("execution_contract_hash")
        or export.get("execution_contract_hash")
        != execution.get("preflight", {}).get("execution_contract_hash")
    ):
        raise ValueError("plan_stale")
    period = plan["period"]
    if (
        period.get("release") != release
        or not period.get("verified")
        or period.get("binary_id") != plan["binary_id"]
        or not period.get("binary_evidence")
    ):
        raise ValueError("plan_stale")
    return deepcopy({field: plan[field] for field in fields})


def target_identity(db, release):
    binding = w.get_state(db, "evaluation_target:" + release)
    return (
        {k: binding.get(k) for k in ("release", "execution_id", "audit_hash")} if binding else None
    )


def target(db, snapshot):
    config = w.effective_config(db)
    sim = config.get("simulation", {})
    period = deepcopy(snapshot.payload["period"])
    approved = audited_execution_target(db, period["release"])
    # Approved executions supersede legacy batches. Avoid loading and auditing
    # historical payloads that cannot affect this target.
    base = None if approved else at._base(db, period["release"])
    if approved:
        specification = approved
    elif base:
        p = base.payload
        period = {**period, **p["period"]}
        specification = {
            "period": period,
            "binary_id": p["binary_id"],
            "template_job_id": p["job_id"],
            "simulation": deepcopy(p["simulation"]),
            "driver_revision": p.get("driver_revision"),
        }
    else:
        specification = {
            "period": period,
            "binary_id": period.get("binary_id"),
            "template_job_id": period.get("template_job_id"),
            "simulation": {
                "cluster": "prod_gen4",
                "max_concurrency": sim.get("max_concurrency", 1),
                "priority": sim.get("priorities_by_release", {}).get(
                    period["release"], sim.get("priority", "NORMAL")
                ),
                "cache": "disabled",
                "dpe": True,
                "recovery_mode": sim.get("recovery_mode", "level4-independent"),
            },
            "driver_revision": sim.get("driver_revision"),
        }
    # An explicit execution change creates a new physical plan. Historical
    # metrics stay immutable and are never reused under a new warmup policy.
    specification["simulation"].update(w.execution_overrides(config, period["release"]))
    return specification


def same_runtime(left, right):
    return all(left.get(k) == right.get(k) for k in ("binary_id", "simulation", "driver_revision"))


def activated_scene_inputs(db, release, payload, specification):
    """The approved replay's complete manifest supersedes old scene IDs per input.

    Scene creation may issue new IDs for the same physical Issue. Requiring both
    generations would invent a coverage gap. Replace only Issues with an exact
    input match, retaining every scene in the approved manifest for that Issue.
    """
    approved = audited_execution_target(db, release)
    if not approved or not same_scene_preparation(approved, specification):
        return
    binding = w.get_state(db, "evaluation_target:" + release)
    execution = w.get_state(db, "evexecution:" + binding["execution_id"])
    inputs = {str(i["issue_id"]): i for i in execution["plan"]["issues"]}
    current = {str(i["issue_id"]): i for i in payload["issues"]}
    matching = {
        iid
        for iid in inputs
        if iid in current and at._physical(inputs[iid]) == at._physical(current[iid])
    }
    scenes = [deepcopy(s) for s in execution["plan"]["scenarios"] if str(s["issue_id"]) in matching]
    superseded = {str(s["issue_id"]) for s in scenes}
    payload["scenarios"] = [
        s for s in payload["scenarios"] if str(s["issue_id"]) not in superseded
    ] + scenes


def reuse(db, snapshot, payload, specification):
    base = at._base(db, snapshot.release)
    matches_base = base is None or same_runtime(base.payload, specification)
    if matches_base:
        results, lineage, warnings, incompatible = at.reusable_results(db, base, payload)
    else:
        results, lineage, incompatible = {}, {}, set()
        warnings = [{"job_id": base.payload.get("job_id"), "reason": "execution_contract_changed"}]
    by_issue = {str(i["issue_id"]): i for i in payload["issues"]}
    scenes = {str(s["scenario_id"]): s for s in payload["scenarios"]}
    binding = w.get_state(db, "evaluation_target:" + snapshot.release)
    activated = w.get_state(db, "evexecution:" + binding["execution_id"]) if binding else None
    approved_contract = (
        activated["export"]["execution_contract_hash"]
        if activated and same_runtime(activated["plan"], specification)
        else None
    )
    for execution in sorted(
        rows(db, "evexecution:"),
        key=lambda r: (bool(activated) and r["id"] != activated["id"], r.get("created_at", "")),
    ):
        plan = execution["plan"]
        if (
            execution.get("status") not in ("complete", "quality_failed")
            or plan["release"] != snapshot.release
        ):
            continue
        if any(
            plan.get(k) != specification.get(k)
            for k in ("binary_id", "simulation", "driver_revision")
        ):
            continue
        if activated and execution["id"] != activated["id"]:
            # A later incremental run must come from a reviewed plan bound to
            # this activation. Matching parameters alone do not authorize reuse.
            reviewed = w.get_state(db, "evplan:" + str(execution.get("plan_id", ""))[:48])
            origin = w.get_state(db, reviewed.get("revision_key", "evrevision:none"))
            if (
                not reviewed
                or reviewed.get("id") != execution.get("plan_id")
                or reviewed.get("context") != execution.get("context")
                or origin.get("target_binding") != target_identity(db, snapshot.release)
            ):
                continue
        if execution.get("audit_hash") != execution_audit_hash(execution):
            warnings.append(
                {"job_id": execution.get("job_id"), "reason": "execution_audit_changed"}
            )
            continue
        if (
            approved_contract
            and execution.get("export", {}).get("execution_contract_hash") != approved_contract
        ):
            continue
        if base and matches_base:
            expected = base.payload.get("result_import", {}).get("execution_contract_hash")
            cached = w.get_state(db, "label_runtime:" + base.fingerprint[:48])
            expected = expected or (
                cached.get("execution_contract_hash")
                if cached.get("base_audit_hash") == at.audit_hash(base.payload)
                else None
            )
            if not expected or execution["export"].get("execution_contract_hash") != expected:
                continue
        inputs = {str(i["issue_id"]): i for i in plan["issues"]}
        for scene in plan["scenarios"]:
            sid, iid = str(scene["scenario_id"]), str(scene["issue_id"])
            if (
                iid not in by_issue
                or iid not in inputs
                or at._physical(inputs[iid]) != at._physical(by_issue[iid])
            ):
                continue
            if sid in scenes and any(scenes[sid].get(k) != scene.get(k) for k in SCENE_FIELDS):
                continue
            scenes[sid] = deepcopy(scene)
            row = execution.get("results", {}).get(sid)
            if row and sid not in results and type(row.get("sim_triggered")) is bool:
                results[sid] = {
                    "sim_triggered": row["sim_triggered"],
                    "job_id": execution["job_id"],
                }
                lineage[sid] = {
                    "execution_id": execution["id"],
                    "job_id": execution["job_id"],
                    "audit_hash": execution["audit_hash"],
                }
    payload["scenarios"] = list(scenes.values())
    return results, lineage, warnings, incompatible


def summarize(projected_rows, config, label_key="auto_label"):
    counts = {
        k: 0
        for k in (
            "precision_numerator",
            "precision_denominator",
            "recall_numerator",
            "recall_denominator",
        )
    }
    simulated = dict(counts)
    covered_source = dict(counts)
    eligible = covered = matches = 0
    cohorts = {
        k: {"count": 0, "matches": 0}
        for k in ("positive_auto", "negative_auto", "positive_manual", "other_auto", "other_manual")
    }
    for row in projected_rows:
        label = row[label_key]
        source_flags = profiles.membership(config, row["ra_type"], label)
        for k, v in source_flags.items():
            counts[k] += v
        valid = bool(source_flags["precision_denominator"] or source_flags["recall_denominator"])
        if not valid:
            continue
        eligible += 1
        group = (
            ("positive_manual" if row["ra_type"] == 3 else "positive_auto")
            if label in profiles.GOOD
            else "negative_auto"
            if label == "误触发" and row["ra_type"] == 2
            else "other_manual"
            if row["ra_type"] == 3
            else "other_auto"
        )
        cohorts[group]["count"] += 1
        if row["result_status"] != "reused":
            continue
        covered += 1
        for k, v in source_flags.items():
            covered_source[k] += v
        trigger = row["sim_triggered"]
        flags = profiles.membership(config, 2 if trigger else 3, label)
        for k, v in flags.items():
            simulated[k] += v
        matched = int(trigger == (row["ra_type"] == 2))
        matches += matched
        cohorts[group]["matches"] += matched
    ratio = lambda a, b: a / b if b else None
    complete = eligible > 0 and covered == eligible
    p = ratio(simulated["precision_numerator"], simulated["precision_denominator"])
    r = ratio(simulated["recall_numerator"], simulated["recall_denominator"])
    return {
        "available": complete,
        "eligible": eligible,
        "covered": covered,
        "coverage": ratio(covered, eligible),
        "missing_results": eligible - covered,
        "road_matches": matches,
        "online_precision": ratio(counts["precision_numerator"], counts["precision_denominator"]),
        "online_recall": ratio(counts["recall_numerator"], counts["recall_denominator"]),
        "precision": p if complete else None,
        "recall": r if complete else None,
        "covered_precision": p,
        "covered_recall": r,
        "sim_repro_rate": ratio(matches, eligible) if complete else None,
        "covered_repro_rate": ratio(matches, covered),
        "counts": counts,
        "sim_counts": simulated,
        "covered_source_counts": covered_source,
        "cohorts": cohorts,
    }


def shared_results(db, base, full):
    """Allow standard backfill to reuse audited physical executions, without GT transfer."""
    source_inputs, _ = at.execution_inputs(db, base)
    if not source_inputs:
        return {}, {}
    expected_contract = base.payload.get("result_import", {}).get("execution_contract_hash")
    if not expected_contract:
        cached = w.get_state(db, "label_runtime:" + base.fingerprint[:48])
        if cached.get("base_audit_hash") == at.audit_hash(base.payload):
            expected_contract = cached.get("execution_contract_hash")
    if not expected_contract:
        return {}, {}
    expected = {str(s["scenario_id"]): s for s in full["scenarios"]}
    results, bindings = {}, {}
    for execution in sorted(rows(db, "evexecution:"), key=lambda e: e.get("created_at", "")):
        plan = execution["plan"]
        if (
            execution["status"] not in ("complete", "quality_failed")
            or plan["release"] != base.release
            or execution.get("audit_hash") != execution_audit_hash(execution)
            or execution["export"].get("execution_contract_hash") != expected_contract
            or any(
                plan.get(k) != base.payload.get(k)
                for k in ("binary_id", "simulation", "driver_revision")
            )
        ):
            continue
        inputs = {str(i["issue_id"]): i for i in plan["issues"]}
        for scene in plan["scenarios"]:
            sid, iid = str(scene["scenario_id"]), str(scene["issue_id"])
            signal = execution.get("results", {}).get(sid)
            if (
                sid in results
                or sid not in expected
                or not signal
                or type(signal.get("sim_triggered")) is not bool
                or iid not in inputs
                or iid not in source_inputs
                or at._physical(inputs[iid]) != at._physical(source_inputs[iid])
                or any(scene.get(k) != expected[sid].get(k) for k in SCENE_FIELDS)
            ):
                continue
            triggered = signal["sim_triggered"]
            results[sid] = {"sim_triggered": triggered, "job_id": execution["job_id"]}
            bindings[sid] = {
                "execution_id": execution["id"],
                "job_id": execution["job_id"],
                "audit_hash": execution["audit_hash"],
            }
    return results, bindings


def binding_valid(db, item):
    execution, actual_hash = execution_receipt(db, item["execution_id"])
    return bool(
        execution.get("audit_hash")
        and execution["audit_hash"] == item["audit_hash"]
        and execution["audit_hash"] == actual_hash
    )


def calculate(db, ctx, snapshot, profile, dashboard, observed):
    warehouse.validate_receipt(dashboard)
    payload, labels, changed_inputs = physical_payload(snapshot, dashboard, observed)
    specification = target(db, snapshot)
    deferred, preparations = prepared_inputs(db, ctx, dashboard, payload, specification)
    activated_scene_inputs(db, ctx["release"], payload, specification)
    results, lineage, warnings, incompatible = reuse(db, snapshot, payload, specification)
    projected = at.project(payload, labels, results, incompatible_scenes=incompatible)
    by_warehouse = {r["issue_id"]: r for r in dashboard["rows"]}
    for row in projected["rows"]:
        sample = by_warehouse[row["issue_id"]]
        row["auto_label"] = profiles.resolve(profile["config"], sample)
        if profile["config"]["label"]["source"] == "coalesce":
            # Every downstream consumer receives the same deterministic receipt.
            receipt = profiles.resolution(profile["config"], sample)
            row.update(
                label_resolution=receipt,
                label_source=receipt["source"] or "no_result",
                label_observed=True,
                raw_model_result=sample["ra_stuck_auto_result"],
            )
        row["auto_memberships"] = profiles.membership(
            profile["config"], row["ra_type"], row["auto_label"]
        )
        row["eligible"] = bool(
            row["auto_memberships"]["precision_denominator"]
            or row["auto_memberships"]["recall_denominator"]
        )
        row["sim_memberships"] = (
            profiles.membership(
                profile["config"], 2 if row["sim_triggered"] else 3, row["auto_label"]
            )
            if row["result_status"] == "reused" and row["eligible"]
            else None
        )
        row["baseline_available"] = dashboard.get("baseline_available", True)
        row["changed"] = row["baseline_available"] and row["auto_label"] != row["baseline_label"]
        if row["issue_id"] in changed_inputs and row["result_status"] == "missing_scenario":
            row["result_status"] = "input_changed"
        if (
            row["issue_id"] in deferred
            and not row["scenario_ids"]
            and row["result_status"] not in ("user_exclusion", "input_unverified")
        ):
            row["result_status"] = deferred[row["issue_id"]]
    metrics = summarize(projected["rows"], profile["config"])
    metrics["source_pending_count"] = len(dashboard.get("pending", []))
    if metrics["source_pending_count"]:
        metrics.update(available=False, precision=None, recall=None, sim_repro_rate=None)
    # Both labels on the same population, rather than a comparison to a different inventory.
    baseline = summarize(projected["rows"], profiles.DEFAULT_CONFIG, "baseline_label")
    if dashboard.get("baseline_available") is False:
        baseline = {
            **summarize([], profiles.DEFAULT_CONFIG),
            "source_available": False,
            "error": "baseline_unavailable",
        }
    source = {
        "dashboard": dashboard,
        "labels": labels,
        "inventory_identity": at.source_identity(snapshot.payload),
    }
    core = {
        "metric_projection_schema": "paired_coverage_v1",
        "context": ctx,
        "config_hash": profile["config_hash"],
        "source": source,
        "payload": payload,
        "lineage": lineage,
        "specification": specification,
        "preparations": preparations,
    }
    if profile["config"]["label"]["source"] == "coalesce":
        core["metric_projection_schema"] = "review_sources_v2"
    identity = target_identity(db, ctx["release"])
    if identity:
        core["target_binding"] = identity
    key = "evrevision:" + digest(core)[:48]
    return {
        **core,
        "revision_key": key,
        "profile": profile,
        "metrics": metrics,
        "baseline": baseline,
        "rows": projected["rows"],
        "warnings": warnings,
        "generated_at": now(),
        "label_checked_at": dashboard["observed_at"],
        "source_count": len(dashboard["rows"]),
        "source_snapshot_id": snapshot.id,
        "reconciliation": {
            "status": "matched",
            "checked_issues": len(dashboard["rows"]),
            "counts": dashboard["counts"],
            "references": dashboard.get("references", []),
        },
    }


def recalculate(
    db, release="@current", profile_id=None, date_start=None, date_end=None, refresh_labels=False
):
    ctx, _, _, _ = context(db, release, profile_id, date_start, date_end)
    with lock("context:" + digest(ctx)):
        db.expire_all()
        return _recalculate(db, **ctx, refresh_labels=refresh_labels)


def _recalculate(
    db, release="@current", profile_id=None, date_start=None, date_end=None, refresh_labels=False
):
    if refresh_labels:
        raise ValueError("offline_sample_update_required")
    ctx, snapshot, profile, key = context(db, release, profile_id, date_start, date_end)
    if profile["status"] != "published":
        raise ValueError("profile_not_published")
    scope = {k: ctx[k] for k in ("release", "date_start", "date_end")}
    dashboard, observed = cached_source(db, snapshot, scope, profile)
    value = calculate(db, ctx, snapshot, profile, dashboard, observed)
    db.expire_all()
    if (
        at.source_identity(at._snapshot(db, ctx["release"]).payload)
        != value["source"]["inventory_identity"]
    ):
        raise ValueError("source_changed")
    save_revision(db, value)
    return value


def save_revision(db, value):
    ctx = value["context"]
    key = "evcontext:" + digest(ctx)[:48]
    if not w.get_state(db, value["revision_key"]):
        w.put_state(db, value["revision_key"], value)
    pointer = w.get_state(db, key)
    w.put_state(
        db,
        key,
        {
            **pointer,
            "context": ctx,
            "revision_key": value["revision_key"],
            "updated_at": now(),
            "cron_enabled": pointer.get("cron_enabled", False),
            "next_check_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    generate_plan(db, value)
    return value


def publish_profile_revision(db, profile, preview):
    source = w.get_state(db, "evpreviewdata:" + preview["preview_hash"][:48])
    if not source or digest(source) != preview.get("source_hash"):
        raise ValueError("profile_preview_required")
    ctx, snapshot, _, _ = context(db, **{**preview["context"], "profile_id": profile["id"]})
    if source["inventory_identity"] != at.source_identity(snapshot.payload):
        raise ValueError("plan_stale")
    scope = {k: ctx[k] for k in ("release", "date_start", "date_end")}
    current = samples.selection(db, scope, profile["config"]["population"]["filters"])
    if source["dashboard"].get("sample_snapshot_id") != current["snapshot_id"]:
        raise ValueError("plan_stale")
    value = calculate(db, ctx, snapshot, profile, source["dashboard"], source["labels"])
    return save_revision(db, value)


def generate_plan(db, revision):
    gaps = [r for r in revision["rows"] if r["eligible"] and r["result_status"] != "reused"]
    blocked = [r for r in gaps if r["result_status"] in ("user_exclusion", "input_unverified")]
    deferred = [r for r in gaps if r["result_status"] in ("missing_bag", "upstream_error")]
    actions = [
        {
            "issue_id": r["issue_id"],
            "reason": r["result_status"],
            "scenario_ids": r["scenario_ids"],
            "action": "review"
            if r in blocked
            else "deferred"
            if r in deferred
            else "prepare"
            if not r["scenario_ids"]
            else "simulate",
        }
        for r in gaps
    ]
    core = {
        "revision_key": revision["revision_key"],
        "context": revision["context"],
        "specification": revision["specification"],
        "actions": actions,
    }
    identifier = digest(core)
    value = {
        **core,
        "id": identifier,
        "created_at": now(),
        "reuse_count": revision["metrics"]["covered"],
        "gap_count": len(gaps),
        "review_count": len(blocked),
        "blocked_count": len(deferred),
        "runnable_count": sum(a["action"] in ("prepare", "simulate") for a in actions),
        "prepare_count": sum(a["action"] == "prepare" for a in actions),
        "simulate_count": sum(a["action"] == "simulate" for a in actions),
        "manual_start_required": True,
    }
    if not w.get_state(db, "evplan:" + identifier[:48]):
        w.put_state(db, "evplan:" + identifier[:48], value)
    ctxkey = "evcontext:" + digest(revision["context"])[:48]
    w.put_state(db, ctxkey, {**w.get_state(db, ctxkey), "plan_id": identifier})
    return value


def preview(db, version, release="@current", profile_id=None, date_start=None, date_end=None):
    ctx, snapshot, _, _ = context(db, release, profile_id, date_start, date_end)
    previous = current_revision(db, **ctx)
    if not previous:
        previous = recalculate(db, **ctx)
    profile = profiles.get(db, version)
    scope = {k: ctx[k] for k in ("release", "date_start", "date_end")}
    dashboard, observed = cached_source(db, snapshot, scope, profile)
    candidate = calculate(
        db, {**ctx, "profile_id": profile["id"]}, snapshot, profile, dashboard, observed
    )
    old = {r["issue_id"]: r for r in previous["rows"]}
    new = {r["issue_id"]: r for r in candidate["rows"]}
    value = {
        "profile_id": version,
        "config_hash": profile["config_hash"],
        "context": ctx,
        "base_revision": previous["revision_key"],
        "metrics": candidate["metrics"],
        "previous_metrics": previous["metrics"],
        "population_added": len(new.keys() - old.keys()),
        "population_removed": len(old.keys() - new.keys()),
        "changed_labels": sum(
            old[i]["auto_label"] != new[i]["auto_label"] for i in old.keys() & new.keys()
        ),
        "newly_eligible": sum(
            r["eligible"] and not old.get(i, {}).get("eligible", False) for i, r in new.items()
        ),
        "no_longer_eligible": sum(
            r["eligible"] and not new.get(i, {}).get("eligible", False) for i, r in old.items()
        ),
        "source_hash": digest(candidate["source"]),
        "generated_at": now(),
    }
    value["preview_hash"] = digest(value)
    w.put_state(db, "evpreviewdata:" + value["preview_hash"][:48], candidate["source"])
    w.put_state(db, "evpreview:" + value["preview_hash"][:48], value)
    return value


def queue(
    db, release="@current", profile_id=None, date_start=None, date_end=None, refresh_labels=False
):
    if refresh_labels:
        raise ValueError("offline_sample_update_required")
    ctx, _, _, _ = context(db, release, profile_id, date_start, date_end)
    with lock("context:" + digest(ctx)):
        db.expire_all()
        return _queue(db, **ctx, refresh_labels=refresh_labels)


def _queue(
    db, release="@current", profile_id=None, date_start=None, date_end=None, refresh_labels=False
):
    ctx, _, profile, key = context(db, release, profile_id, date_start, date_end)
    if profile["status"] != "published":
        raise ValueError("profile_not_published")
    pointer = w.get_state(db, key)
    request = w.get_state(db, pointer.get("request_key", "evrequest:none"))
    if (
        request.get("source_mode") == "database"
        and request.get("status") in ("queued", "running")
        and (
            datetime.now(timezone.utc) - datetime.fromisoformat(request["requested_at"])
        ).total_seconds()
        < 1800
    ):
        return request
    value = {
        "context": ctx,
        "refresh_labels": False,
        "source_mode": "database",
        "status": "queued",
        "requested_at": now(),
    }
    value["id"] = digest(value)[:32]
    request_key = "evrequest:" + value["id"]
    w.put_state(db, request_key, value)
    w.put_state(
        db,
        key,
        {
            **pointer,
            "context": ctx,
            "request_key": request_key,
            "cron_enabled": pointer.get("cron_enabled", False),
        },
    )
    return value


def process(identifier):
    with lock("request:" + identifier), SessionLocal() as db:
        key = "evrequest:" + identifier
        value = w.get_state(db, key)
        if value.get("status") not in ("queued", "running"):
            return
        w.put_state(db, key, {**value, "status": "running"})
        try:
            revision = recalculate(
                db, **value["context"], refresh_labels=value.get("refresh_labels", False)
            )
            outcome = {"status": "complete", "revision_key": revision["revision_key"]}
        except Exception as exc:
            db.rollback()
            outcome = {
                "status": "failed",
                "error": str(exc) if isinstance(exc, ValueError) else "upstream_error",
            }
        w.put_state(db, key, {**value, **outcome, "finished_at": now()})


def board(
    db,
    release="@current",
    profile_id=None,
    date_start=None,
    date_end=None,
    *,
    catalogue=None,
    execution_views=None,
    comparison_only=False,
):
    from app.services import evaluation_worker
    from app.services.evaluation_sources import distribution

    ctx, snapshot, profile, key = context(db, release, profile_id, date_start, date_end)
    pointer = w.get_state(db, key)
    revision = w.get_state(db, pointer.get("revision_key", "evrevision:none"))
    stale = bool(revision) and revision["source"]["inventory_identity"] != at.source_identity(
        snapshot.payload
    )
    if revision and not same_runtime(revision["specification"], target(db, snapshot)):
        stale = True
    if revision and revision.get("target_binding") != target_identity(db, ctx["release"]):
        stale = True
    source_scope = {k: ctx[k] for k in ("release", "date_start", "date_end")}
    source_status = samples.status(db, source_scope, profile["config"]["population"]["filters"])
    if revision and (
        source_status["status"] != "ready"
        or revision["source"]["dashboard"].get("sample_snapshot_id")
        != source_status.get("snapshot_id")
    ):
        stale = True
    for identifier in revision.get("preparations", []):
        receipt = w.get_state(db, "evpreparation:" + identifier[:48])
        if (
            not receipt
            or receipt.get("id") != identifier
            or digest(preparation_core(receipt)) != identifier
        ):
            stale = True
    # A release has many scene bindings to the same large execution receipt.
    # Verify each receipt once per read while still checking every binding.
    execution_checks, batch_hashes = {}, {}
    for binding in revision.get("lineage", {}).values():
        if binding.get("execution_id"):
            identity = (binding["execution_id"], binding.get("audit_hash"))
            if identity not in execution_checks:
                execution_checks[identity] = binding_valid(db, binding)
            if not execution_checks[identity]:
                stale = True
        elif binding.get("fingerprint"):
            fingerprint = binding["fingerprint"]
            if fingerprint not in batch_hashes:
                batch = db.get(ReleaseSimulationBatch, fingerprint)
                batch_hashes[fingerprint] = at.audit_hash(batch.payload) if batch else None
            if batch_hashes[fingerprint] != binding["audit_hash"]:
                stale = True
    if revision and not stale:
        from app.services.reproduction_evidence import evaluation_view

        # This projection returns metrics/source aggregates, never Issue rows.
        # Recall comparison below reads the original whole-window row signals.
        revision = evaluation_view(db, revision, include_rows=False)
    public_revision = (
        {k: v for k, v in revision.items() if k not in ("source", "payload", "rows", "lineage")}
        if revision
        else None
    )
    if public_revision is not None:
        public_revision["source_distribution"] = distribution(revision)
    # Comparison consumes only this audited projection. Avoid loading plans,
    # start receipts and execution histories which never appear in its response.
    if comparison_only:
        return {"revision": public_revision, "stale": stale}
    histories = (
        execution_views if execution_views is not None else public_executions(db, ctx["release"])
    )
    executions = histories.get(ctx["release"], [])
    request = w.get_state(db, pointer.get("request_key", "evrequest:none"))
    # Retain old online requests in the audit ledger without presenting their
    # expired session error as a failure of the new DB-only query path.
    request = request if request.get("source_mode") == "database" else {}
    return {
        "context": ctx,
        "profile": profile,
        "versions": at.versions(db) if catalogue is None else catalogue,
        "sample_source": source_status,
        "recall_comparison": recall_diff.compare(revision["rows"], profile["config"])
        if revision and not stale
        else None,
        "revision": public_revision,
        "stale": stale,
        "refresh": request,
        "plan": w.get_state(db, "evplan:" + pointer.get("plan_id", "none")[:48]),
        "cron": {
            "enabled": pointer.get("cron_enabled", False),
            "interval_seconds": 3600,
            "effective": pointer.get("cron_enabled", False)
            and evaluation_worker.scheduling_enabled(),
            "processing_enabled": evaluation_worker.enabled(),
            "poll_seconds": evaluation_worker.POLL_SECONDS,
            "next_check_at": pointer.get("next_check_at"),
        },
        "executions": [
            {k: v for k, v in e.items() if k not in ("plan", "results", "export")}
            for e in executions
        ],
        "starts": [s for s in rows(db, "evstart:") if s["context"] == ctx],
    }


def issue_page(
    db,
    release="@current",
    profile_id=None,
    date_start=None,
    date_end=None,
    page=1,
    page_size=20,
    query="",
    coverage="",
    changed_only=False,
):
    if (
        page < 1
        or page_size not in (10, 20, 50, 100)
        or coverage
        not in (
            "",
            "gap",
            "reused",
            "recall_gain",
            "recall_loss",
            "before_manual",
            "after_manual",
            "reproduction_pending",
        )
    ):
        raise ValueError("invalid_pagination")
    revision = current_revision(db, release, profile_id, date_start, date_end)
    from app.services.reproduction_evidence import evaluation_view

    revision = evaluation_view(db, revision)
    config = profiles.get(db, profile_id)["config"]

    def matches(row):
        behavior = row.get("reproduction") or {}
        if coverage in ("before_manual", "after_manual"):
            return row["eligible"] and behavior.get("status") == coverage + "_trigger"
        if coverage == "reproduction_pending":
            return row["eligible"] and bool(behavior) and behavior.get("matched") is None
        if coverage == "gap":
            return row["eligible"] and row["result_status"] != "reused"
        if coverage == "reused":
            return row["result_status"] == "reused"
        return not coverage or recall_diff.transition(row, config) == coverage

    values = [
        r
        for r in revision.get("rows", [])
        if (not query or query.casefold() in (r["issue_id"] + " " + r["issue_topic"]).casefold())
        and matches(r)
        and (not changed_only or r["changed"])
    ]
    return {
        "items": values[(page - 1) * page_size : page * page_size],
        "total": len(values),
        "page": page,
        "page_size": page_size,
        "pages": (len(values) + page_size - 1) // page_size,
        "revision_key": revision.get("revision_key"),
    }


def comparison(db, profile_id=None, date_start=None, date_end=None):
    profile = profiles.get(db, profile_id)
    values = []
    # Only release keys are needed here. The board's catalogue additionally
    # audits legacy jobs and reads full source snapshots for navigation counts.
    releases = db.scalars(
        select(ReleaseIssueSnapshot.release)
        .group_by(ReleaseIssueSnapshot.release)
        .order_by(ReleaseIssueSnapshot.release.desc())
    )
    for release in releases:
        try:
            view = board(db, release, profile["id"], date_start, date_end, comparison_only=True)
            values.append(
                {"release": release, "revision": view["revision"], "stale": view["stale"]}
            )
        except ValueError:
            continue
    return {"profile": profile, "versions": list(reversed(values))}


def set_cron(db, enabled, **ctx):
    ctx, _, _, _ = context(db, **ctx)
    with lock("context:" + digest(ctx)):
        db.expire_all()
        return _set_cron(db, enabled, **ctx)


def _set_cron(db, enabled, **ctx):
    ctx, _, _, key = context(db, **ctx)
    if type(enabled) is not bool:
        raise ValueError("invalid_cron")
    pointer = w.get_state(db, key)
    w.put_state(
        db, key, {**pointer, "context": ctx, "cron_enabled": enabled, "next_check_at": now()}
    )
    return board(db, **ctx)["cron"]


def start(db, identifier):
    with lock("execution", shared=True):
        plan = w.get_state(db, "evplan:" + identifier[:48])
        if not plan or plan.get("id") != identifier:
            raise ValueError("plan_not_found")
        previous = w.get_state(db, "evstart:" + identifier[:48])
        if previous and previous["status"] != "failed":
            return previous
        view = board(db, **plan["context"])
        if view["stale"]:
            raise ValueError("plan_stale")
        revision = current_revision(db, **plan["context"])
        if revision.get("revision_key") != plan["revision_key"]:
            raise ValueError("plan_stale")
        _, snapshot, _, _ = context(db, **plan["context"])
        if revision["source"]["inventory_identity"] != at.source_identity(snapshot.payload):
            raise ValueError("plan_stale")
        if plan["review_count"]:
            raise ValueError("requires_user_review")
        if not plan.get("runnable_count", plan["gap_count"]):
            return {"status": "complete", "plan_id": identifier, "simulation_submitted": False}
        specification = target(db, snapshot)
        if specification != plan["specification"]:
            raise ValueError("plan_stale")
        validate_period(specification["period"], require_verified=True)
        if not specification["binary_id"] or not specification["template_job_id"]:
            raise ValueError("binary_unverified")
        config = w.effective_config(db)
        if not config.get("simulation", {}).get("driver_command"):
            raise ValueError("driver_unavailable")
        # Ordinary and AutoTriage submitters use this same workflow lock.
        if any(
            b.status in ("queued", "submitting", "submission_uncertain", "running", "verifying")
            and b.payload.get("binary_id") == specification["binary_id"]
            for b in db.scalars(
                select(ReleaseSimulationBatch).where(
                    ReleaseSimulationBatch.release == plan["context"]["release"]
                )
            )
        ):
            raise ValueError("shared_execution_active")
        if any(
            e["status"] in ACTIVE
            and e["plan"]["release"] == plan["context"]["release"]
            and e["plan"]["binary_id"] == specification["binary_id"]
            for e in rows(db, "evexecution:")
        ):
            raise ValueError("shared_execution_active")
        value = {
            "id": identifier[:48],
            "status": "preparing",
            "plan_id": identifier,
            "context": plan["context"],
            "created_at": now(),
            "simulation_submitted": False,
        }
        if previous:
            value["previous_attempts"] = previous.get("previous_attempts", []) + [
                {k: v for k, v in previous.items() if k != "previous_attempts"}
            ]
        w.put_state(db, "evstart:" + identifier[:48], value)
        return value


def execute_start(db, value):
    identifier = value["plan_id"]
    # A crash after persisting submit intent must resume receipt reconciliation,
    # even if the source has since changed. It must never prepare or submit again.
    existing = next(
        (
            e
            for e in rows(db, "evexecution:")
            if e.get("plan_id") == identifier
            and e["status"] not in ("preparing", "preflight_failed")
        ),
        None,
    )
    if existing:
        return existing
    plan = w.get_state(db, "evplan:" + identifier[:48])

    def validate_current():
        db.expire_all()
        view = board(db, **plan["context"])
        _, snapshot, _, _ = context(db, **plan["context"])
        if (
            view["stale"]
            or not view["revision"]
            or view["revision"]["revision_key"] != plan["revision_key"]
            or target(db, snapshot) != plan["specification"]
        ):
            raise ValueError("plan_stale")

    validate_current()
    revision = w.get_state(db, plan["revision_key"])
    source = revision["payload"]
    by_issue = {i["issue_id"]: i for i in source["issues"]}
    specification = plan["specification"]
    config = w.effective_config(db)
    scenes = deepcopy(source["scenarios"])
    pending_prepare = [by_issue[a["issue_id"]] for a in plan["actions"] if a["action"] == "prepare"]
    if pending_prepare:
        receipt = w.driver_call(
            config,
            "prepare_scenes",
            {
                **specification,
                "release": plan["context"]["release"],
                "execution_schema": "physical_v2",
                "issues": pending_prepare,
            },
        )
        save_preparation(db, revision, pending_prepare, receipt)
        if not receipt.get("ready"):
            updated = recalculate(db, **plan["context"])
            return {
                "id": value["id"],
                "status": "plan_updated",
                "revision_key": updated["revision_key"],
            }
        scenes.extend(receipt["scenarios"])
    ids = {a["issue_id"] for a in plan["actions"] if a["action"] in ("prepare", "simulate")}
    already = set(revision["lineage"])
    requested = [
        {
            **s,
            "cohort": "source_manual"
            if by_issue[str(s["issue_id"])]["ra_type"] == 3
            else "source_auto",
        }
        for s in scenes
        if str(s["issue_id"]) in ids and str(s["scenario_id"]) not in already
    ]
    if not requested or {str(s["issue_id"]) for s in requested} != ids:
        raise ValueError("scene_preparation_failed")
    body = {
        **specification,
        "execution_schema": "physical_v2",
        "release": plan["context"]["release"],
        "population_hash": digest([by_issue[i] for i in sorted(ids)]),
        "scenarios": sorted(requested, key=lambda s: str(s["scenario_id"])),
        "issues": [by_issue[i] for i in sorted(ids)],
        "acceptance_only": False,
    }
    body["fingerprint"] = digest(body)
    execution = {
        "id": body["fingerprint"][:48],
        "created_at": now(),
        "status": "preparing",
        "plan": body,
        "context": plan["context"],
        "plan_id": identifier,
        "simulation_submitted": False,
    }
    key = "evexecution:" + execution["id"]
    existing = w.get_state(db, key)
    if existing and existing["status"] not in ("preparing", "preflight_failed"):
        return existing
    if existing:
        execution = {**existing, "status": "preparing"}
    # Preflight is read-only. Persist execution intent only after all preflight
    # gates pass, immediately before submission. Failures remain in evstart.
    preflight = w.driver_call(config, "preflight", body)
    if preflight.get("ready") is not True or preflight.get("fingerprint") != body["fingerprint"]:
        raise ValueError("preflight_failed")
    base = at._base(db, body["release"])
    if base and same_runtime(base.payload, specification):
        from app.services.label_recovery import contract

        if preflight.get("execution_contract_hash") != contract(db, config, base):
            raise ValueError("execution_contract_changed")
    validate_current()
    execution.update(status="submitting", preflight=preflight)
    w.put_state(db, key, execution)
    try:
        receipt = w.driver_call(config, "submit", body)
        if receipt.get("fingerprint") != body["fingerprint"] or not receipt.get("job_id"):
            raise ValueError("submission_uncertain")
        execution.update(status="running", job_id=receipt["job_id"], simulation_submitted=True)
    except Exception:
        execution.update(status="submission_uncertain")
    w.put_state(db, key, execution)
    return execution


def poll_execution(db, execution):
    config = w.effective_config(db)
    body = {
        **execution["plan"],
        **({"job_id": execution["job_id"]} if execution.get("job_id") else {}),
    }
    if execution["status"] in ("submitting", "submission_uncertain"):
        receipt = w.driver_call(config, "receipt", body)
        if not receipt.get("job_id"):
            return  # No new submit on an ambiguous receipt.
        execution.update(status="running", job_id=receipt["job_id"], simulation_submitted=True)
        body["job_id"] = receipt["job_id"]
    progress = w.driver_call(config, "progress", {"job_id": execution["job_id"]})
    execution["progress"] = progress.get("progress", progress)
    result = w.driver_call(config, "poll", body)
    if result.get("execution_export"):
        export = result["execution_export"]
        expected = {str(s["scenario_id"]): s for s in body["scenarios"]}
        received = {str(r["scenario_id"]): r for r in export["rows"]}
        progress = export.get("progress", {})
        task_ids = [str(r.get("task_id") or "") for r in export["rows"]]
        counts = {
            status: sum(r.get("task_status") == status for r in received.values())
            for status in (3, 4, 5)
        }
        if (
            len(received) != len(export["rows"])
            or set(received) != set(expected)
            or len(set(task_ids)) != len(task_ids)
            or not all(task_ids)
            or not export.get("execution_contract_hash")
            or export["progress"]["state"] != "COMPLETED"
            or progress.get("job_id") != execution["job_id"]
            or progress.get("total") != len(expected)
            or [counts[3], counts[4], counts[5]]
            != [progress.get("completed"), progress.get("failed"), progress.get("cancelled")]
            or any(
                export.get(k) != body.get(k) for k in ("release", "binary_id", "population_hash")
            )
            or export["job_id"] != execution["job_id"]
            or export["execution_contract_hash"]
            != execution["preflight"]["execution_contract_hash"]
        ):
            raise ValueError("execution_audit_mismatch")
        if any(
            r.get("issue_id") != expected[sid]["issue_id"]
            or not r.get("argument_hash")
            or r.get("cohort") != expected[sid].get("cohort")
            or r.get("task_status") not in counts
            for sid, r in received.items()
        ):
            raise ValueError("execution_audit_mismatch")
        valid = {
            sid: {"sim_triggered": r[TRIGGER] >= 1} for sid, r in received.items() if not checks(r)
        }
        execution.update(
            status="complete" if len(valid) == len(expected) else "quality_failed",
            results=valid,
            export=export,
            finished_at=now(),
        )
        execution["audit_hash"] = execution_audit_hash(execution)
    elif result.get("status") == "cancelled":
        execution.update(status="cancelled", finished_at=now())
    else:
        execution["status"] = result.get("status", "running")
    execution.pop("error", None)
    if execution["status"] in ("complete", "quality_failed"):
        execution["metrics_status"] = "pending"
    w.put_state(db, "evexecution:" + execution["id"], execution)
    if execution["status"] in ("complete", "quality_failed"):
        from app.services.reproduction_evidence import capture_completion

        capture_completion(db, execution=execution)
    sync_start(db, execution)
    if execution["status"] in ("complete", "quality_failed"):
        project_execution_metrics(db, execution)


def sync_start(db, execution):
    if not execution.get("plan_id"):
        return
    key = "evstart:" + execution["plan_id"][:48]
    started = w.get_state(db, key)
    if started.get("execution_id") != execution["id"]:
        return
    changes = {
        k: execution[k]
        for k in ("status", "simulation_submitted", "job_id", "finished_at")
        if k in execution
    }
    if any(started.get(k) != v for k, v in changes.items()):
        w.put_state(db, key, {**started, **changes})


def project_execution_metrics(db, execution):
    # Raw results are already audited and retained. A temporary projection failure
    # must retry DB-only evaluation, never re-submit the physical simulation.
    try:
        value = recalculate(db, **execution["context"])
        execution.update(
            metrics_status="complete",
            metrics_revision_key=value["revision_key"],
            metrics_finished_at=now(),
        )
        execution.pop("metrics_error", None)
        execution.pop("metrics_retry_at", None)
    except Exception as exc:
        db.rollback()
        execution.update(
            metrics_status="pending",
            metrics_error=str(exc) if isinstance(exc, ValueError) else "upstream_error",
            metrics_retry_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        )
    w.put_state(db, "evexecution:" + execution["id"], execution)


def tick(*, schedule=True):
    """Recover authorized work; optionally schedule DB-only hourly plans."""
    with SessionLocal() as db:
        for item in rows(db, "evrequest:"):
            if item["status"] in ("queued", "running"):
                try:
                    process(item["id"])
                except ValueError:
                    pass
        db.expire_all()
        for pointer in rows(db, "evcontext:"):
            if schedule and pointer.get("cron_enabled") and pointer.get("context"):
                due = pointer.get("next_check_at")
                if not due or datetime.fromisoformat(due) <= datetime.now(timezone.utc):
                    try:
                        request = queue(db, **pointer["context"])
                        # Advance before attempting: a failed upstream gets bounded retry.
                        key = "evcontext:" + digest(pointer["context"])[:48]
                        w.put_state(
                            db,
                            key,
                            {
                                **w.get_state(db, key),
                                "next_check_at": (
                                    datetime.now(timezone.utc) + timedelta(hours=1)
                                ).isoformat(),
                            },
                        )
                        process(request["id"])
                    except ValueError:
                        pass
        try:
            with lock("execution", shared=True):
                for started in rows(db, "evstart:"):
                    if started["status"] == "preparing":
                        try:
                            execution = execute_start(db, started)
                            w.put_state(
                                db,
                                "evstart:" + started["id"],
                                {
                                    **started,
                                    "status": execution["status"],
                                    "execution_id": execution["id"],
                                    "simulation_submitted": execution.get(
                                        "simulation_submitted", False
                                    ),
                                    **(
                                        {"job_id": execution["job_id"]}
                                        if execution.get("job_id")
                                        else {}
                                    ),
                                },
                            )
                        except Exception as exc:
                            db.rollback()
                            w.put_state(
                                db,
                                "evstart:" + started["id"],
                                {
                                    **started,
                                    "status": "failed",
                                    "error": str(exc)
                                    if isinstance(exc, ValueError)
                                    else "upstream_error",
                                },
                            )
                for execution in rows(db, "evexecution:"):
                    sync_start(db, execution)
                    if (
                        execution["status"] in ("complete", "quality_failed")
                        and execution.get("metrics_status") != "complete"
                    ):
                        retry = execution.get("metrics_retry_at")
                        if not retry or datetime.fromisoformat(retry) <= datetime.now(timezone.utc):
                            project_execution_metrics(db, execution)
                    if execution["status"] in (
                        "submitting",
                        "submission_uncertain",
                        "running",
                        "verifying",
                    ):
                        try:
                            poll_execution(db, execution)
                        except Exception as exc:
                            db.rollback()
                            w.put_state(
                                db,
                                "evexecution:" + execution["id"],
                                {
                                    **execution,
                                    "error": str(exc)
                                    if isinstance(exc, ValueError)
                                    else "upstream_error",
                                },
                            )
        except ValueError:
            pass
