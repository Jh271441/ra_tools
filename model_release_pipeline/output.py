"""Human-readable CLI formatting helpers."""

from __future__ import annotations

import shutil
import sys
from typing import Any, Dict, Optional


def separator(char: str = "=") -> str:
    columns = shutil.get_terminal_size((100, 20)).columns
    return char * max(40, int(columns * 0.9))


def progress(
    args: Any,
    title: str,
    step: Optional[int] = None,
    total: Optional[int] = None,
    blank_before: bool = True,
    icon: str = "▶",
    detail: Optional[str] = None,
) -> None:
    if getattr(args, "json", False):
        return
    title = title.strip().rstrip(".")
    spacer = "\n" if blank_before else ""
    print(f"{spacer}{separator('=')}", file=sys.stderr, flush=True)
    print(f"{icon} {title}", file=sys.stderr, flush=True)
    if step is not None and total is not None:
        print(f"step: {step}/{total}", file=sys.stderr, flush=True)
        print(f"tasks_remaining: {max(total - step, 0)}", file=sys.stderr, flush=True)
    if detail:
        print(detail, file=sys.stderr, flush=True)
    print(separator("="), file=sys.stderr, flush=True)

DISPLAY_METRICS = ("roc_auc", "pr_auc", "accuracy", "f1_score", "precision", "recall")


def format_number(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.5f}"
    return str(value)


def format_epoch(epoch: Any) -> str:
    try:
        return f"{int(epoch):03d}"
    except (TypeError, ValueError):
        return str(epoch)


def candidate_metric_text(candidate: Dict[str, Any], first_metric: str) -> str:
    fields = [first_metric] + [
        metric for metric in DISPLAY_METRICS if metric != first_metric
    ]
    return " | ".join(
        f"{metric if metric != 'f1_score' else 'f1'}={format_number(candidate.get(metric))}"
        for metric in fields
        if candidate.get(metric) is not None
    )


def format_top_by_metric(
    task: str, candidates: list[Dict[str, Any]], metric: str, top_n: int
) -> str:
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
            f"[{index:02d}] Epoch {format_epoch(candidate.get('epoch'))} | "
            f"{candidate_metric_text(candidate, metric)}"
        )
    return "\n".join(lines)


def format_task_sections(
    task: str, task_result: Dict[str, Any], top_n: int, policy: str
) -> str:
    candidates = task_result.get("all_candidates", [])
    metric_candidates = [
        candidate
        for candidate in candidates
        if any(candidate.get(metric) is not None for metric in DISPLAY_METRICS)
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
        if (section := format_top_by_metric(task, metric_candidates, metric, top_n))
    ]
    if not sections:
        fallback = [
            candidate
            for candidate in task_result.get("candidates", [])
            if any(candidate.get(metric) is not None for metric in DISPLAY_METRICS)
        ]
        if not fallback:
            return f"===== {task}: No parsed metrics ====="
        lines = [f"===== {task}: Top {len(fallback)} by picker score ====="]
        for index, candidate in enumerate(fallback, 1):
            lines.append(
                f"[{index:02d}] Epoch {format_epoch(candidate.get('epoch'))} | "
                f"{candidate_metric_text(candidate, 'precision')}"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def format_combined_recommendations(
    pick_result: Dict[str, Any], top_n: int
) -> str:
    combined = pick_result.get("combined_recommendations") or []
    if not combined:
        return ""
    lines = ["===== Selected Epochs (primary stuck_detect precision weighted) =====", ""]
    for item in combined[:top_n]:
        epoch = item.get("epoch")
        lines.append(
            f"Epoch {format_epoch(epoch)} | TOTAL={item.get('total_rank')} | "
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
                    f"{metric if metric != 'f1_score' else 'f1'}={format_number(metrics.get(metric))}"
                    for metric in DISPLAY_METRICS
                    if metrics.get(metric) is not None
                )
            )
        lines.append("-" * 90)
    return "\n".join(lines)


