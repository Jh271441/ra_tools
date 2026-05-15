"""Sim Plan trigger/status/cancel steps."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from typing import Any, Callable, Dict, Iterable, Optional

from model_release_pipeline.config import (
    BranchConfig,
    BranchSimPlanConfig,
    ReleaseConfig,
    VoyagerConfig,
)
from model_release_pipeline.services.sim_plan import SimPlanClient
from model_release_pipeline.state_store import StateStore

ConfirmFn = Callable[[str, bool], bool]
ProgressFn = Callable[..., None]


def _find_branch(config: VoyagerConfig, branch_value: str) -> BranchConfig | None:
    for branch in config.branches:
        if branch_value in {branch.name, branch.checkout_branch}:
            return branch
    return None


def _dcl_results(record: Dict[str, Any]) -> list[Dict[str, Any]]:
    dcl = record.get("dcl") or {}
    results = dcl.get("results")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    if isinstance(dcl, dict) and dcl.get("branch"):
        return [dcl]
    return []


def _dcl_result_for_branch(record: Dict[str, Any], branch: BranchConfig) -> Dict[str, Any] | None:
    names = {branch.name, branch.checkout_branch}
    for result in _dcl_results(record):
        if result.get("branch") in names or result.get("checkout_branch") in names:
            return result
    return None


def _revision_from_dcl(record: Dict[str, Any], branch: BranchConfig) -> int | None:
    result = _dcl_result_for_branch(record, branch)
    if not result:
        return None
    ids = result.get("update_diff_ids") or []
    if isinstance(ids, (int, str)):
        ids = [ids]
    for value in ids:
        text = str(value).strip()
        if text.upper().startswith("CR"):
            text = text[2:].strip()
        if text.isdigit():
            return int(text)
    return None


def _split_plan_names(values: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            names.extend(_split_plan_names(value))
            continue
        for part in str(value).replace("\n", ",").split(","):
            part = part.strip()
            if part:
                names.append(part)
    return names


def _plan_overrides(args: argparse.Namespace) -> list[str]:
    return _split_plan_names(getattr(args, "plan", None) or getattr(args, "plans", None) or [])


def _selected_branches(config: VoyagerConfig, args: argparse.Namespace) -> list[BranchConfig]:
    branch_value = str(getattr(args, "branch", "") or "").strip()
    if branch_value:
        branch = _find_branch(config, branch_value)
        if branch is None:
            raise RuntimeError(f"Unknown branch for Sim Plan: {branch_value}")
        return [branch]
    return list(config.branches)


def _selected_plans(branch: BranchConfig, selected_names: list[str]) -> list[BranchSimPlanConfig]:
    plans = branch.effective_sim_plans()
    if selected_names:
        wanted = set(selected_names)
        chosen = [plan for plan in plans if plan.name in wanted]
        known = {plan.name for plan in chosen}
        missing = sorted(wanted - known)
        if missing:
            chosen.extend(BranchSimPlanConfig(name=name) for name in missing)
        return chosen
    return [plan for plan in plans if plan.enabled_by_default]


def _tasks(
    args: argparse.Namespace,
    config: ReleaseConfig,
    record: Dict[str, Any],
) -> list[Dict[str, Any]]:
    selected_names = _plan_overrides(args)
    explicit_revision = getattr(args, "revision_id", None)
    tasks: list[Dict[str, Any]] = []
    for branch in _selected_branches(config.voyager, args):
        revision_id = int(explicit_revision) if explicit_revision else _revision_from_dcl(record, branch)
        if revision_id is None:
            ids = branch.effective_diff_ids()
            revision_id = int(ids[0]) if ids else None
        if revision_id is None:
            raise RuntimeError(f"No DCL revision_id found for branch {branch.name}.")
        for plan in _selected_plans(branch, selected_names):
            tasks.append({"branch": branch, "revision_id": revision_id, "plan": plan})
    if not tasks:
        raise RuntimeError("No Sim Plan is selected.")
    return tasks


def _task_summary(tasks: list[Dict[str, Any]]) -> str:
    return ", ".join(
        f"{task['branch'].name}/CR{task['revision_id']}/{task['plan'].name}"
        for task in tasks
    )


def _dry_run_trigger_result(
    client: SimPlanClient,
    *,
    release_id: str,
    task: Dict[str, Any],
    priority: Optional[int],
    time_sensitive_hour: Optional[float],
) -> Dict[str, Any]:
    plan = task["plan"]
    plan_id = int(plan.plan_id or 0)
    request = client.build_trigger_payload(
        release_id=release_id,
        branch=task["branch"].name,
        revision_id=task["revision_id"],
        plan=plan,
        plan_id=plan_id,
        priority=priority,
        time_sensitive_hour=time_sensitive_hour,
    )
    return {
        "returncode": None,
        "dry_run": True,
        "request": request,
        "response": {},
        "plan_id": plan_id,
        "context_id": None,
    }


def _result_line(item: Dict[str, Any]) -> str:
    status = "dry-run" if item.get("dry_run") else ("ok" if item.get("returncode") == 0 else "failed")
    context = item.get("context_id")
    suffix = f" context_id={context}" if context else ""
    return (
        f"{status}: {item.get('branch')} CR{item.get('revision_id')} "
        f"{item.get('plan_name')}{suffix}"
    )


def _save_sim_plan(
    record: Dict[str, Any],
    store: StateStore,
    *,
    result: Dict[str, Any],
    stage: str,
    status: str,
) -> Dict[str, Any]:
    record["sim_plan"] = result
    record["stage"] = stage
    record["status"] = status
    store.save(record)
    return record


def run_sim_plan(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = SimPlanClient,
) -> Dict[str, Any]:
    if not config.sim_plan.enabled:
        raise RuntimeError("Sim Plan is disabled in config.")
    tasks = _tasks(args, config, record)
    if not getattr(args, "dry_run", False) and not confirm(
        f"Trigger {len(tasks)} Sim Plan job(s): {_task_summary(tasks)}?",
        args.yes,
    ):
        raise RuntimeError("sim-plan cancelled by user.")

    client = service_cls(config.sim_plan)
    priority = getattr(args, "priority", None)
    time_sensitive_hour = getattr(args, "time_sensitive_hour", None)
    results: list[Dict[str, Any]] = []
    failed = False
    for index, task in enumerate(tasks, start=1):
        branch = task["branch"]
        plan = task["plan"]
        progress(
            args,
            "Trigger Sim Plan",
            index,
            len(tasks),
            "🧪",
            f"{branch.name}; CR{task['revision_id']}; {plan.name}",
        )
        if getattr(args, "dry_run", False):
            raw = _dry_run_trigger_result(
                client,
                release_id=record["release_id"],
                task=task,
                priority=priority,
                time_sensitive_hour=time_sensitive_hour,
            )
        else:
            raw = client.trigger(
                release_id=record["release_id"],
                branch=branch.name,
                revision_id=task["revision_id"],
                plan=plan,
                priority=priority,
                time_sensitive_hour=time_sensitive_hour,
            )
        item = {
            **raw,
            "branch": branch.name,
            "revision_id": int(task["revision_id"]),
            "plan_name": plan.name,
            "dry_run": bool(getattr(args, "dry_run", False)),
        }
        failed = failed or raw.get("returncode") not in (0, None)
        results.append(item)

    stdout_lines = [_result_line(item) for item in results]
    stderr_lines = [
        json.dumps(item.get("response"), ensure_ascii=False)
        for item in results
        if item.get("returncode") not in (0, None)
    ]
    aggregate = {
        "mode": "simone",
        "returncode": None if getattr(args, "dry_run", False) else (1 if failed else 0),
        "dry_run": bool(getattr(args, "dry_run", False)),
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "results": results,
    }
    if getattr(args, "dry_run", False):
        return _save_sim_plan(
            record,
            store,
            result=aggregate,
            stage="sim_plan_dry_run",
            status="dry_run",
        )
    if failed:
        store.add_error(record, "Sim Plan trigger failed. See sim_plan.stderr.")
        return _save_sim_plan(
            record,
            store,
            result=aggregate,
            stage="sim_plan_failed",
            status="failed",
        )
    return _save_sim_plan(
        record,
        store,
        result=aggregate,
        stage="sim_plan_triggered",
        status="completed",
    )


def refresh_sim_plan_status(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    progress: ProgressFn,
    service_cls: Any = SimPlanClient,
) -> Dict[str, Any]:
    sim_plan = record.get("sim_plan") or {}
    results = sim_plan.get("results") or []
    if not results:
        raise RuntimeError("No Sim Plan trigger result found in release record.")
    client = service_cls(config.sim_plan)
    refreshed = []
    for index, item in enumerate(results, start=1):
        progress(
            args,
            "Refresh Sim Plan",
            index,
            len(results),
            "🧪",
            f"{item.get('branch')}; CR{item.get('revision_id')}; {item.get('plan_name')}",
        )
        query: Dict[str, Any] = {}
        if item.get("record_id"):
            query["detail"] = client.detail(str(item["record_id"]))
        elif item.get("context_id"):
            query["group"] = client.query_group(item["context_id"])
            query["records"] = client.query_records(revision_id=item.get("revision_id"))
        else:
            query["records"] = client.query_records(revision_id=item.get("revision_id"))
        refreshed.append({**item, "query": query})

    updated = {
        **sim_plan,
        "returncode": 0,
        "dry_run": False,
        "stdout": "\n".join(
            f"refreshed: {item.get('branch')} CR{item.get('revision_id')} {item.get('plan_name')}"
            for item in refreshed
        ),
        "stderr": "",
        "results": refreshed,
    }
    return _save_sim_plan(
        record,
        store,
        result=updated,
        stage="sim_plan_status_refreshed",
        status="completed",
    )


def cancel_sim_plan(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = SimPlanClient,
) -> Dict[str, Any]:
    record_id = str(getattr(args, "record_id", "") or "").strip()
    if not record_id:
        raise RuntimeError("--record-id is required to cancel a Sim Plan.")
    if not confirm(f"Cancel Sim Plan record {record_id}?", args.yes):
        raise RuntimeError("sim-plan-cancel cancelled by user.")
    progress(args, "Cancel Sim Plan", 1, 1, "🧪", record_id)
    result = service_cls(config.sim_plan).cancel(record_id)
    sim_plan = dict(record.get("sim_plan") or {})
    cancel_results = list(sim_plan.get("cancels") or [])
    cancel_results.append({"record_id": record_id, **result})
    sim_plan["cancels"] = cancel_results
    sim_plan["returncode"] = result.get("returncode")
    sim_plan["stdout"] = f"cancel requested: {record_id}"
    sim_plan["stderr"] = "" if result.get("returncode") == 0 else json.dumps(result.get("response"), ensure_ascii=False)
    stage = "sim_plan_cancelled" if result.get("returncode") == 0 else "sim_plan_failed"
    status = "completed" if result.get("returncode") == 0 else "failed"
    if result.get("returncode") != 0:
        store.add_error(record, "Sim Plan cancel failed. See sim_plan.stderr.")
    return _save_sim_plan(record, store, result=sim_plan, stage=stage, status=status)
