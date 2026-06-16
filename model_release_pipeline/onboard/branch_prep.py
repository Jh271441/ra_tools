"""Branch preparation step: checkout release branch + create working branch."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Dict, Optional

from model_release_pipeline.config import ReleaseConfig
from model_release_pipeline.onboard.export import ensure_run
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore

ConfirmFn = Callable[[str, bool], bool]
ProgressFn = Callable[..., None]


def run_branch_prep(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = VoyagerHandoffService,
) -> Dict[str, Any]:
    base_branch = str(getattr(args, "base_branch", "") or "").strip()
    new_branch = str(getattr(args, "new_branch", "") or "").strip()
    if not base_branch:
        raise RuntimeError("branch-prep requires --base-branch.")
    if not new_branch:
        raise RuntimeError("branch-prep requires --new-branch.")

    if not confirm(
        f"Checkout {base_branch!r} and create branch {new_branch!r} in Voyager docker?",
        args.yes,
    ):
        raise RuntimeError("branch-prep cancelled by user.")

    # branch-prep is the entry step for the Rule Patch workflow: when no run
    # exists yet, create one (mirrors how `pick` bootstraps a release record).
    record = ensure_run(
        record,
        store,
        None,
        getattr(args, "desc", "") or "",
        workflow_type=getattr(args, "workflow_type", None) or "rule_patch",
    )

    progress(args, "Branch Prep", 1, 1, "🌿", f"checkout {base_branch!r}; create {new_branch!r}")

    service = service_cls(config.voyager)
    result = service.branch_prep_to_docker(
        ifx_config=config.ifx,
        base_branch=base_branch,
        new_branch=new_branch,
        container=str(getattr(args, "docker", "") or ""),
        dry_run=args.dry_run,
    )

    record["branch_prep"] = result
    if result.get("returncode") not in (0, None):
        record["stage"] = "branch_prep_failed"
        record["status"] = "failed"
        store.add_error(record, "branch-prep failed. See branch_prep.stderr.")
    elif args.dry_run:
        record["stage"] = "branch_prep_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "branch_prep_complete"
        record["status"] = "completed"
    store.save(record)
    return record
