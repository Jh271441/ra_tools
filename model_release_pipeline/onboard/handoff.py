"""Voyager handoff and DCL steps."""

from __future__ import annotations

import argparse
from dataclasses import replace
from typing import Any, Callable, Dict

from model_release_pipeline.config import BranchConfig, ReleaseConfig, VoyagerConfig
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore
from model_release_pipeline.web.stage_config import parse_update_diff_ids

ConfirmFn = Callable[[str, bool], bool]
ProgressFn = Callable[[argparse.Namespace, str, int, int, str, str], None]


def ifx_mapping_from_record(record: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    ifx_mapping = record.get("ifx", {}).get("ifx_mapping")
    if not ifx_mapping:
        ifx_mapping = record.get("ifx", {}).get("dry_run_mapping", {})
    if not ifx_mapping:
        raise RuntimeError("No IFX mapping found in release record.")
    return ifx_mapping


def _find_branch(config: VoyagerConfig, branch_value: str) -> BranchConfig | None:
    for branch in config.branches:
        if branch_value in {branch.name, branch.checkout_branch}:
            return branch
    return None


def _temporary_branch_config(
    config: VoyagerConfig,
    args: argparse.Namespace,
) -> BranchConfig | None:
    checkout_branch = str(getattr(args, "checkout_branch", "") or "").strip()
    update_diff_ids = parse_update_diff_ids(getattr(args, "update_diff_ids", "") or "")
    sim_plan = str(getattr(args, "sim_plan", "") or "").strip()
    if not any([checkout_branch, update_diff_ids, sim_plan]):
        return None

    branch_value = str(getattr(args, "branch", "") or "").strip()
    if not branch_value:
        raise RuntimeError("Temporary branch overrides require --branch.")

    base = _find_branch(config, branch_value)
    if base is None:
        if not checkout_branch:
            raise RuntimeError(
                "Unknown branch override requires --checkout-branch."
            )
        branch = BranchConfig(
            name=branch_value,
            checkout_branch=checkout_branch,
            update_diff_id=0,
            update_diff_ids=[],
            sim_plan="",
        )
    else:
        branch = replace(base)

    if checkout_branch:
        branch.checkout_branch = checkout_branch
    if update_diff_ids:
        branch.update_diff_ids = update_diff_ids
        branch.update_diff_id = update_diff_ids[0]
    if sim_plan:
        branch.sim_plan = sim_plan
    return branch


def _voyager_config_for_args(
    config: VoyagerConfig,
    args: argparse.Namespace,
) -> tuple[VoyagerConfig, BranchConfig | None]:
    override = _temporary_branch_config(config, args)
    if override is None:
        return config, None

    branches = []
    replaced = False
    branch_value = str(getattr(args, "branch", "") or "").strip()
    for branch in config.branches:
        if branch_value in {branch.name, branch.checkout_branch}:
            branches.append(override)
            replaced = True
        else:
            branches.append(branch)
    if not replaced:
        branches.append(override)
    return replace(config, branches=branches), override


def run_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    step: int = 1,
    total_steps: int = 1,
    progress: ProgressFn,
    service_cls: Any = VoyagerHandoffService,
) -> Dict[str, Any]:
    ifx_mapping = ifx_mapping_from_record(record)
    progress(args, "Voyager Handoff", step, total_steps, "🧾", "")
    result = service_cls(config.voyager).generate(
        run_dir=store.run_dir(record["release_id"]),
        ifx_mapping=ifx_mapping,
        description=args.desc or record.get("description", ""),
        experiment_name=record.get("experiment", {}).get("name")
        or "scenario_dnn_experiment",
        selected_epoch=record.get("selection", {}).get("selected_epoch"),
    )
    record["handoff"] = result
    record["stage"] = "handoff_complete"
    record["status"] = "completed"
    store.save(record)
    return record