def format_tensorboard_fallbacks(pick_result: Dict[str, Any]) -> str:
    lines = []
    for task, task_result in pick_result.get("per_task", {}).items():
        fallback = task_result.get("tensorboard_loss_window")
        if not fallback:
            continue
        candidate = fallback.get("candidate", {})
        if not lines:
            lines.extend(["===== TensorBoard Val-Loss Tolerance Fallback =====", ""])
        lines.append(
            f"{task}: min_loss_epoch={format_epoch(fallback.get('min_loss_epoch'))} | "
            f"min_loss={format_number(fallback.get('min_loss'))} | "
            f"loss_tolerance={format_number(fallback.get('loss_tolerance_pct'))} | "
            f"max_loss={format_number(fallback.get('max_allowed_loss'))} | "
            f"candidates={fallback.get('candidate_count')} | "
            f"recommended_epoch={format_epoch(fallback.get('recommended_epoch'))}"
        )
        lines.append(
            "  "
            + " | ".join(
                f"{metric if metric != 'f1_score' else 'f1'}={format_number(candidate.get(metric))}"
                for metric in ("loss", "precision", "recall", "pr_auc", "roc_auc")
                if candidate.get(metric) is not None
            )
        )
    return "\n".join(lines)


def format_pick_result(pick_result: Dict[str, Any]) -> str:
    top_n = int(pick_result.get("top_n") or 3)
    policy = str(pick_result.get("policy") or "precision_first")
    lines = [
        f"Policy: {policy}",
        f"Tasks: {', '.join(pick_result.get('tasks', [])) or '<none>'}",
        "",
    ]
    for task, task_result in pick_result.get("per_task", {}).items():
        lines.append(format_task_sections(task, task_result, top_n, policy))
        lines.append("")

    combined = format_combined_recommendations(pick_result, top_n)
    if combined:
        lines.append(combined)
        lines.append("")

    tensorboard_fallbacks = format_tensorboard_fallbacks(pick_result)
    if tensorboard_fallbacks:
        lines.append(tensorboard_fallbacks)
        lines.append("")

    recommended_epoch = pick_result.get("recommended_epoch")
    if recommended_epoch is None and len(pick_result.get("per_task", {})) == 1:
        only_task_result = next(iter(pick_result["per_task"].values()))
        recommended_epoch = only_task_result.get("recommended_epoch")
    lines.append(f"Recommended epoch: {format_epoch(recommended_epoch)}")
    if pick_result.get("notes"):
        lines.append("")
        lines.extend(f"Note: {note}" for note in pick_result["notes"])
    return "\n".join(line for line in lines if line is not None)


def command_state(result: Optional[Dict[str, Any]]) -> str:
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


def tail_text(text: Any, max_lines: int = 8) -> list[str]:
    lines = str(text or "").strip().splitlines()
    if len(lines) > max_lines:
        return ["..."] + lines[-max_lines:]
    return lines


def append_command_result(
    lines: list[str],
    label: str,
    result: Optional[Dict[str, Any]],
    show_error: bool = True,
) -> None:
    state = command_state(result)
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
        stderr_tail = tail_text(result.get("stderr"))
        if stderr_tail:
            lines.append("  stderr:")
            lines.extend(f"  {line}" for line in stderr_tail)


def format_record_result(record: Dict[str, Any]) -> str:
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
            f"selected epoch: {format_epoch(selection.get('selected_epoch'))} "
            f"({selection.get('selection_source') or 'unknown'})"
        )

    export = record.get("export") or {}
    if export:
        append_command_result(lines, "remote export", export.get("export"))
        append_command_result(lines, "scp onnx", export.get("scp"), show_error=False)
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
        append_command_result(lines, "apply handoff", apply_handoff)
        if apply_handoff.get("results"):
            lines.append(
                "  branches: "
                f"{len(apply_handoff.get('results') or [])} attempted"
            )
            for item in apply_handoff.get("results", []):
                state = command_state(item)
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
        append_command_result(lines, "dcl", dcl)
        if dcl.get("results"):
            lines.append("  branches: " f"{len(dcl.get('results') or [])} attempted")
            for item in dcl.get("results", []):
                state = command_state(item)
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
        append_command_result(lines, "offboard", offboard)

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


def format_inspect_result(experiment: Dict[str, Any]) -> str:
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
