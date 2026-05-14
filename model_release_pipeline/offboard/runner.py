"""Offboard validation runner independent from the seven-step release path."""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, Optional

from model_release_pipeline.config import ReleaseConfig
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.luban_runner import LubanRunner
from model_release_pipeline.state_store import StateStore

ProgressFn = Callable[[argparse.Namespace, str, int, int, str, str], None]
ConfirmFn = Callable[[str, bool], bool]


def run_offboard(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]],
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    inspector_cls: Any = ExperimentInspector,
    luban_runner_cls: Any = LubanRunner,
) -> Dict[str, Any]:
    """Run offboard validation from either a run record or explicit experiment.

    This intentionally does not require upload/IFX/handoff state. With a run
    record it only uses the record's experiment path and selected epoch.
    """

    if args.dry_run and record is not None:
        record = json.loads(json.dumps(record))
    if record is None:
        if not args.experiment:
            raise RuntimeError("Provide --experiment or --run-id.")
        progress(
            args,
            "Inspect Experiment",
            1,
            2,
            "🔎",
            f"experiment: {args.experiment}",
        )
        experiment = inspector_cls(
            remote_python_bin=getattr(args, "remote_python", None)
            or config.luban.remote_python_bin
        ).inspect(args.experiment, remote_host=getattr(args, "remote", None))
        if args.epoch is None:
            raise RuntimeError("Provide --epoch when no --run-id is used.")
        epoch = args.epoch
        record = store.create(args.experiment, args.desc or "")
        checkpoint = experiment.checkpoint_for_epoch(int(epoch))
        remote_host = experiment.remote_host
    else:
        progress(
            args,
            "Inspect Experiment",
            1,
            2,
            "🔎",
            f"experiment: {record['experiment_path']}",
        )
        experiment = inspector_cls(
            remote_python_bin=getattr(args, "remote_python", None)
            or config.luban.remote_python_bin
        ).inspect(
            record["experiment_path"],
            remote_host=getattr(args, "remote", None)
            or record.get("experiment", {}).get("remote_host"),
        )
        epoch = args.epoch or record.get("selection", {}).get("selected_epoch")
        checkpoint = experiment.checkpoint_for_epoch(int(epoch))
        remote_host = experiment.remote_host

    if checkpoint is None:
        raise RuntimeError(f"Checkpoint for epoch {epoch} not found.")
    if not confirm(f"Run offboard test with {checkpoint.name}?", args.yes):
        raise RuntimeError("Offboard test cancelled by user.")

    progress(
        args,
        "Offboard Test",
        2,
        2,
        "🧪",
        f"host: {remote_host or config.luban.host_alias}",
    )
    result = luban_runner_cls(config.luban).run_offboard_test(
        checkpoint_path=checkpoint,
        remote_host=remote_host,
        dry_run=args.dry_run,
        show_progress=not getattr(args, "json", False),
    )
    branch_result = {
        **result,
        "branch": "offboard",
        "source": "run_id" if getattr(args, "run_id", None) else "experiment_epoch",
    }
    record["offboard"] = branch_result
    branches = list(record.get("offboard_branches") or [])
    branches.append(branch_result)
    record["offboard_branches"] = branches

    if result.get("returncode") not in (0, None):
        record["stage"] = "offboard_failed"
        record["status"] = "failed"
    elif args.dry_run:
        record["stage"] = "offboard_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "offboard_complete"
        record["status"] = "completed"
    if not args.dry_run:
        store.save(record)
    return record