def run_apply_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = VoyagerHandoffService,
) -> Dict[str, Any]:
    ifx_mapping = ifx_mapping_from_record(record)
    voyager_config, branch_override = _voyager_config_for_args(config.voyager, args)
    branches = (
        [branch_override.name]
        if branch_override
        else [args.branch]
        if args.branch
        else [branch.name for branch in config.voyager.branches]
    )
    branch_text = args.branch or f"all-configured ({len(branches)})"
    if not confirm(
        f"Apply handoff to Voyager MANIFEST and create local commits for {branch_text}?",
        args.yes,
    ):
        raise RuntimeError("apply-handoff cancelled by user.")

    service = service_cls(voyager_config)
    results = []
    failed = None
    for index, branch_name in enumerate(branches, start=1):
        progress(
            args,
            "Apply Voyager Handoff",
            index,
            len(branches),
            "🧾",
            f"mode: docker; branch: {branch_name}",
        )
        result = service.apply_to_docker(
            ifx_config=config.ifx,
            ifx_mapping=ifx_mapping,
            description=args.desc or record.get("description", ""),
            experiment_name=record.get("experiment", {}).get("name")
            or "scenario_dnn_experiment",
            selected_epoch=record.get("selection", {}).get("selected_epoch"),
            branch=branch_name,
            container=args.docker or "",
            dry_run=args.dry_run,
            no_commit=args.no_commit,
            allow_dirty=args.allow_dirty,
            allow_append=args.allow_append,
        )
        results.append(result)
        if result.get("returncode") not in (0, None):
            failed = result
            break

    single_branch_result = results[0] if args.branch else None
    if single_branch_result is not None:
        existing = record.get("apply_handoff")
        if existing and isinstance(existing.get("results"), list) and not failed:
            # Supplement mode: merge this branch into the existing multi-branch result.
            kept = [r for r in existing["results"] if r.get("branch") != single_branch_result.get("branch")]
            merged_results = kept + [single_branch_result]
            result = {
                **existing,
                "results": merged_results,
                "dcl_commands": [cmd for r in merged_results for cmd in r.get("dcl_commands", [])],
                "returncode": max((r.get("returncode") or 0) for r in merged_results),
                "stdout": "\n".join(r.get("stdout") or "" for r in merged_results if r.get("stdout")),
                "stderr": "\n".join(r.get("stderr") or "" for r in merged_results if r.get("stderr")),
            }
        else:
            result = single_branch_result
    else:
        result = {
            "mode": "docker",
            "returncode": failed.get("returncode") if failed else 0,
            "stdout": "\n".join(item.get("stdout") or "" for item in results),
            "stderr": "\n".join(item.get("stderr") or "" for item in results),
            "results": results,
            "dcl_commands": [
                command
                for item in results
                for command in item.get("dcl_commands", [])
            ],
        }
    record["apply_handoff"] = result
    supplementing = single_branch_result is not None and record.get("stage") == "apply_handoff_complete"
    if failed:
        record["stage"] = "apply_handoff_failed"
        record["status"] = "failed"
        store.add_error(record, "Apply handoff failed. See apply_handoff.stderr.")
    elif args.dry_run:
        if not supplementing:
            record["stage"] = "apply_handoff_dry_run"
            record["status"] = "dry_run"
    elif not supplementing:
        record["stage"] = "apply_handoff_complete"
        record["status"] = "completed"
    store.save(record)
    return record


def run_dcl(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = VoyagerHandoffService,
) -> Dict[str, Any]:
    voyager_config, branch_override = _voyager_config_for_args(config.voyager, args)
    branches = (
        [branch_override.name]
        if branch_override
        else [args.branch]
        if args.branch
        else [branch.name for branch in config.voyager.branches]
    )
    branch_text = args.branch or f"all-configured ({len(branches)})"
    if not confirm(f"Run DCL diff for {branch_text}?", args.yes):
        raise RuntimeError("dcl cancelled by user.")

    service = service_cls(voyager_config)
    results = []
    failed = None
    for index, branch_name in enumerate(branches, start=1):
        progress(
            args,
            "Run DCL Diff",
            index,
            len(branches),
            "🧾",
            f"mode: docker; branch: {branch_name}",
        )
        result = service.dcl_to_docker(
            ifx_config=config.ifx,
            branch=branch_name,
            container=args.docker or "",
            dry_run=args.dry_run,
            lint=args.lint,
            allow_dirty=args.allow_dirty,
        )
        results.append(result)
        if result.get("returncode") not in (0, None):
            failed = result
            break

    result = (
        results[0]
        if args.branch
        else {
            "mode": "docker",
            "returncode": failed.get("returncode") if failed else 0,
            "stdout": "\n".join(item.get("stdout") or "" for item in results),
            "stderr": "\n".join(item.get("stderr") or "" for item in results),
            "results": results,
        }
    )
    record["dcl"] = result
    if failed:
        record["stage"] = "dcl_failed"
        record["status"] = "failed"
        store.add_error(record, "DCL diff failed. See dcl.stderr.")
    elif args.dry_run:
        record["stage"] = "dcl_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "dcl_complete"
        record["status"] = "completed"
    store.save(record)
    return record
