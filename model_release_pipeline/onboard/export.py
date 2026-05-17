"""Experiment inspection, epoch selection, and ONNX export step."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from model_release_pipeline.config import ReleaseConfig
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.luban_runner import LubanRunner
from model_release_pipeline.services.model_picker import ModelPicker
from model_release_pipeline.state_store import StateStore

ConfirmFn = Callable[[str, bool], bool]
FormatEpochFn = Callable[[Any], str]
ProgressFn = Callable[
    [argparse.Namespace, str, Optional[int], Optional[int], str, Optional[str], bool],
    None,
]


def select_candidate(
    pick_result: Dict[str, Any],
    experiment_path: str,
    epoch: Optional[int],
    task: Optional[str] = None,
) -> Dict[str, Any]:
    per_task = pick_result.get("per_task", {})
    if task:
        if task not in per_task:
            available = ", ".join(per_task.keys()) or "<none>"
            raise RuntimeError(f"Task {task} not found. Available tasks: {available}.")
        task_result = per_task[task]
    elif len(per_task) == 1:
        task = next(iter(per_task))
        task_result = per_task[task]
    elif len(per_task) > 1 and epoch is None:
        if pick_result.get("recommended_epoch") is None:
            available = ", ".join(per_task.keys())
            raise RuntimeError(
                "Multiple tasks were detected. Rerun with --task or --epoch. "
                f"Available tasks: {available}."
            )
        task_result = pick_result
    else:
        task_result = pick_result

    all_candidates = task_result["all_candidates"]
    if epoch is None:
        recommended_epoch = task_result.get("recommended_epoch")
        if recommended_epoch is None:
            raise RuntimeError(
                "No recommended epoch available. Rerun with --epoch to choose a checkpoint."
            )
        epoch = int(recommended_epoch)
    selected = next((item for item in all_candidates if item["epoch"] == epoch), None)
    if selected is None:
        raise RuntimeError(f"Epoch {epoch} not found in experiment {experiment_path}.")
    return dict(selected)


def select_manual_epoch_candidate(
    experiment: Any,
    experiment_path: str,
    epoch: int,
) -> Dict[str, Any]:
    checkpoint = experiment.checkpoint_for_epoch(epoch)
    if checkpoint is None:
        raise RuntimeError(f"Epoch {epoch} not found in experiment {experiment_path}.")
    return {
        "epoch": epoch,
        "task": None,
        "checkpoint_path": checkpoint,
        "sources": ["manual_epoch"],
        "notes": ["Model picking was skipped because --epoch was provided."],
    }


def ensure_run(
    record: Optional[Dict[str, Any]],
    store: StateStore,
    experiment_path: Optional[str],
    description: str,
) -> Dict[str, Any]:
    return record if record is not None else store.create(experiment_path, description)


def unsaved_dry_run_record(
    experiment_path: Optional[str],
    description: str,
) -> Dict[str, Any]:
    now = datetime.now().isoformat()
    return {
        "release_id": "__dry_run_export__",
        "created_at": now,
        "updated_at": now,
        "status": "created",
        "stage": "created",
        "description": description,
        "experiment_path": experiment_path,
        "selection": {},
        "export": {},
        "ifx": {},
        "handoff": {},
        "offboard": {},
        "errors": [],
    }


def inspect_and_pick(
    experiment_path: str,
    config: ReleaseConfig,
    remote: Optional[str] = None,
    remote_python: Optional[str] = None,
    policy: Optional[str] = None,
    top_n: Optional[int] = None,
    loss_tolerance_pct: Optional[float] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run inspect + pick without touching StateStore (for CLI or preview)."""
    experiment = _inspect_experiment_with_luban_fallback(
        experiment_path,
        config,
        remote=remote,
        remote_python=remote_python,
        inspector_cls=ExperimentInspector,
    )
    pick_result = ModelPicker().pick(
        experiment=experiment,
        policy=policy or config.picker.policy,
        top_n=top_n or config.picker.top_n,
        loss_tolerance_pct=(
            loss_tolerance_pct if loss_tolerance_pct is not None
            else config.picker.loss_tolerance_pct
        ),
    )
    return experiment.to_dict(), pick_result


