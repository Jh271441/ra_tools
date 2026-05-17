"""Offboard validation runner independent from the seven-step release path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from model_release_pipeline.config import ReleaseConfig
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.luban_runner import LubanRunner
from model_release_pipeline.state_store import StateStore

ProgressFn = Callable[[argparse.Namespace, str, int, int, str, str], None]
ConfirmFn = Callable[[str, bool], bool]


def _split_test_yaml_values(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            result.extend(_split_test_yaml_values(list(value)))
            continue
        for part in str(value).replace("\n", ",").split(","):
            text = part.strip()
            if text:
                result.append(text)
    return result


def _normalize_test_yaml(value: str) -> str:
    path = Path(value.strip())
    name = path.name
    if not (
        name == "scenario_dnn_finetune_test.yaml"
        or (name.startswith("scenario_dnn_finetune_test_") and name.endswith(".yaml"))
    ):
        raise RuntimeError(
            "Offboard --test-yaml must be scenario_dnn_finetune_test.yaml "
            "or scenario_dnn_finetune_test_*.yaml."
        )
    if path.is_absolute():
        return path.as_posix()
    if len(path.parts) == 1:
        return f"configs/{name}"
    if path.parts[0] != "configs":
        raise RuntimeError("Offboard --test-yaml must be a file under configs/.")
    return path.as_posix()


def _selected_test_yamls(args: argparse.Namespace, config: ReleaseConfig) -> list[str]:
    raw_values = _split_test_yaml_values(getattr(args, "test_yaml", None) or [])
    if not raw_values:
        raw_values = [config.luban.offboard_config_path]
    seen = set()
    yamls = []
    for value in raw_values:
        yaml_path = _normalize_test_yaml(value)
        if yaml_path not in seen:
            yamls.append(yaml_path)
            seen.add(yaml_path)
    return yamls


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
    test_yamls = _selected_test_yamls(args, config)
    yaml_text = ", ".join(Path(item).name for item in test_yamls)
    if not confirm(f"Run offboard test with {checkpoint.name} using {yaml_text}?", args.yes):
        raise RuntimeError("Offboard test cancelled by user.")

    runner = luban_runner_cls(config.luban)
    results = []
    failed = None
    for index, test_yaml in enumerate(test_yamls, start=1):
        progress(
            args,
            "Offboard Test",
            index + 1,
            len(test_yamls) + 1,
            "🧪",
            f"{Path(test_yaml).name}; host: {remote_host or config.luban.host_alias}",
        )
        item = runner.run_offboard_test(
            checkpoint_path=checkpoint,
            remote_host=remote_host,
            config_path=test_yaml,
            dry_run=args.dry_run,
            show_progress=not getattr(args, "json", False),
        )
        results.append(item)
        if item.get("returncode") not in (0, None) and failed is None:
            failed = item
            break

    if len(results) == 1:
        result = results[0]
    else:
        result = {
            "host": remote_host or config.luban.host_alias,
            "checkpoint_path": str(checkpoint),
            "config_yamls": [item.get("config_yaml") for item in results],
            "temp_configs": [item.get("temp_config") for item in results],
            "results": results,
            "returncode": failed.get("returncode") if failed else 0,
            "stdout": "\n".join(str(item.get("stdout") or "") for item in results),
            "stderr": "\n".join(str(item.get("stderr") or "") for item in results),
            "command": "\n".join(str(item.get("command") or "") for item in results),
        }
    branch_result = {
        **result,
        "branch": "offboard",
        "source": "run_id" if getattr(args, "run_id", None) else "experiment_epoch",
        "test_yamls": test_yamls,
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
