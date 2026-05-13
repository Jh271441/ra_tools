"""CLI for scenario dnn release tooling."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from model_release_pipeline.config import (
    DEFAULT_TEMPLATE_PATH,
    ReleaseConfig,
    load_config,
)
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.ifx_pipeline import IfxPipeline, IfxPipelineError
from model_release_pipeline.services.luban_runner import LubanRunner
from model_release_pipeline.services.model_picker import ModelPicker
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore
from model_release_pipeline.web_app import serve as serve_web


_DISPLAY_METRICS = ("roc_auc", "pr_auc", "accuracy", "f1_score", "precision", "recall")


def _separator(char: str = "=") -> str:
    columns = shutil.get_terminal_size((100, 20)).columns
    width = max(40, int(columns * 0.9))
    return char * width


def _print(payload: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(payload)


def _progress(
    args: argparse.Namespace,
    title: str,
    step: Optional[int] = None,
    total: Optional[int] = None,
    blank_before: bool = True,
    icon: str = "▶",
    detail: Optional[str] = None,
) -> None:
    if not getattr(args, "json", False):
        title = title.strip().rstrip(".")
        spacer = "\n" if blank_before else ""
        print(f"{spacer}{_separator('=')}", file=sys.stderr, flush=True)
        print(f"{icon} {title}", file=sys.stderr, flush=True)
        if step is not None and total is not None:
            print(f"step: {step}/{total}", file=sys.stderr, flush=True)
            print(
                f"tasks_remaining: {max(total - step, 0)}",
                file=sys.stderr,
                flush=True,
            )
        if detail:
            print(detail, file=sys.stderr, flush=True)
        print(_separator("="), file=sys.stderr, flush=True)


def _format_number(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.5f}"
    return str(value)


def _format_epoch(epoch: Any) -> str:
    try:
        return f"{int(epoch):03d}"
    except (TypeError, ValueError):
        return str(epoch)


def _candidate_metric_text(candidate: Dict[str, Any], first_metric: str) -> str:
    fields = [first_metric] + [
        metric for metric in _DISPLAY_METRICS if metric != first_metric
    ]
    return " | ".join(
        f"{metric if metric != 'f1_score' else 'f1'}={_format_number(candidate.get(metric))}"
        for metric in fields
        if candidate.get(metric) is not None
    )


def _format_top_by_metric(task: str, candidates: list[Dict[str, Any]], metric: str, top_n: int) -> str:
    ranked = sorted(
        [candidate for candidate in candidates if candidate.get(metric) is not None],
        key=lambda candidate: candidate[metric],
        reverse=True,
    )[:top_n]
    if not ranked:
        return ""
    lines = [f"===== {task}: Top {top_n} by {metric} ====="]
    for index, candidate in enumerate(ranked, 1):
        lines.append(
            f"[{index:02d}] Epoch {_format_epoch(candidate.get('epoch'))} | "
            f"{_candidate_metric_text(candidate, metric)}"
        )
    return "\n".join(lines)


def _format_task_sections(task: str, task_result: Dict[str, Any], top_n: int, policy: str) -> str:
    candidates = task_result.get("all_candidates", [])
    metric_candidates = [
        candidate
        for candidate in candidates
        if any(candidate.get(metric) is not None for metric in _DISPLAY_METRICS)
    ]
    if not metric_candidates:
        return f"===== {task}: No parsed metrics ====="
    metrics = ["roc_auc", "pr_auc"]
    if policy == "recall_first":
        metrics.append("recall")
    else:
        metrics.append("precision")
    if task == "stuck_detect":
        extra = "recall" if policy != "recall_first" else "precision"
        if extra not in metrics:
            metrics.append(extra)

    sections = [
        section
        for metric in metrics
        if (section := _format_top_by_metric(task, metric_candidates, metric, top_n))
    ]
    if not sections:
        fallback = [
            candidate
            for candidate in task_result.get("candidates", [])
            if any(candidate.get(metric) is not None for metric in _DISPLAY_METRICS)
        ]
        if not fallback:
            return f"===== {task}: No parsed metrics ====="
        lines = [f"===== {task}: Top {len(fallback)} by picker score ====="]
        for index, candidate in enumerate(fallback, 1):
            lines.append(
                f"[{index:02d}] Epoch {_format_epoch(candidate.get('epoch'))} | "
                f"{_candidate_metric_text(candidate, 'precision')}"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _format_combined_recommendations(pick_result: Dict[str, Any], top_n: int) -> str:
    combined = pick_result.get("combined_recommendations") or []
    if not combined:
        return ""
    lines = ["===== Selected Epochs (primary stuck_detect precision weighted) =====", ""]
    for item in combined[:top_n]:
        epoch = item.get("epoch")
        lines.append(
            f"Epoch {_format_epoch(epoch)} | TOTAL={item.get('total_rank')} | "
            f"primary={item.get('primary_task')}"
        )
        rank_details = item.get("rank_details", {})
        metrics_by_task = item.get("metrics_by_task", {})
        for task, metrics in metrics_by_task.items():
            ranks = rank_details.get(task, {})
            rank_text = ", ".join(f"{metric}={rank}" for metric, rank in ranks.items())
            lines.append(f"  [{task}] ranks: {rank_text}")
            lines.append(
                "    "
                + " | ".join(
                    f"{metric if metric != 'f1_score' else 'f1'}={_format_number(metrics.get(metric))}"
                    for metric in _DISPLAY_METRICS
                    if metrics.get(metric) is not None
                )
            )
        lines.append("-" * 90)
    return "\n".join(lines)


def _format_tensorboard_fallbacks(pick_result: Dict[str, Any]) -> str:
    lines = []
    for task, task_result in pick_result.get("per_task", {}).items():
        fallback = task_result.get("tensorboard_loss_window")
        if not fallback:
            continue
        candidate = fallback.get("candidate", {})
        if not lines:
            lines.extend(["===== TensorBoard Val-Loss Tolerance Fallback =====", ""])
        lines.append(
            f"{task}: min_loss_epoch={_format_epoch(fallback.get('min_loss_epoch'))} | "
            f"min_loss={_format_number(fallback.get('min_loss'))} | "
            f"loss_tolerance={_format_number(fallback.get('loss_tolerance_pct'))} | "
            f"max_loss={_format_number(fallback.get('max_allowed_loss'))} | "
            f"candidates={fallback.get('candidate_count')} | "
            f"recommended_epoch={_format_epoch(fallback.get('recommended_epoch'))}"
        )
        lines.append(
            "  "
            + " | ".join(
                f"{metric if metric != 'f1_score' else 'f1'}={_format_number(candidate.get(metric))}"
                for metric in ("loss", "precision", "recall", "pr_auc", "roc_auc")
                if candidate.get(metric) is not None
            )
        )
    return "\n".join(lines)


def _format_pick_result(pick_result: Dict[str, Any]) -> str:
    top_n = int(pick_result.get("top_n") or 3)
    policy = str(pick_result.get("policy") or "precision_first")
    lines = [
        f"Policy: {policy}",
        f"Tasks: {', '.join(pick_result.get('tasks', [])) or '<none>'}",
        "",
    ]
    for task, task_result in pick_result.get("per_task", {}).items():
        lines.append(_format_task_sections(task, task_result, top_n, policy))
        lines.append("")

    combined = _format_combined_recommendations(pick_result, top_n)
    if combined:
        lines.append(combined)
        lines.append("")

    tensorboard_fallbacks = _format_tensorboard_fallbacks(pick_result)
    if tensorboard_fallbacks:
        lines.append(tensorboard_fallbacks)
        lines.append("")

    recommended_epoch = pick_result.get("recommended_epoch")
    if recommended_epoch is None and len(pick_result.get("per_task", {})) == 1:
        only_task_result = next(iter(pick_result["per_task"].values()))
        recommended_epoch = only_task_result.get("recommended_epoch")
    lines.append(f"Recommended epoch: {_format_epoch(recommended_epoch)}")
    if pick_result.get("notes"):
        lines.append("")
        lines.extend(f"Note: {note}" for note in pick_result["notes"])
    return "\n".join(line for line in lines if line is not None)


def _command_state(result: Optional[Dict[str, Any]]) -> str:
    if not result:
        return "NA"
    returncode = result.get("returncode")
    stderr = str(result.get("stderr") or "")
    if returncode == 0:
        return "OK"
    if returncode is None and stderr.startswith("Skipped"):
        return "SKIPPED"
    if returncode is None:
        return "DRY-RUN"
    return f"FAILED({returncode})"


def _tail_text(text: Any, max_lines: int = 8) -> list[str]:
    lines = str(text or "").strip().splitlines()
    if len(lines) > max_lines:
        return ["..."] + lines[-max_lines:]
    return lines


def _append_command_result(
    lines: list[str],
    label: str,
    result: Optional[Dict[str, Any]],
    show_error: bool = True,
) -> None:
    state = _command_state(result)
    if state == "OK":
        icon = "✅"
    elif state.startswith("FAILED"):
        icon = "❌"
    elif state == "SKIPPED":
        icon = "⏭"
    elif state == "DRY-RUN":
        icon = "🧪"
    else:
        icon = "ℹ"
    lines.append(f"{icon} {label}: {state}")
    if not result:
        return
    if show_error and state.startswith("FAILED"):
        stderr_tail = _tail_text(result.get("stderr"))
        if stderr_tail:
            lines.append("  stderr:")
            lines.extend(f"  {line}" for line in stderr_tail)


def _format_record_result(record: Dict[str, Any]) -> str:
    lines = [
        f"release_id: {record.get('release_id')}",
        f"stage/status: {record.get('stage')} / {record.get('status')}",
    ]
    experiment = record.get("experiment") or {}
    if experiment.get("name"):
        lines.append(f"experiment: {experiment.get('name')}")
    selection = record.get("selection") or {}
    if selection.get("selected_epoch") is not None:
        lines.append(
            f"selected epoch: {_format_epoch(selection.get('selected_epoch'))} "
            f"({selection.get('selection_source') or 'unknown'})"
        )

    export = record.get("export") or {}
    if export:
        _append_command_result(lines, "remote export", export.get("export"))
        _append_command_result(lines, "scp onnx", export.get("scp"), show_error=False)
        if export.get("remote_onnx_file"):
            lines.append(f"  remote onnx: {export.get('remote_onnx_file')}")
        if export.get("local_onnx_file"):
            lines.append(f"  local onnx: {export.get('local_onnx_file')}")

    ifx = record.get("ifx") or {}
    if ifx:
        label = ifx.get("label")
        mapping = ifx.get("ifx_mapping") or {}
        lines.append(f"ifx: label={label or 'NA'} platforms={len(mapping)}")
        runner = ifx.get("truck_runner") or {}
        if runner:
            lines.append(
                "  truck runner: "
                f"{runner.get('configured') or 'NA'} -> {runner.get('selected') or 'NA'}"
            )
        if ifx.get("upload_description"):
            lines.append(f"  upload desc: {ifx.get('upload_description')}")
        onnx = ifx.get("onnx") or {}
        if onnx.get("version") is not None:
            lines.append(f"  onnx version: {onnx.get('version')}")

    handoff = record.get("handoff") or {}
    if handoff:
        if handoff.get("manifest_snippet"):
            lines.append(f"manifest snippet: {handoff.get('manifest_snippet')}")
        if handoff.get("commands_file"):
            lines.append(f"handoff commands: {handoff.get('commands_file')}")

    apply_handoff = record.get("apply_handoff") or {}
    if apply_handoff:
        _append_command_result(lines, "apply handoff", apply_handoff)
        if apply_handoff.get("results"):
            lines.append(
                "  branches: "
                f"{len(apply_handoff.get('results') or [])} attempted"
            )
            for item in apply_handoff.get("results", []):
                state = _command_state(item)
                lines.append(
                    "  "
                    f"{item.get('branch')} -> {item.get('checkout_branch')}: {state}"
                )
        else:
            lines.append(
                "  docker: "
                f"{apply_handoff.get('container')}:{apply_handoff.get('workdir')}"
            )
            lines.append(
                "  branch: "
                f"{apply_handoff.get('branch')} -> "
                f"{apply_handoff.get('checkout_branch')}"
            )
        if apply_handoff.get("dcl_commands"):
            lines.append("  dcl next steps:")
            lines.extend(
                f"  {command}" for command in apply_handoff.get("dcl_commands", [])
            )

    dcl = record.get("dcl") or {}
    if dcl:
        _append_command_result(lines, "dcl", dcl)
        if dcl.get("results"):
            lines.append("  branches: " f"{len(dcl.get('results') or [])} attempted")
            for item in dcl.get("results", []):
                state = _command_state(item)
                lines.append(
                    "  "
                    f"{item.get('branch')} -> {item.get('checkout_branch')}: {state}"
                )
        else:
            lines.append(
                "  branch: "
                f"{dcl.get('branch')} -> {dcl.get('checkout_branch')}"
            )

    offboard = record.get("offboard") or {}
    if offboard:
        _append_command_result(lines, "offboard", offboard)

    errors = record.get("errors") or []
    if errors and record.get("status") == "failed":
        lines.append("errors:")
        for error in errors[-3:]:
            if isinstance(error, dict):
                lines.append(f"  {error.get('message')}")
            else:
                lines.append(f"  {error}")
    elif errors:
        lines.append(f"previous_errors: {len(errors)} (see release_record.json)")
    return "\n".join(lines)


def _format_inspect_result(experiment: Dict[str, Any]) -> str:
    lines = [
        f"experiment: {experiment.get('name')}",
        f"path: {experiment.get('experiment_path')}",
        f"version: {experiment.get('version_name')}",
        f"tasks: {', '.join(experiment.get('tasks') or []) or '<none>'}",
        f"checkpoints: {len(experiment.get('checkpoints') or [])}",
    ]
    if experiment.get("current_trained_model_relative_path"):
        lines.append(
            "hparams checkpoint: "
            f"{experiment.get('current_trained_model_relative_path')}"
        )
    if experiment.get("log_file"):
        lines.append(f"train log: {experiment.get('log_file')}")
    if experiment.get("tensorboard_files"):
        lines.append(
            f"tensorboard files: {len(experiment.get('tensorboard_files') or [])}"
        )
    return "\n".join(lines)


def _print_record(record: Dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        _print(record, as_json=True)
    else:
        print("\n" + _format_record_result(record))


def _record_failed(record: Dict[str, Any]) -> bool:
    return record.get("status") == "failed"


def _export_failed(export_result: Dict[str, Any]) -> bool:
    remote_returncode = (export_result.get("export") or {}).get("returncode")
    scp_returncode = (export_result.get("scp") or {}).get("returncode")
    return remote_returncode not in (0, None) or scp_returncode not in (0, None)



def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _build_store(config: ReleaseConfig) -> StateStore:
    return StateStore(config.runs_dir)


def _select_candidate(
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


def _select_manual_epoch_candidate(
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


def _ensure_run(
    record: Optional[Dict[str, Any]],
    store: StateStore,
    experiment_path: Optional[str],
    description: str,
) -> Dict[str, Any]:
    return record if record is not None else store.create(experiment_path, description)


def _inspect_and_pick(
    experiment_path: str,
    config: ReleaseConfig,
    policy: Optional[str] = None,
    top_n: Optional[int] = None,
    loss_tolerance_pct: Optional[float] = None,
    remote: Optional[str] = None,
    remote_python: Optional[str] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    experiment = ExperimentInspector(
        remote_python_bin=remote_python or config.luban.remote_python_bin
    ).inspect(experiment_path, remote_host=remote)
    pick_result = ModelPicker().pick(
        experiment=experiment,
        policy=policy or config.picker.policy,
        top_n=top_n or config.picker.top_n,
        loss_tolerance_pct=(
            loss_tolerance_pct
            if loss_tolerance_pct is not None
            else config.picker.loss_tolerance_pct
        ),
    )
    return experiment.to_dict(), pick_result


def _command_export(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 3,
) -> Dict[str, Any]:
    _progress(
        args,
        "Inspect Experiment",
        step=step_offset + 1,
        total=total_steps,
        blank_before=False,
        icon="🔎",
        detail=f"experiment: {args.experiment}",
    )
    experiment = ExperimentInspector(
        remote_python_bin=getattr(args, "remote_python", None)
        or config.luban.remote_python_bin
    ).inspect(
        args.experiment, remote_host=getattr(args, "remote", None)
    )
    pick_result: Dict[str, Any]
    if args.epoch is not None:
        pick_result = {
            "policy": "manual_epoch",
            "recommended_epoch": None,
            "candidates": [],
            "per_task": {},
            "notes": ["Model picking skipped; using explicit --epoch."],
        }
        selected = _select_manual_epoch_candidate(
            experiment, args.experiment, int(args.epoch)
        )
    else:
        pick_result = ModelPicker().pick(
            experiment=experiment,
            policy=args.policy or config.picker.policy,
            top_n=args.top_n or config.picker.top_n,
            loss_tolerance_pct=getattr(args, "loss_tolerance_pct", None)
            if getattr(args, "loss_tolerance_pct", None) is not None
            else config.picker.loss_tolerance_pct,
        )
        selected = _select_candidate(
            pick_result, args.experiment, None, getattr(args, "task", None)
        )
    if not _confirm(
        f"Export epoch={selected['epoch']} from {experiment.name}?", args.yes
    ):
        raise RuntimeError("Export cancelled by user.")

    record = _ensure_run(record, store, args.experiment, args.desc or "")
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
    store.save(record)
    checkpoint = experiment.checkpoint_for_epoch(selected["epoch"])
    if checkpoint is None:
        raise RuntimeError(f"Checkpoint for epoch {selected['epoch']} not found.")
    _progress(
        args,
        "Remote ONNX Export",
        step=step_offset + 2,
        total=total_steps,
        icon="📤",
        detail=(
            f"epoch: {_format_epoch(selected['epoch'])}; "
            f"host: {experiment.remote_host or config.luban.host_alias}"
        ),
    )
    export_result = LubanRunner(config.luban).export_onnx(
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
    if _export_failed(export_result):
        record["stage"] = "export_failed"
        record["status"] = "failed"
        record["errors"] = list(record.get("errors", [])) + [
            {
                "message": "Remote ONNX export failed. See export.export.stderr in release_record.json.",
            }
        ]
    elif args.dry_run:
        record["stage"] = "export_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "exported"
        record["status"] = "running"
    store.save(record)
    return record


def _command_ifx(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 5,
) -> Dict[str, Any]:
    local_onnx_file = (
        record.get("export", {}).get("local_onnx_file")
        if record is not None
        else args.onnx_file
    )
    if record is not None:
        _validate_upload_binding(args, record)
    if not _confirm(f"Upload {local_onnx_file} and trigger IFX conversion?", args.yes):
        raise RuntimeError("IFX stage cancelled by user.")
    record = _command_upload(
        args,
        config,
        store,
        record=record,
        step_offset=step_offset,
        total_steps=total_steps,
        confirm=False,
    )
    record = _command_ifx_convert(
        args,
        config,
        store,
        record=record,
        step_offset=step_offset + 3,
        total_steps=total_steps,
        confirm=False,
    )
    return record


def _upload_description(args: argparse.Namespace, record: Dict[str, Any]) -> str:
    experiment_name = record.get("experiment", {}).get("name") or "manual_onnx"
    selected_epoch = record.get("selection", {}).get("selected_epoch")
    epoch_text = (
        f"epoch={_format_epoch(selected_epoch)}"
        if selected_epoch is not None
        else "epoch=unknown"
    )
    user_desc = args.desc or record.get("description", "")
    upload_desc = f"{experiment_name}, {epoch_text}"
    if user_desc:
        upload_desc = f"{upload_desc}, {user_desc}"
    return f"{upload_desc}."


def _validate_upload_binding(args: argparse.Namespace, record: Dict[str, Any]) -> None:
    existing_onnx = record.get("ifx", {}).get("onnx") or {}
    existing_version = existing_onnx.get("version")
    truck_runner = record.get("ifx", {}).get("truck_runner") or {}
    existing_is_dry_run = (
        existing_version == 0
        or truck_runner.get("selected") == "dry_run"
        or record.get("stage") == "ifx_upload_dry_run"
    )
    if existing_is_dry_run:
        return
    if existing_version is None or getattr(args, "replace_upload", False):
        return

    requested_version = args.version
    if requested_version is None or requested_version == existing_version:
        raise RuntimeError(
            "This release is already bound to ONNX "
            f"{existing_onnx.get('name') or '<unknown>'} version {existing_version}. "
            "Run ifx-convert next, or pass --replace-upload to explicitly re-upload."
        )
    raise RuntimeError(
        "This release is already bound to ONNX "
        f"{existing_onnx.get('name') or '<unknown>'} version {existing_version}; "
        f"requested version {requested_version}. "
        "Use a new run-id, or pass --replace-upload if you intentionally want to "
        "replace the upload binding."
    )


def _command_upload(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 3,
    confirm: bool = True,
) -> Dict[str, Any]:
    if record is None:
        if not args.onnx_file:
            raise RuntimeError("Provide --onnx-file or --run-id.")
        local_onnx_file = args.onnx_file
        record = store.create(None, args.desc or "")
    else:
        local_onnx_file = record.get("export", {}).get("local_onnx_file")
        if not local_onnx_file:
            raise RuntimeError("No exported ONNX found in release record.")

    _validate_upload_binding(args, record)

    if confirm and not _confirm(f"Upload {local_onnx_file} to truck?", args.yes):
        raise RuntimeError("Upload cancelled by user.")

    record["stage"] = "ifx_uploading"
    record["status"] = "running"
    store.save(record)

    def ifx_progress(title: str, substep: int, detail: Optional[str] = None) -> None:
        _progress(
            args,
            title,
            step=step_offset + substep,
            total=total_steps,
            icon="🚚",
            detail=detail,
        )

    result = IfxPipeline(config.ifx).upload(
        local_onnx_file=local_onnx_file,
        description=_upload_description(args, record),
        version=args.version,
        dry_run=args.dry_run,
        progress=ifx_progress if not getattr(args, "json", False) else None,
        step_offset=step_offset,
    )
    if args.dry_run:
        record["ifx"] = {
            **record.get("ifx", {}),
            "dry_run_upload": result,
        }
        record["stage"] = "ifx_upload_dry_run"
        record["status"] = "dry_run"
    else:
        existing_ifx = {
            key: value
            for key, value in record.get("ifx", {}).items()
            if key not in {"jenkins", "ifx_mapping", "label", "dry_run_upload"}
        }
        record["ifx"] = {**existing_ifx, **result}
        record["stage"] = "ifx_uploaded"
        record["status"] = "running"
    store.save(record)
    return record


def _command_ifx_convert(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 2,
    confirm: bool = True,
) -> Dict[str, Any]:
    if record is None:
        if not args.run_id:
            raise RuntimeError("Provide --run-id.")
        record = store.load(args.run_id)
    if not record.get("ifx", {}).get("onnx"):
        raise RuntimeError("No uploaded ONNX found in release record. Run upload first.")
    if confirm and not _confirm("Trigger IFX conversion from uploaded ONNX?", args.yes):
        raise RuntimeError("IFX conversion cancelled by user.")
    if args.dry_run:
        record = json.loads(json.dumps(record))
    record["stage"] = "ifx_converting"
    record["status"] = "running"
    if not args.dry_run:
        store.save(record)

    def convert_progress(title: str, substep: int, detail: Optional[str] = None) -> None:
        _progress(
            args,
            title,
            step=step_offset + substep,
            total=total_steps,
            icon="🚚",
            detail=detail,
        )

    try:
        result = IfxPipeline(config.ifx).convert(
            upload_result=record.get("ifx", {}),
            dry_run=args.dry_run,
            progress=convert_progress if not getattr(args, "json", False) else None,
            step_offset=0,
        )
    except IfxPipelineError as exc:
        if exc.partial_result:
            record["ifx"] = {**record.get("ifx", {}), **exc.partial_result}
            store.save(record)
        raise
    record["ifx"] = {**record.get("ifx", {}), **result}
    if args.dry_run:
        record["stage"] = "ifx_convert_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "ifx_complete"
        record["status"] = "running"
    if not args.dry_run:
        store.save(record)
    return record


def _command_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    step: int = 1,
    total_steps: int = 1,
) -> Dict[str, Any]:
    ifx_mapping = record.get("ifx", {}).get("ifx_mapping")
    if not ifx_mapping:
        ifx_mapping = record.get("ifx", {}).get("dry_run_mapping", {})
    if not ifx_mapping:
        raise RuntimeError("No IFX mapping found in release record.")
    _progress(args, "Voyager Handoff", step=step, total=total_steps, icon="🧾")
    result = VoyagerHandoffService(config.voyager).generate(
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


def _ifx_mapping_from_record(record: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    ifx_mapping = record.get("ifx", {}).get("ifx_mapping")
    if not ifx_mapping:
        ifx_mapping = record.get("ifx", {}).get("dry_run_mapping", {})
    if not ifx_mapping:
        raise RuntimeError("No IFX mapping found in release record.")
    return ifx_mapping


def _command_apply_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    ifx_mapping = _ifx_mapping_from_record(record)
    branches = [args.branch] if args.branch else [branch.name for branch in config.voyager.branches]
    branch_text = args.branch or f"all-configured ({len(branches)})"
    if not _confirm(
        f"Apply handoff to Voyager MANIFEST and create local commits for {branch_text}?",
        args.yes,
    ):
        raise RuntimeError("apply-handoff cancelled by user.")
    service = VoyagerHandoffService(config.voyager)
    results = []
    failed = None
    for index, branch_name in enumerate(branches, start=1):
        _progress(
            args,
            "Apply Voyager Handoff",
            step=index,
            total=len(branches),
            icon="🧾",
            detail=f"mode: docker; branch: {branch_name}",
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
    result = (
        results[0]
        if args.branch
        else {
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
    )
    record["apply_handoff"] = result
    if failed:
        record["stage"] = "apply_handoff_failed"
        record["status"] = "failed"
        store.add_error(record, "Apply handoff failed. See apply_handoff.stderr.")
    elif args.dry_run:
        record["stage"] = "apply_handoff_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "apply_handoff_complete"
        record["status"] = "completed"
    store.save(record)
    return record


def _command_dcl(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    branches = [args.branch] if args.branch else [branch.name for branch in config.voyager.branches]
    branch_text = args.branch or f"all-configured ({len(branches)})"
    if not _confirm(
        f"Run DCL diff for {branch_text}?",
        args.yes,
    ):
        raise RuntimeError("dcl cancelled by user.")
    service = VoyagerHandoffService(config.voyager)
    results = []
    failed = None
    for index, branch_name in enumerate(branches, start=1):
        _progress(
            args,
            "Run DCL Diff",
            step=index,
            total=len(branches),
            icon="🧾",
            detail=f"mode: docker; branch: {branch_name}",
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


def _command_offboard(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if args.dry_run and record is not None:
        record = json.loads(json.dumps(record))
    if record is None:
        if not args.experiment:
            raise RuntimeError("Provide --experiment or --run-id.")
        _progress(
            args,
            "Inspect Experiment",
            step=1,
            total=2,
            icon="🔎",
            detail=f"experiment: {args.experiment}",
        )
        experiment = ExperimentInspector(
            remote_python_bin=getattr(args, "remote_python", None)
            or config.luban.remote_python_bin
        ).inspect(
            args.experiment, remote_host=getattr(args, "remote", None)
        )
        if args.epoch is None:
            raise RuntimeError("Provide --epoch when no --run-id is used.")
        epoch = args.epoch
        record = store.create(args.experiment, args.desc or "")
        checkpoint = experiment.checkpoint_for_epoch(int(epoch))
        remote_host = experiment.remote_host
    else:
        _progress(
            args,
            "Inspect Experiment",
            step=1,
            total=2,
            icon="🔎",
            detail=f"experiment: {record['experiment_path']}",
        )
        experiment = ExperimentInspector(
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
    if not _confirm(f"Run offboard test with {checkpoint.name}?", args.yes):
        raise RuntimeError("Offboard test cancelled by user.")
    _progress(
        args,
        "Offboard Test",
        step=2,
        total=2,
        icon="🧪",
        detail=f"host: {remote_host or config.luban.host_alias}",
    )
    result = LubanRunner(config.luban).run_offboard_test(
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


def _resume(
    args: argparse.Namespace, config: ReleaseConfig, store: StateStore
) -> Dict[str, Any]:
    record = store.load(args.run_id)
    if not getattr(args, "remote", None):
        args.remote = record.get("experiment", {}).get("remote_host")
    if not getattr(args, "remote_python", None):
        args.remote_python = config.luban.remote_python_bin
    if not record.get("export", {}).get("local_onnx_file"):
        args.experiment = record["experiment_path"]
        record = _command_export(args, config, store, record=record)
    if _record_failed(record):
        return record
    if not record.get("ifx", {}).get("ifx_mapping"):
        record = _command_ifx(
            args, config, store, record=record, step_offset=0, total_steps=6
        )
    if not record.get("handoff", {}).get("commands_file"):
        record = _command_handoff(args, config, store, record, step=6, total_steps=6)
    return record


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Print JSON output")
    common.add_argument("--yes", action="store_true", help="Auto-confirm prompts")

    parser = argparse.ArgumentParser(description="Scenario DNN release pipeline")
    parser.add_argument("--config", help="Path to YAML config file")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--yes", action="store_true", help="Auto-confirm prompts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", parents=[common], help="Inspect an experiment"
    )
    inspect_parser.add_argument("--experiment", required=True)
    inspect_parser.add_argument("--remote", help="SSH host alias for remote inspect")
    inspect_parser.add_argument("--remote-python", help="Python command on remote host")

    pick_parser = subparsers.add_parser(
        "pick", parents=[common], help="Recommend epochs"
    )
    pick_parser.add_argument("--experiment", required=True)
    pick_parser.add_argument("--remote", help="SSH host alias for remote inspect")
    pick_parser.add_argument("--remote-python", help="Python command on remote host")
    pick_parser.add_argument("--policy", choices=["precision_first", "recall_first"])
    pick_parser.add_argument("--top-n", type=int)
    pick_parser.add_argument(
        "--loss-tolerance-pct",
        type=float,
        help="TensorBoard fallback loss tolerance, e.g. 0.05 keeps epochs within 5%% of min val loss",
    )

    export_parser = subparsers.add_parser(
        "export", parents=[common], help="Export ONNX from Luban"
    )
    export_parser.add_argument("--experiment", required=True)
    export_parser.add_argument("--remote", help="SSH host alias for remote inspect/export")
    export_parser.add_argument("--remote-python", help="Python command on remote host")
    export_parser.add_argument("--task", help="Task/head to use for auto epoch selection")
    export_parser.add_argument("--epoch", type=int)
    export_parser.add_argument("--policy", choices=["precision_first", "recall_first"])
    export_parser.add_argument("--top-n", type=int)
    export_parser.add_argument("--loss-tolerance-pct", type=float)
    export_parser.add_argument("--desc", default="")
    export_parser.add_argument("--dry-run", action="store_true")

    ifx_parser = subparsers.add_parser(
        "ifx", parents=[common], help="Push ONNX and trigger IFX"
    )
    ifx_parser.add_argument("--run-id")
    ifx_parser.add_argument("--onnx-file")
    ifx_parser.add_argument("--desc", default="")
    ifx_parser.add_argument(
        "--version",
        "--onnx-version",
        dest="version",
        type=int,
        help="Explicit ONNX fileserver version. Defaults to latest+1.",
    )
    ifx_parser.add_argument(
        "--replace-upload",
        action="store_true",
        help="Allow replacing an existing ONNX upload binding in this run record.",
    )
    ifx_parser.add_argument("--dry-run", action="store_true")

    upload_parser = subparsers.add_parser(
        "upload",
        aliases=["ifx-upload"],
        parents=[common],
        help="Upload ONNX to truck and prepare precision test",
    )
    upload_parser.add_argument("--run-id")
    upload_parser.add_argument("--onnx-file")
    upload_parser.add_argument("--desc", default="")
    upload_parser.add_argument(
        "--version",
        "--onnx-version",
        dest="version",
        type=int,
        help="Explicit ONNX fileserver version. Defaults to latest+1.",
    )
    upload_parser.add_argument(
        "--replace-upload",
        action="store_true",
        help="Allow replacing an existing ONNX upload binding in this run record.",
    )
    upload_parser.add_argument("--dry-run", action="store_true")

    convert_parser = subparsers.add_parser(
        "ifx-convert",
        parents=[common],
        help="Trigger Jenkins IFX from an uploaded ONNX",
    )
    convert_parser.add_argument("--run-id", required=True)
    convert_parser.add_argument("--dry-run", action="store_true")

    handoff_parser = subparsers.add_parser(
        "handoff", parents=[common], help="Generate Voyager handoff files"
    )
    handoff_parser.add_argument("--run-id", required=True)
    handoff_parser.add_argument("--desc", default="")

    apply_handoff_parser = subparsers.add_parser(
        "apply-handoff",
        parents=[common],
        help="Apply Voyager MANIFEST changes in docker and create a commit",
    )
    apply_handoff_parser.add_argument("--run-id", required=True)
    apply_handoff_parser.add_argument(
        "--branch",
        help="Configured branch name or checkout branch. If omitted, apply all configured branches in order.",
    )
    apply_handoff_parser.add_argument(
        "--docker",
        help="Voyager docker container. Defaults to CONTAINER_NAME_GEN4 or config.",
    )
    apply_handoff_parser.add_argument("--desc", default="")
    apply_handoff_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apply in-memory check and show diff without committing.",
    )
    apply_handoff_parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Modify MANIFEST but skip git add/commit.",
    )
    apply_handoff_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow applying when the Voyager worktree already has changes.",
    )
    apply_handoff_parser.add_argument(
        "--allow-append",
        action="store_true",
        help="Append missing MANIFEST targets instead of failing.",
    )

    dcl_parser = subparsers.add_parser(
        "dcl",
        parents=[common],
        help="Run Voyager DCL diff in docker for applied handoff commits",
    )
    dcl_parser.add_argument("--run-id", required=True)
    dcl_parser.add_argument(
        "--branch",
        help="Configured branch name or checkout branch. If omitted, run all configured branches in order.",
    )
    dcl_parser.add_argument(
        "--docker",
        help="Voyager docker container. Defaults to CONTAINER_NAME_GEN4 or config.",
    )
    dcl_parser.add_argument("--dry-run", action="store_true")
    dcl_parser.add_argument(
        "--lint",
        action="store_true",
        help="Run dcl lint before dcl diff. Default is --nolint.",
    )
    dcl_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow running when the Voyager worktree already has changes.",
    )

    release_parser = subparsers.add_parser(
        "release", parents=[common], help="Run export -> ifx -> handoff"
    )
    release_parser.add_argument("--experiment", required=True)
    release_parser.add_argument("--remote", help="SSH host alias for remote inspect/export")
    release_parser.add_argument("--remote-python", help="Python command on remote host")
    release_parser.add_argument("--task", help="Task/head to use for auto epoch selection")
    release_parser.add_argument("--epoch", type=int)
    release_parser.add_argument("--policy", choices=["precision_first", "recall_first"])
    release_parser.add_argument("--top-n", type=int)
    release_parser.add_argument("--loss-tolerance-pct", type=float)
    release_parser.add_argument("--desc", default="")
    release_parser.add_argument(
        "--version",
        "--onnx-version",
        dest="version",
        type=int,
        help="Explicit ONNX fileserver version. Defaults to latest+1.",
    )
    release_parser.add_argument("--dry-run", action="store_true")

    resume_parser = subparsers.add_parser(
        "resume", parents=[common], help="Resume a previous release"
    )
    resume_parser.add_argument("--run-id", required=True)
    resume_parser.add_argument("--remote", help="SSH host alias override")
    resume_parser.add_argument("--remote-python", help="Python command on remote host")
    resume_parser.add_argument("--task", help="Task/head to use for auto epoch selection")
    resume_parser.add_argument("--desc", default="")
    resume_parser.add_argument("--epoch", type=int)
    resume_parser.add_argument("--loss-tolerance-pct", type=float)
    resume_parser.add_argument(
        "--version",
        "--onnx-version",
        dest="version",
        type=int,
        help="Explicit ONNX fileserver version. Defaults to latest+1.",
    )
    resume_parser.add_argument("--dry-run", action="store_true")

    offboard_parser = subparsers.add_parser(
        "offboard", parents=[common], help="Run offboard test on Luban"
    )
    offboard_parser.add_argument("--run-id")
    offboard_parser.add_argument("--experiment")
    offboard_parser.add_argument("--remote", help="SSH host alias for remote inspect/offboard")
    offboard_parser.add_argument("--remote-python", help="Python command on remote host")
    offboard_parser.add_argument("--epoch", type=int)
    offboard_parser.add_argument("--desc", default="")
    offboard_parser.add_argument("--dry-run", action="store_true")

    config_parser = subparsers.add_parser(
        "print-config", parents=[common], help="Show bundled config"
    )
    config_parser.add_argument("--copy", action="store_true")

    web_parser = subparsers.add_parser(
        "web", parents=[common], help="Start the read-only release web console"
    )
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument(
        "--open",
        action="store_true",
        help="Open the console in the default browser",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    store = _build_store(config)
    try:
        if args.command == "inspect":
            _progress(
                args,
                "Inspect Experiment",
                blank_before=False,
                icon="🔎",
                detail=f"experiment: {args.experiment}",
            )
            experiment, _ = _inspect_and_pick(
                args.experiment,
                config,
                remote=args.remote,
                remote_python=args.remote_python,
            )
            if args.json:
                _print(experiment, as_json=True)
            else:
                print(_format_inspect_result(experiment))
            return 0
        if args.command == "pick":
            _progress(
                args,
                "Inspect And Rank Epochs",
                blank_before=False,
                icon="🏁",
                detail=f"experiment: {args.experiment}",
            )
            _, pick_result = _inspect_and_pick(
                args.experiment,
                config,
                policy=args.policy,
                top_n=args.top_n,
                loss_tolerance_pct=args.loss_tolerance_pct,
                remote=args.remote,
                remote_python=args.remote_python,
            )
            if args.json:
                _print(pick_result, as_json=True)
            else:
                print(_format_pick_result(pick_result))
            return 0
        if args.command == "export":
            record = _command_export(args, config, store)
            _print_record(record, as_json=args.json)
            return 1 if _record_failed(record) else 0
        if args.command == "ifx":
            record = store.load(args.run_id) if args.run_id else None
            _print_record(
                _command_ifx(args, config, store, record, step_offset=0, total_steps=5),
                as_json=args.json,
            )
            return 0
        if args.command in {"upload", "ifx-upload"}:
            record = store.load(args.run_id) if args.run_id else None
            _print_record(
                _command_upload(
                    args,
                    config,
                    store,
                    record,
                    step_offset=0,
                    total_steps=3,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "ifx-convert":
            record = store.load(args.run_id)
            _print_record(
                _command_ifx_convert(
                    args,
                    config,
                    store,
                    record,
                    step_offset=0,
                    total_steps=2,
                ),
                as_json=args.json,
            )
            return 0
        if args.command == "handoff":
            record = store.load(args.run_id)
            _print_record(
                _command_handoff(args, config, store, record, step=1, total_steps=1),
                as_json=args.json,
            )
            return 0
        if args.command == "apply-handoff":
            record = store.load(args.run_id)
            _print_record(
                _command_apply_handoff(args, config, store, record),
                as_json=args.json,
            )
            return 0
        if args.command == "dcl":
            record = store.load(args.run_id)
            _print_record(
                _command_dcl(args, config, store, record),
                as_json=args.json,
            )
            return 0
        if args.command == "release":
            record = _command_export(
                args, config, store, step_offset=0, total_steps=9
            )
            if _record_failed(record):
                _print_record(record, as_json=args.json)
                return 1
            record = _command_ifx(
                args, config, store, record, step_offset=3, total_steps=9
            )
            record = _command_handoff(
                args, config, store, record, step=9, total_steps=9
            )
            _print_record(record, as_json=args.json)
            return 0
        if args.command == "resume":
            record = _resume(args, config, store)
            _print_record(record, as_json=args.json)
            return 1 if _record_failed(record) else 0
        if args.command == "offboard":
            record = store.load(args.run_id) if args.run_id else None
            record = _command_offboard(args, config, store, record)
            _print_record(record, as_json=args.json)
            return 1 if _record_failed(record) else 0
        if args.command == "print-config":
            if args.copy:
                target = Path.cwd() / "scenario_dnn_release.yaml"
                target.write_text(
                    DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                print(target)
            else:
                print(DEFAULT_TEMPLATE_PATH)
            return 0
        if args.command == "web":
            serve_web(
                config,
                host=args.host,
                port=args.port,
                open_browser=args.open,
                config_path=args.config,
            )
            return 0
    except Exception as exc:  # pylint: disable=broad-except
        if getattr(args, "run_id", None):
            try:
                record = store.load(args.run_id)
                store.add_error(record, str(exc))
            except Exception:
                pass
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