def _remote_host_candidates(config: ReleaseConfig, remote: Optional[str]) -> list[str]:
    requested = str(remote or "").strip()
    if not requested:
        return []
    candidates = [requested]
    for host in config.luban.effective_host_aliases():
        if host != requested:
            candidates.append(host)
    return candidates


def _looks_like_broken_remote_mount(exc: Exception) -> bool:
    text = str(exc)
    return (
        "Transport endpoint is not connected" in text
        or "Errno 107" in text
    )


def _inspect_experiment_with_luban_fallback(
    experiment_path: str,
    config: ReleaseConfig,
    *,
    remote: Optional[str],
    remote_python: Optional[str],
    inspector_cls: Any,
) -> Any:
    hosts = _remote_host_candidates(config, remote)
    if not hosts:
        return inspector_cls(
            remote_python_bin=remote_python or config.luban.remote_python_bin
        ).inspect(experiment_path, remote_host=remote)

    errors: list[tuple[str, Exception]] = []
    for host in hosts:
        try:
            return inspector_cls(
                remote_python_bin=remote_python or config.luban.remote_python_bin
            ).inspect(experiment_path, remote_host=host)
        except Exception as exc:
            errors.append((host, exc))
            if not _looks_like_broken_remote_mount(exc):
                raise

    detail = "; ".join(f"{host}: {exc}" for host, exc in errors)
    raise RuntimeError(f"Remote inspect failed on all Luban hosts. {detail}")


def run_pick(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    *,
    progress: ProgressFn,
    inspector_cls: Any = ExperimentInspector,
    picker_cls: Any = ModelPicker,
) -> Dict[str, Any]:
    progress(args, "Inspect Experiment", 1, 2, "🔎", f"experiment: {args.experiment}", False)
    experiment = _inspect_experiment_with_luban_fallback(
        args.experiment,
        config,
        remote=getattr(args, "remote", None),
        remote_python=getattr(args, "remote_python", None),
        inspector_cls=inspector_cls,
    )

    progress(args, "Pick Epoch", 2, 2, "🏁", None, True)
    pick_result = picker_cls().pick(
        experiment=experiment,
        policy=getattr(args, "policy", None) or config.picker.policy,
        top_n=getattr(args, "top_n", None) or config.picker.top_n,
        loss_tolerance_pct=(
            getattr(args, "loss_tolerance_pct", None)
            if getattr(args, "loss_tolerance_pct", None) is not None
            else config.picker.loss_tolerance_pct
        ),
    )

    record = ensure_run(record, store, args.experiment, getattr(args, "desc", "") or "")
    record["experiment_path"] = args.experiment
    record["experiment"] = experiment.to_dict()
    record["pick"] = pick_result
    record["selection"] = {
        "selected_epoch": pick_result.get("recommended_epoch"),
        "selection_source": "pick",
    }
    record["stage"] = "picked"
    record["status"] = "running"
    store.save(record)
    return record


def export_failed(export_result: Dict[str, Any]) -> bool:
    remote_returncode = (export_result.get("export") or {}).get("returncode")
    scp_returncode = (export_result.get("scp") or {}).get("returncode")
    return remote_returncode not in (0, None) or scp_returncode not in (0, None)


