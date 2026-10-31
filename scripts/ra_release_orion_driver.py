#!/usr/bin/env python3
"""JSON/stdin adapter for a full same-release Orion batch.

Runs in the validated Voyager environment. Preflight is read-only. Submission
receipts are written before launch and retained on ambiguous failures. The
backend passes an immutable plan; runtime paths and credentials are server-side.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = Path(
    os.getenv("RELEASE_DRIVER_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
)
sys.path.insert(0, str(ROOT))
INDEPENDENT = "--planning_enable_sim_assist_stuck_independent_replay"
LEVEL4 = "--sim_state_recovery_level=4"


def concurrency(value):
    if type(value) is not int or not 1 <= value <= 1000:
        raise ValueError("max_concurrency must be an integer between 1 and 1000")
    return value


def launch_priority(simulation, template_priority):
    priority = simulation.get("priority")
    if priority is None:
        return template_priority
    if priority not in ("NORMAL", "HIGH"):
        raise ValueError("Only NORMAL and HIGH submission priorities are supported")
    from orion_protos.orion_job_pb2 import OrionJob

    return OrionJob.Priority.Value(priority)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def validate_plan(plan):
    expected = digest(
        {
            k: v
            for k, v in plan.items()
            if k
            not in (
                "fingerprint",
                "job_id",
                "results",
                "summary",
                "error",
                "quality",
                "last_poll_error",
                "attached_job",
            )
        }
    )
    if plan.get("fingerprint") != expected:
        raise ValueError("Plan fingerprint mismatch")
    if not re.fullmatch(r"gen4-release-\d{8}", plan.get("release", "")):
        raise ValueError("Explicit release required")
    if not plan.get("period", {}).get("verified"):
        raise ValueError("Period boundaries must be verified before submission")
    if not plan.get("period", {}).get("binary_evidence"):
        raise ValueError("Release binary identity has no verified evidence")
    if int(plan.get("binary_id", 0)) <= 0 or int(plan.get("template_job_id", 0)) <= 0:
        raise ValueError("Positive binary and template IDs required")
    sim = plan["simulation"]
    if sim.get("priority") not in (None, "NORMAL", "HIGH"):
        raise ValueError("Only NORMAL and HIGH submission priorities are supported")
    concurrency(sim.get("max_concurrency"))
    if (
        sim.get("cluster") != "prod_gen4"
        or sim.get("cache") != "disabled"
        or sim.get("dpe") is not True
    ):
        raise ValueError("Invalid production runtime contract")
    if sim.get("recovery_mode") not in ("baseline", "level4-independent"):
        raise ValueError("Unknown recovery mode")
    rows = plan.get("scenarios", [])
    ids = [str(s.get("scenario_id", "")) for s in rows]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not value.isdigit() or int(value) <= 0 for value in ids)
    ):
        raise ValueError("Scenario identities missing or duplicated")
    for row in rows:
        if not row.get("issue_id") or row.get("cohort") not in (
            "positive_auto",
            "negative_auto",
            "positive_manual",
        ):
            raise ValueError("Scenario requires a verified source cohort")
    if "issue_tolerance" in plan:
        from ra_api.release_tolerance import validate_frozen
        validate_frozen(plan)
    return plan


def replay_arguments(raw, mode):
    tokens = str(raw).split()
    cleaned = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token == "--sim_state_recovery_level":
            skip = True
            continue
        if token.startswith("--sim_state_recovery_level=") or token == INDEPENDENT:
            continue
        cleaned.append(token)
    if mode == "level4-independent":
        cleaned += [LEVEL4, INDEPENDENT]
    return " " + " ".join(cleaned)


def check_task(arguments, binary_id, mode):
    if int(arguments.get("--binary-id", -1)) != binary_id:
        raise ValueError("Task binary mismatch")
    if arguments.get("--simulator-cache") != "disabled":
        raise ValueError("Task cache must be disabled")
    if "--enable-dpe" not in arguments:
        raise ValueError("Task DPE missing")
    tokens = str(arguments.get("--sim-exec-args", "")).split()
    if mode == "baseline":
        if INDEPENDENT in tokens or any(
            t.startswith("--sim_state_recovery_level") for t in tokens
        ):
            raise ValueError("Baseline task contains experimental recovery flags")
    elif tokens.count(LEVEL4) != 1 or tokens.count(INDEPENDENT) != 1:
        raise ValueError("Controlled replay flags missing or duplicated")


def verify_live_labels(plan):
    from ra_api.release_labels import full_scene_label, validate_scene_labels
    from ra_api.scenario_api import trail_api, ScenarioURL
    from ra_api.sim_result_api import SimResultClient

    label = plan.get('scenario_label')
    if not label or label != full_scene_label({**plan['period'], 'scenario_creation_label': label}):
        raise ValueError('New submissions require a canonical full label')
    trail_api.token = SimResultClient()._app_token
    rows = plan['scenarios']
    for start in range(0, len(rows), 100):
        expected = {str(r['scenario_id']): r for r in rows[start:start + 100]}
        response = trail_api.send_request(ScenarioURL.query.value,
            {'id': ','.join(expected), 'page': 1, 'size': 500})
        if not response or response.get('msg') != 'success':
            raise ValueError('Cannot verify live Scenario labels')
        data = response['data']
        found = data.get('res', data.get('data', []))
        if (int(data.get('total', data.get('count', -1))) != len(expected)
            or len(found) != len(expected) or {str(r['id']) for r in found} != set(expected)):
            raise ValueError('Live Scenario identity coverage mismatch')
        for row in found:
            target = expected[str(row['id'])]
            validate_scene_labels(row, label, plan['release'], target['cohort'])
            if row.get('is_deleted') or row.get('version') != target.get('scenario_revision'):
                raise ValueError('Scenario revision or deletion state changed')
            labels = row.get('labels', [])
            if isinstance(labels, str):
                labels = json.loads(labels) if labels.startswith('[') else labels.split(',')
            issue_labels = {v for v in labels if v.startswith('#') and v[1:].isdigit()}
            if issue_labels != {'#' + str(target['issue_id']).removeprefix('cn')}:
                raise ValueError('Live Scenario source Issue changed')
            if any(row.get(k) != target.get(k) for k in ('start_timestamp', 'end_timestamp')):
                raise ValueError('Live Scenario time window changed')


def build_job(plan):
    verify_live_labels(plan)
    from scripts.ra_repro_launch_full_orion import _load_api
    from orion.db_accessor.binary_accessor import BinaryAccessor

    (
        JobAccessor,
        TaskAccessor,
        TaskArgKeys,
        clone_job,
        launch_job,
        get_auth_token,
        JobArgKeys,
        OrionTask,
        Regions,
        TrailRegionMgr,
    ) = _load_api()
    with TrailRegionMgr(Regions.CN, is_pre=False):
        binary = BinaryAccessor.get(int(plan["binary_id"]))
        build = re.search(r"\.(\d+)$", plan["period"].get("target_road_version", ""))
        if (
            not build
            or binary.get("name") != "upload_binary_dcheck_off-" + build[1]
            or binary.get("platform") != "gen4"
            or binary.get("is_valid") is not True
        ):
            raise ValueError(
                "Target binary does not match the observed road release build"
            )
        if binary.get("git_commit") != plan["period"].get("binary_commit"):
            raise ValueError("Binary commit changed or has no verified receipt")
        metadata = JobAccessor.get(int(plan["template_job_id"]))
        templates = list(
            TaskAccessor.query(
                {
                    "job_id": int(plan["template_job_id"]),
                    "kind": OrionTask.MAPPER,
                    "extra_fields": "task_args",
                }
            )
        )
    if (
        not metadata
        or not templates
        or metadata.get("cluster") != "prod_gen4"
        or not metadata.get("runtime_reference")
    ):
        raise ValueError("Template runtime not valid for Gen4")
    job = clone_job(
        job_id=int(plan["template_job_id"]),
        task_id_list=[int(templates[0]["id"])],
        region=Regions.CN,
    )
    if len(job.mapper_tasks) != 1:
        raise ValueError("Clone did not produce exactly one template task")
    template = OrionTask()
    template.CopyFrom(job.mapper_tasks[0])
    job.ClearField("mapper_tasks")
    for row in plan["scenarios"]:
        task = job.mapper_tasks.add()
        task.CopyFrom(template)
        task.signature = str(row["scenario_id"])
        key = (
            TaskArgKeys.SCENARIO_ID
            if hasattr(TaskArgKeys, "SCENARIO_ID")
            else "--scenario-id"
        )
        task.arguments[key] = str(row["scenario_id"])
        task.arguments[TaskArgKeys.BINARY_ID] = str(plan["binary_id"])
        task.arguments[TaskArgKeys.SIMULATOR_CACHE] = "disabled"
        task.arguments["--sim-exec-args"] = replay_arguments(
            task.arguments.get("--sim-exec-args", ""),
            plan["simulation"]["recovery_mode"],
        )
        check_task(
            dict(task.arguments),
            int(plan["binary_id"]),
            plan["simulation"]["recovery_mode"],
        )
    job.arguments[JobArgKeys.SIMULATOR_CACHE] = "disabled"
    job.description = f"{'RA acceptance' if plan.get('acceptance_only') else 'RA cycle'} {plan['release']} {plan['fingerprint'][:12]}"
    job.labels[:] = [
        "ra_release_cycle_acceptance"
        if plan.get("acceptance_only")
        else "ra_release_cycle",
        plan["release"],
        plan["fingerprint"],
    ]
    token = os.getenv("ORION_TOKEN") or get_auth_token(None, Regions.CN)
    if not token:
        raise ValueError("Orion authentication unavailable")
    return job, metadata, launch_job, token


def atomic(path, payload):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as file:
        json.dump(payload, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    temp.replace(path)


def submit(plan, directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (plan["fingerprint"] + ".json")
    with (directory / "launch.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            receipt = json.loads(path.read_text())
            if receipt.get("job_id"):
                return receipt
            raise ValueError(
                "Previous submission outcome uncertain; reconcile before retrying"
            )
        job, metadata, launch, token = build_job(plan)
        receipt = {
            "fingerprint": plan["fingerprint"],
            "status": "submitting",
            "job_id": None,
        }
        atomic(path, receipt)
        try:
            job_id = launch(
                job,
                cluster_name="prod_gen4",
                max_concurrency=concurrency(plan["simulation"]["max_concurrency"]),
                priority=launch_priority(plan["simulation"], metadata["priority"]),
                override_runtime=metadata["runtime_reference"],
                override_token=token,
            )
            if not job_id:
                raise ValueError("Orion did not return a job ID")
        except Exception:
            receipt["status"] = "submission_uncertain"
            atomic(path, receipt)
            raise
        receipt.update(status="running", job_id=int(job_id))
        atomic(path, receipt)
        return receipt


def poll(plan):
    import pandas as pd
    from scripts.ra_repro_launch_full_orion import _load_api
    from scripts.ra_repro_validate_orion import (
        _query_orion,
        _summarize,
        _TRIGGER_METRIC,
    )
    from ra_api.sim_result_api import SimResultClient

    (
        JobAccessor,
        TaskAccessor,
        TaskArgKeys,
        _,
        _,
        get_auth_token,
        _,
        _,
        Regions,
        TrailRegionMgr,
    ) = _load_api()
    job_id = int(plan["job_id"])
    token = os.getenv("ORION_TOKEN") or get_auth_token(None, Regions.CN)
    with TrailRegionMgr(Regions.CN, is_pre=False):
        metadata = JobAccessor.get(job_id)
        tasks = list(
            TaskAccessor.query({"job_id": job_id, "extra_fields": "task_args"})
        )
    if (
        not metadata
        or metadata.get("cluster") != "prod_gen4"
        or int(metadata.get("max_concurrency", -1))
        != concurrency(plan["simulation"]["max_concurrency"])
    ):
        raise ValueError("Submitted job runtime changed")
    from orion_protos.orion_job_pb2 import OrionJob

    if int(metadata.get("state", 0)) == OrionJob.CANCELLED:
        return {
            "fingerprint": plan["fingerprint"],
            "job_id": job_id,
            "status": "cancelled",
            "quality_gate_passed": False,
            "results": {},
        }
    if plan["simulation"].get("priority") and int(
        metadata.get("priority", -1)
    ) != launch_priority(plan["simulation"], metadata.get("priority")):
        raise ValueError("Submitted job priority differs from approved plan")
    expected = {str(s["scenario_id"]) for s in plan["scenarios"]}
    actual = [str(t["signature"]) for t in tasks]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("Submitted task population mismatch")
    argument_hashes = {}
    runtime_arguments = set()
    scenario_key = getattr(TaskArgKeys, "SCENARIO_ID", "--scenario-id")
    for task in tasks:
        arguments = task.get("task_args") or task.get("arguments")
        if hasattr(arguments, "as_dict"):
            arguments = arguments.as_dict()
        if not isinstance(arguments, dict):
            raise ValueError("Cannot verify submitted task arguments")
        check_task(
            arguments, int(plan["binary_id"]), plan["simulation"]["recovery_mode"]
        )
        argument_hashes[str(task["signature"])] = digest(arguments)
        runtime_arguments.add(digest({k:v for k,v in arguments.items() if k != scenario_key}))
    from ra_api.release_tolerance import POLICY
    if plan.get("issue_tolerance", {}).get("policy") == POLICY and (len(runtime_arguments) != 1 or not metadata.get("runtime_reference")):
        raise ValueError("Actual task runtime parameters are inconsistent")
    execution_contract_hash = digest({"arguments":sorted(runtime_arguments),
        "runtime_reference":metadata.get("runtime_reference"), "binary_id":plan["binary_id"], "cluster":metadata["cluster"]}) if len(runtime_arguments) == 1 and metadata.get("runtime_reference") else None
    from orion_protos.orion_task_pb2 import OrionTask

    execution_progress = summarize_progress(
        job_id, metadata, tasks, OrionTask.Status.Name, OrionJob.State.Name
    )
    execution_progress["priority"] = OrionJob.Priority.Name(metadata["priority"])
    # A failed task can still be retried by Orion while its job is active.
    # Only audit final results once both the job and every task are terminal.
    if not ready_for_audit(execution_progress):
        return {
            "fingerprint": plan["fingerprint"], "job_id": job_id,
            "status": "running", "quality_gate_passed": False, "results": {},
        }
    manifest = pd.DataFrame(plan["scenarios"])
    manifest["scenario_id"] = manifest["scenario_id"].astype(int)
    task_results = _query_orion(job_id, token)
    dpe = SimResultClient().query_all_pages(
        job_id, metrics=["dpe_assist_channel_triggered"], page_size=100
    )
    if dpe.empty:
        dpe = pd.DataFrame(columns=["scenario_id", _TRIGGER_METRIC])
    else:
        dpe["scenario_id"] = dpe["scenario_id"].astype(int)
        dpe = dpe[["scenario_id", _TRIGGER_METRIC]]
        if dpe["scenario_id"].duplicated().any():
            raise ValueError("Duplicate DPE results")
    joined = manifest.merge(
        task_results, on="scenario_id", how="left", validate="1:1"
    ).merge(dpe, on="scenario_id", how="left", validate="1:1")
    summary = _summarize(joined, job_id)
    # Fresh results may lag the lightweight task inventory; keep polling.
    if summary["terminal"] != len(joined) or summary["completed_pending_dpe_grace"]:
        return {
            "fingerprint": plan["fingerprint"], "job_id": job_id,
            "status": "verifying", "quality_gate_passed": False,
            "results": {}, "quality": summary["quality"],
        }
    if set(task_results["scenario_id"].astype(str)) != expected:
        raise ValueError("Result audit task population mismatch")
    if {str(v) for v in task_results["task_id"]} != {str(t["id"]) for t in tasks}:
        raise ValueError("Result audit task identities differ")
    joined["argument_hash"] = joined["scenario_id"].astype(str).map(argument_hashes)
    # JSON conversion turns missing DPE/cache values into null, never NaN.
    rows = json.loads(joined.to_json(orient="records"))
    return {
        "fingerprint": plan["fingerprint"], "job_id": job_id,
        "status": "audited",
        "execution_export": {
            "job_id": job_id,
            **{key: plan[key] for key in ("release", "binary_id", "population_hash")},
            "progress": execution_progress, "quality": summary, "rows": rows,
            "execution_contract_hash": execution_contract_hash,
        },
    }


def ready_for_audit(progress):
    return (
        progress["state"] == "COMPLETED"
        and progress["total"] > 0
        and progress["finished"] == progress["total"]
    )


def summarize_progress(job_id, metadata, tasks, status_name, job_state_name):
    counts = Counter(status_name(int(task.get("status", 0))) for task in tasks)
    completed = counts["COMPLETED"]
    failed = counts["FAILED"]
    cancelled = counts["CANCELLED"]
    total = len(tasks)
    declared = int(metadata.get("num_total_tasks") or total)
    if declared != total:
        raise ValueError("Incomplete Orion task inventory; progress not published")

    def timestamp(value):
        text = str(value or "")
        return text if text[:4].isdigit() and int(text[:4]) >= 2000 else None

    return {
        "job_id": int(job_id),
        "state": job_state_name(int(metadata.get("state", 0))),
        "total": total,
        "completed": completed,
        "running": counts["RUNNING"],
        "queued": counts["UNASSIGNED"],
        "failed": failed,
        "cancelled": cancelled,
        "unknown": total
        - completed
        - failed
        - cancelled
        - counts["RUNNING"]
        - counts["UNASSIGNED"],
        "finished": completed + failed + cancelled,
        "percent": round(100 * (completed + failed + cancelled) / total, 2)
        if total
        else 0,
        "task_states": dict(counts),
        "max_concurrency": metadata.get("max_concurrency"),
        "priority": metadata.get("priority"),
        "started_at": timestamp(metadata.get("kickoff_time")),
        "finished_at": timestamp(metadata.get("finish_time")),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "failures": [
            {
                "task_id": str(t["id"]),
                "scenario_id": str(t.get("signature") or ""),
                "status": status_name(int(t.get("status", 0))),
            }
            for t in tasks
            if status_name(int(t.get("status", 0))) in ("FAILED", "CANCELLED")
        ][:10],
    }


def progress(payload):
    from orion.db_accessor.job_accessor import JobAccessor
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion_protos.orion_job_pb2 import OrionJob
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr

    job_id = int(payload["job_id"])
    if job_id <= 0:
        raise ValueError("Positive job ID required")
    with TrailRegionMgr(Regions.CN, is_pre=False):
        metadata = JobAccessor.get(job_id)
        tasks = list(TaskAccessor.query({"job_id": job_id, "extra_fields": ""}))
    if not metadata:
        raise ValueError("Orion job not found")
    result = summarize_progress(
        job_id, metadata, tasks, OrionTask.Status.Name, OrionJob.State.Name
    )
    result["priority"] = OrionJob.Priority.Name(metadata["priority"])
    return result


def prepare_scenes(payload):
    import logging
    import pandas as pd
    from ra_api.scenario_api import trail_api
    from ra_api.sim_result_api import SimResultClient
    from scripts.ra_repro_scenario_sample import build_manifest, upload_manifest

    release = payload["release"]
    period = payload["period"]
    if not re.fullmatch(r"gen4-release-\d{8}", release) or not period.get("verified"):
        raise ValueError("Verified release scope required for scenario preparation")
    from ra_api.release_labels import full_scene_label

    label = full_scene_label(period)
    if label != payload.get("label"):
        raise ValueError("Scenario label does not match period")
    rows = payload["issues"]
    if not rows or len({i["issue_id"] for i in rows}) != len(rows):
        raise ValueError("Invalid source identity population")
    for issue in rows:
        if not isinstance(issue.get("trip_id"), str) or not re.fullmatch(
            r"\d+_\d{8}_\d{6}", issue["trip_id"]
        ):
            raise ValueError("Original trip string identity missing or invalid")
        if issue.get("cohort") not in (
            "positive_auto",
            "negative_auto",
            "positive_manual",
        ):
            raise ValueError("Unknown source truth")
    directory = Path(os.environ["RELEASE_DRIVER_STATE_DIR"])
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "scenario-creation.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        source = directory / (label + "-source.csv")
        output = directory / (label + "-manifest.csv")
        frame = pd.DataFrame(rows)
        frame["release"] = release
        frame.to_csv(source, index=False)
        plan = build_manifest(
            source, 100000, "full-current-cycle", [release], None, label, 20000, 10000
        )
        original = {r["issue_id"]: r["trip_id"] for r in rows}
        if plan.validation_error.astype(bool).any() or any(
            r.trip_id != original[r.issue_id] for r in plan.itertuples()
        ):
            raise ValueError("Scenario conversion failed original-identity check")
        trail_api.token = SimResultClient()._app_token
        first = trail_api.send_request(
            "http://100.69.238.11:8000/voyager/trail/simulation/scenario/query/",
            {"labels": label, "page": 1, "size": 500},
        )
        if not first or first.get("msg") != "success":
            raise ValueError("Cannot verify existing namespace; refusing creation")
        data = first["data"]
        reported = data.get("total", data.get("count"))
        if reported is None:
            raise ValueError("Existing scene namespace has no declared total")
        total = int(reported)
        existing = list(data.get("data") or data.get("res") or [])
        for page in range(2, (total + 499) // 500 + 1):
            response = trail_api.send_request(
                "http://100.69.238.11:8000/voyager/trail/simulation/scenario/query/",
                {"labels": label, "page": page, "size": 500},
            )
            if not response or response.get("msg") != "success":
                raise ValueError("Existing scene pagination failed")
            existing.extend(
                response["data"].get("data") or response["data"].get("res") or []
            )
        if len(existing) != total or len({r["id"] for r in existing}) != total:
            raise ValueError("Existing scene namespace pagination incomplete")
        if len({r["name"] for r in existing}) != total:
            raise ValueError("Existing scene namespace contains duplicate names")
        # Pin the verified existing index; legacy upload helper must not query a partial list.
        import scripts.ra_repro_scenario_sample as helper

        helper._existing_by_name = lambda _: {
            str(r["name"]): int(r["id"]) for r in existing
        }
        logging.getLogger("ra_api.issue_api").setLevel(logging.CRITICAL)
        result = upload_manifest(plan, label, "jasperchen", None, 4)
        result.to_csv(output, index=False)
        failed = int((~result.upload_status.isin(["uploaded", "existing"])).sum())
        failures = [
            {"issue_id": str(row.issue_id),
             "reason": "missing_bag" if "does not have bags" in str(row.upload_status) else "upstream_error"}
            for row in result[~result.upload_status.isin(["uploaded", "existing"])].itertuples()
        ]
        return {
            "ready": failed == 0,
            "label": label,
            "prepared": len(result) - failed,
            "failed": failed,
            "failures": failures,
            "error": f"{failed} scenes could not be prepared" if failed else "",
        }


def lookup_binary(payload):
    from orion.db_accessor.binary_accessor import BinaryAccessor
    from voy_data_utils.regions import Regions, TrailRegionMgr

    release = payload["release"]
    candidates = []
    with TrailRegionMgr(Regions.CN, is_pre=False):
        for version in payload.get(
            "road_versions", [payload.get("target_road_version", "")]
        ):
            match = re.fullmatch(r"1\." + re.escape(release) + r"\.(\d+)", version)
            if not match:
                raise ValueError("Observed road build does not match release")
            found = [
                b
                for b in BinaryAccessor.query(
                    {"name": "upload_binary_dcheck_off-" + match[1]}
                )
                if b.get("platform") == "gen4"
                and b.get("target") == "all"
                and b.get("is_valid") is True
            ]
            if len(found) != 1:
                raise ValueError("Observed build has no unique valid Gen4 binary")
            candidates.append((found[0], version))
    if not candidates:
        raise ValueError("No observed road builds")
    binary, version = max(
        candidates, key=lambda pair: str(pair[0].get("commit_date") or "")
    )
    return {
        "binary_id": int(binary["id"]),
        "binary_commit": binary["git_commit"],
        "target_road_version": version,
        "binary_evidence": "Orion BinaryAccessor matched observed road build; latest commit_date",
    }


def dispatch(action, plan):
    if action == "progress":
        return progress(plan)
    if action == "prepare_scenes":
        return prepare_scenes(plan)
    if action == "lookup_binary":
        return lookup_binary(plan)
    validate_plan(plan)
    if action == "receipt":
        path = Path(os.environ["RELEASE_DRIVER_STATE_DIR"]) / (
            plan["fingerprint"] + ".json"
        )
        return (
            json.loads(path.read_text())
            if path.exists()
            else {"fingerprint": plan["fingerprint"], "job_id": None}
        )
    if action == "preflight":
        _, metadata, _, _ = build_job(plan)
        return {
            "fingerprint": plan["fingerprint"],
            "ready": True,
            "runtime_reference": metadata["runtime_reference"],
            "scenario_count": len(plan["scenarios"]),
            "binary_id": plan["binary_id"],
        }
    if action == "submit":
        directory = Path(os.environ["RELEASE_DRIVER_STATE_DIR"])
        return submit(plan, directory)
    if action == "poll":
        return poll(plan)
    raise ValueError("Unknown driver action")


def main():
    os.umask(0o077)
    request = json.load(sys.stdin)
    try:
        # Orion libraries may emit progress; keep stdout a single JSON document.
        with contextlib.redirect_stdout(sys.stderr):
            response = dispatch(request["action"], request["payload"])
    except Exception as exc:
        response = {
            "ready": False,
            "error": (f"Missing Python module: {exc.name}" if isinstance(exc, ModuleNotFoundError)
                      else str(exc) if isinstance(exc, ValueError) else type(exc).__name__),
        }
    json.dump(response, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
