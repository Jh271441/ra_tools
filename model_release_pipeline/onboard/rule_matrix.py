"""Rule Patch matrix workflow.

A Rule Patch *run* is keyed by a single rule CR (a kunpeng revision) and
validates it across a matrix of release branches. For each release we:

1. ``git checkout <release>`` then ``git checkout -b <prefix>/<release>/<rule>``
2. ``dcl patch --revision <ruleCR> --nobranch``
3. ``dcl diff`` to create/update that release's persistent 测试CR
4. (optionally) trigger a Sim Plan against the test CR

Per-release results live in ``record["releases"]``; the run's verdict is the
aggregate over those releases.
"""

from __future__ import annotations

import argparse
from typing import Any, Callable, Dict, List, Optional, Tuple

from model_release_pipeline.config import BranchConfig, BranchSimPlanConfig, ReleaseConfig
from model_release_pipeline.onboard.export import ensure_run
from model_release_pipeline.onboard.sim_plan import (
    _find_branch,
    _plan_overrides,
    _selected_plans,
)
from model_release_pipeline.rule_patch_cache import (
    get_cached_cr,
    remember_releases,
    set_cached_cr,
)
from model_release_pipeline.services.sim_plan import SimPlanClient
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore

ConfirmFn = Callable[[str, bool], bool]
ProgressFn = Callable[..., None]


# --- helpers ---------------------------------------------------------------


def _split_releases(args: argparse.Namespace) -> List[str]:
    """Collect release branches from repeated --release and csv --releases."""
    releases: List[str] = []
    for value in getattr(args, "release", None) or []:
        text = str(value or "").strip()
        if text and text not in releases:
            releases.append(text)
    raw = str(getattr(args, "releases", "") or "")
    for part in raw.replace("\n", ",").split(","):
        text = part.strip()
        if text and text not in releases:
            releases.append(text)
    return releases


def _working_branch(prefix: str, release: str, rule_name: str) -> str:
    parts = [p.strip("/") for p in (prefix, release, rule_name) if str(p or "").strip()]
    return "/".join(parts)