def run_export(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    *,
    step_offset: int = 0,
    total_steps: int = 3,
    progress: ProgressFn,
    confirm: ConfirmFn,
    format_epoch: FormatEpochFn,
    inspector_cls: Any = ExperimentInspector,
    picker_cls: Any = ModelPicker,
    luban_runner_cls: Any = LubanRunner,
) -> Dict[str, Any]:
    progress(
        args,
        "Inspect Experiment",
        step_offset + 1,
        total_steps,
        "🔎",
        f"experiment: {args.experiment}",
        False,
    )
    experiment = inspector_cls(
        remote_python_bin=getattr(args, "remote_python", None)
        or config.luban.remote_python_bin
    ).inspect(args.experiment, remote_host=getattr(args, "remote", None))

    if args.epoch is not None:
        pick_result: Dict[str, Any] = {
            "policy": "manual_epoch",
            "recommended_epoch": None,
            "candidates": [],
            "per_task": {},
            "notes": ["Model picking skipped; using explicit --epoch."],
        }
        selected = select_manual_epoch_candidate(
            experiment, args.experiment, int(args.epoch)
        )
    else:
        pick_result = picker_cls().pick(
            experiment=experiment,
            policy=args.policy or config.picker.policy,
            top_n=args.top_n or config.picker.top_n,
            loss_tolerance_pct=getattr(args, "loss_tolerance_pct", None)
            if getattr(args, "loss_tolerance_pct", None) is not None
            else config.picker.loss_tolerance_pct,
        )
        selected = select_candidate(
            pick_result, args.experiment, None, getattr(args, "task", None)
        )

    if not confirm(f"Export epoch={selected['epoch']} from {experiment.name}?", args.yes):
        raise RuntimeError("Export cancelled by user.")

    persist_record = not (args.dry_run and record is None)
    record = (
        unsaved_dry_run_record(args.experiment, args.desc or "")
        if args.dry_run and record is None
        else ensure_run(record, store, args.experiment, args.desc or "")
    )
    record["stage"] = "exporting"
    record["status"] = "running"
    record["experiment"] = experiment.to_dict()
    selected_task = selected.get("task")
    selected_task_result = pick_result.get("per_task", {}).get(
        selected_task, pick_result
    )
    record["selection"] = {
        "policy": (
            "manual_epoch"
            if args.epoch is not None
            else args.policy or config.picker.policy
        ),
        "recommended_epoch": selected_task_result.get("recommended_epoch"),
        "selected_task": selected_task,
        "selected_epoch": selected["epoch"],
        "selection_source": "manual_epoch" if args.epoch is not None else "picker",
        "candidates": selected_task_result.get("candidates", []),
        "per_task_recommendations": {
            task: {
                "recommended_epoch": task_result.get("recommended_epoch"),
                "candidates": task_result.get("candidates", []),
            }
            for task, task_result in pick_result.get("per_task", {}).items()
        },
        "notes": pick_result["notes"],
    }
    if persist_record:
        store.save(record)

    checkpoint = experiment.checkpoint_for_epoch(selected["epoch"])
    if checkpoint is None:
        raise RuntimeError(f"Checkpoint for epoch {selected['epoch']} not found.")

    progress(
        args,
        "Remote ONNX Export",
        step_offset + 2,
        total_steps,
        "📤",
        (
            f"epoch: {format_epoch(selected['epoch'])}; "
            f"host: {experiment.remote_host or config.luban.host_alias}"
        ),
        True,
    )
    export_result = luban_runner_cls(config.luban).export_onnx(
        experiment=experiment,
        checkpoint_path=checkpoint,
        onnx_file_name=config.onnx_file_name,
        local_output_dir=store.run_dir(record["release_id"]) / "artifacts",
        dry_run=args.dry_run,
        show_progress=not getattr(args, "json", False),
        progress_step=step_offset + 3,
        progress_total=total_steps,
    )
    record["export"] = export_result
    if export_failed(export_result):
        record["stage"] = "export_failed"
        record["status"] = "failed"
        record["errors"] = list(record.get("errors", [])) + [
            {
                "message": (
                    "Remote ONNX export failed. "
                    "See export.export.stderr in release_record.json."
                ),
            }
        ]
    elif args.dry_run:
        record["stage"] = "export_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "exported"
        record["status"] = "running"
    if persist_record:
        store.save(record)
    return record