def _resolve_entry(
    args: argparse.Namespace,
    record: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    releases = record.get("releases") or []
    if not releases:
        raise RuntimeError("This run has no releases. Run rule-setup first.")
    index = getattr(args, "release_index", None)
    if index is not None:
        idx = int(index)
        if idx < 0 or idx >= len(releases):
            raise RuntimeError(f"release-index {idx} out of range (0..{len(releases) - 1}).")
        return idx, releases[idx]
    name = str(getattr(args, "release", "") or "").strip()
    # --release is `append` for rule-setup but a single value for per-release ops;
    # accept either a bare string or a 1-element list.
    if isinstance(getattr(args, "release", None), list):
        name = str((args.release or [""])[0]).strip()
    if not name:
        raise RuntimeError("Specify --release <branch> or --release-index <n>.")
    for idx, entry in enumerate(releases):
        if entry.get("release_branch") == name:
            return idx, entry
    raise RuntimeError(f"Release {name!r} is not part of this run.")


def _entry_status(entry: Dict[str, Any]) -> str:
    """Derive a per-release status from its validate sub-steps."""
    steps = [entry.get("branch_prep"), entry.get("dcl_patch"), entry.get("dcl")]
    present = [s for s in steps if isinstance(s, dict) and s]
    if not present:
        return "pending"
    if any(s.get("returncode") not in (0, None) for s in present):
        return "failed"
    if any(s.get("dry_run") for s in present):
        return "dry_run"
    return "completed"


def _recompute_rollup(record: Dict[str, Any]) -> None:
    releases = record.get("releases") or []
    statuses = [e.get("status") or "pending" for e in releases]
    if "failed" in statuses:
        record["stage"], record["status"] = "rule_matrix_failed", "failed"
    elif statuses and all(s == "completed" for s in statuses):
        record["stage"], record["status"] = "rule_matrix_complete", "completed"
    elif "dry_run" in statuses and "pending" not in statuses:
        record["stage"], record["status"] = "rule_matrix_dry_run", "dry_run"
    elif any(s not in ("pending",) for s in statuses):
        record["stage"], record["status"] = "rule_matrix_running", "running"
    else:
        record["stage"], record["status"] = "rule_setup_complete", "created"


# --- steps -----------------------------------------------------------------


def run_rule_setup(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = VoyagerHandoffService,  # unused; kept for dispatch symmetry
) -> Dict[str, Any]:
    revision_id = str(getattr(args, "revision_id", "") or "").strip()
    rule_name = str(getattr(args, "rule_name", "") or "").strip()
    prefix = str(getattr(args, "branch_prefix", "") or "").strip() or "release"
    if not revision_id:
        raise RuntimeError("rule-setup requires --revision-id (the rule CR).")
    if not rule_name:
        raise RuntimeError("rule-setup requires --rule-name.")
    releases = _split_releases(args)
    if not releases:
        raise RuntimeError("rule-setup requires at least one --release.")

    record = ensure_run(
        record,
        store,
        None,
        getattr(args, "desc", "") or f"Rule patch {rule_name} (CR{revision_id})",
        workflow_type=getattr(args, "workflow_type", None) or "rule_patch",
    )

    progress(args, "Rule Setup", 1, 1, "📋", f"CR{revision_id} → {len(releases)} release(s)")

    record["rule_patch"] = {
        "revision_id": revision_id,
        "rule_name": rule_name,
        "branch_prefix": prefix,
    }
    # Preserve already-run release entries when re-running setup (add/remove).
    existing = {e.get("release_branch"): e for e in (record.get("releases") or [])}
    entries: List[Dict[str, Any]] = []
    for release in releases:
        prev = existing.get(release, {})
        entry = {
            "release_branch": release,
            "working_branch": _working_branch(prefix, release, rule_name),
            "test_cr_revision": prev.get("test_cr_revision")
            or get_cached_cr(config.runs_dir, release),
            "branch_prep": prev.get("branch_prep", {}),
            "dcl_patch": prev.get("dcl_patch", {}),
            "dcl": prev.get("dcl", {}),
            "sim_plan": prev.get("sim_plan", {}),
        }
        entry["status"] = prev.get("status") or _entry_status(entry)
        entry["stage"] = prev.get("stage", "pending")
        entries.append(entry)
    record["releases"] = entries
    remember_releases(config.runs_dir, releases)
    _recompute_rollup(record)
    store.save(record)
    return record


def run_rule_release(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = VoyagerHandoffService,
) -> Dict[str, Any]:
    spec = record.get("rule_patch") or {}
    revision_id = str(spec.get("revision_id") or "").strip()
    if not revision_id:
        raise RuntimeError("This run is missing its rule CR. Run rule-setup first.")
    idx, entry = _resolve_entry(args, record)
    release_branch = entry["release_branch"]
    working_branch = entry["working_branch"]
    dry_run = bool(getattr(args, "dry_run", False))
    container = str(getattr(args, "docker", "") or "")

    if not confirm(
        f"Validate CR{revision_id} on {release_branch!r} "
        f"(checkout {working_branch!r}; patch; dcl diff)?",
        args.yes,
    ):
        raise RuntimeError("rule-release cancelled by user.")

    service = service_cls(config.voyager)

    # 1) checkout base + create working branch
    progress(args, "Branch Prep", 1, 3, "🌿", f"{release_branch} → {working_branch}")
    entry["branch_prep"] = service.branch_prep_to_docker(
        ifx_config=config.ifx,
        base_branch=release_branch,
        new_branch=working_branch,
        container=container,
        dry_run=dry_run,
    )

    # 2) apply the rule CR
    if entry["branch_prep"].get("returncode") in (0, None):
        progress(args, "DCL Patch", 2, 3, "🩹", f"revision {revision_id}")
        entry["dcl_patch"] = service.dcl_patch_to_docker(
            ifx_config=config.ifx,
            revision_id=revision_id,
            nobranch=True,
            container=container,
            dry_run=dry_run,
        )

    # 3) dcl diff -> create/update the persistent test CR
    if entry.get("dcl_patch", {}).get("returncode") in (0, None) and entry["branch_prep"].get(
        "returncode"
    ) in (0, None):
        progress(args, "DCL Diff", 3, 3, "📤", "create/update test CR")
        dcl_result = service.rule_dcl_diff_to_docker(
            ifx_config=config.ifx,
            base_branch=release_branch,
            working_branch=working_branch,
            test_cr_revision=str(entry.get("test_cr_revision") or ""),
            container=container,
            dry_run=dry_run,
        )
        entry["dcl"] = dcl_result
        parsed = str(dcl_result.get("revision_id") or "").strip()
        if parsed and not dry_run:
            entry["test_cr_revision"] = parsed
            set_cached_cr(config.runs_dir, release_branch, parsed)

    entry["status"] = _entry_status(entry)
    entry["stage"] = "validated" if entry["status"] == "completed" else entry["status"]
    if entry["status"] == "failed":
        store.add_error(record, f"rule-release failed on {release_branch}. See release stderr.")
    record["releases"][idx] = entry
    _recompute_rollup(record)
    store.save(record)
    return record


def _sim_tasks_for_release(
    config: ReleaseConfig,
    args: argparse.Namespace,
    entry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    revision = str(entry.get("test_cr_revision") or "").strip()
    if not revision or not revision.isdigit():
        raise RuntimeError(
            "No test CR revision yet — run validate (dcl diff) on this release first."
        )
    selected_names = _plan_overrides(args)
    branch = _find_branch(config.voyager, entry["release_branch"])
    if branch is not None:
        plans = _selected_plans(branch, selected_names, allow_custom=True)
        branch_name = branch.name
    else:
        # Ad-hoc release with no configured branch: only explicit plans are usable.
        if not selected_names:
            raise RuntimeError(
                f"Release {entry['release_branch']!r} is not configured; pass --plan <name>."
            )
        plans = [BranchSimPlanConfig(name=name) for name in selected_names]
        branch_name = entry["release_branch"]
    if not plans:
        raise RuntimeError("No Sim Plan selected for this release.")
    return [
        {"branch_name": branch_name, "revision_id": int(revision), "plan": plan}
        for plan in plans
    ]


def run_rule_sim(
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
    idx, entry = _resolve_entry(args, record)
    tasks = _sim_tasks_for_release(config, args, entry)
    dry_run = bool(getattr(args, "dry_run", False))

    if not dry_run and not confirm(
        f"Trigger {len(tasks)} Sim Plan job(s) for {entry['release_branch']}?",
        args.yes,
    ):
        raise RuntimeError("rule-sim cancelled by user.")

    client = service_cls(config.sim_plan)
    priority = getattr(args, "priority", None)
    time_sensitive_hour = getattr(args, "time_sensitive_hour", None)
    results: List[Dict[str, Any]] = []
    failed = False
    for i, task in enumerate(tasks, start=1):
        plan = task["plan"]
        progress(
            args, "Trigger Sim Plan", i, len(tasks), "🧪",
            f"{entry['release_branch']}; CR{task['revision_id']}; {plan.name}",
        )
        if dry_run:
            plan_id = int(plan.plan_id or 0)
            raw = {
                "returncode": None,
                "dry_run": True,
                "request": client.build_trigger_payload(
                    release_id=record["release_id"],
                    branch=task["branch_name"],
                    revision_id=task["revision_id"],
                    plan=plan,
                    plan_id=plan_id,
                    priority=priority,
                    time_sensitive_hour=time_sensitive_hour,
                ),
                "response": {},
                "plan_id": plan_id,
                "context_id": None,
            }
        else:
            raw = client.trigger(
                release_id=record["release_id"],
                branch=task["branch_name"],
                revision_id=task["revision_id"],
                plan=plan,
                priority=priority,
                time_sensitive_hour=time_sensitive_hour,
            )
        results.append({
            **raw,
            "branch": task["branch_name"],
            "revision_id": int(task["revision_id"]),
            "plan_name": plan.name,
            "dry_run": dry_run,
        })
        failed = failed or raw.get("returncode") not in (0, None)

    entry["sim_plan"] = {
        "mode": "simone",
        "returncode": None if dry_run else (1 if failed else 0),
        "dry_run": dry_run,
        "results": results,
        "stdout": "\n".join(
            f"{'dry-run' if r.get('dry_run') else ('ok' if r.get('returncode') == 0 else 'failed')}: "
            f"{r.get('branch')} CR{r.get('revision_id')} {r.get('plan_name')}"
            for r in results
        ),
    }
    if not dry_run:
        entry["sim_status"] = "failed" if failed else "triggered"
    record["releases"][idx] = entry
    _recompute_rollup(record)
    if failed and not dry_run:
        store.add_error(record, f"Sim Plan trigger failed on {entry['release_branch']}.")
    store.save(record)
    return record
