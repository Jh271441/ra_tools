"""CLI for scenario dnn release tooling."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from model_release_pipeline.config import (
    DEFAULT_TEMPLATE_PATH,
    ReleaseConfig,
    load_config,
)
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.ifx_pipeline import IfxPipeline
from model_release_pipeline.services.luban_runner import LubanRunner
from model_release_pipeline.services.model_picker import ModelPicker
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore


_DISPLAY_METRICS = ("roc_auc", "pr_auc", "accuracy", "f1_score", "precision", "recall")


def _print(payload: Any, as_json: bool = False) -> None:
    if as_json or isinstance(payload, dict):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(payload)


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
) -> Dict[str, Any]:
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
    export_result = LubanRunner(config.luban).export_onnx(
        experiment=experiment,
        checkpoint_path=checkpoint,
        onnx_file_name=config.onnx_file_name,
        local_output_dir=store.run_dir(record["release_id"]) / "artifacts",
        dry_run=args.dry_run,
    )
    record["export"] = export_result
    record["stage"] = "exported"
    store.save(record)
    return record


def _command_ifx(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
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

    if not _confirm(f"Push {local_onnx_file} and trigger IFX conversion?", args.yes):
        raise RuntimeError("IFX stage cancelled by user.")
    record["stage"] = "ifx_running"
    record["status"] = "running"
    store.save(record)
    result = IfxPipeline(config.ifx).run(
        local_onnx_file=local_onnx_file,
        description=args.desc or record.get("description", ""),
        version=args.version,
        dry_run=args.dry_run,
    )
    record["ifx"] = result
    record["stage"] = "ifx_complete"
    store.save(record)
    return record


def _command_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    ifx_mapping = record.get("ifx", {}).get("ifx_mapping")
    if not ifx_mapping:
        ifx_mapping = record.get("ifx", {}).get("dry_run_mapping", {})
    if not ifx_mapping:
        raise RuntimeError("No IFX mapping found in release record.")
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


def _command_offboard(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if record is None:
        if not args.experiment:
            raise RuntimeError("Provide --experiment or --run-id.")
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
    else:
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
    if checkpoint is None:
        raise RuntimeError(f"Checkpoint for epoch {epoch} not found.")
    if not _confirm(f"Run offboard test with {checkpoint.name}?", args.yes):
        raise RuntimeError("Offboard test cancelled by user.")
    result = LubanRunner(config.luban).run_offboard_test(
        checkpoint_path=checkpoint,
        remote_host=experiment.remote_host,
        dry_run=args.dry_run,
    )
    record["offboard"] = result
    record["stage"] = "offboard_complete"
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
    if not record.get("ifx", {}).get("ifx_mapping"):
        record = _command_ifx(args, config, store, record=record)
    if not record.get("handoff", {}).get("commands_file"):
        record = _command_handoff(args, config, store, record)
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
    ifx_parser.add_argument("--version", type=int)
    ifx_parser.add_argument("--dry-run", action="store_true")

    handoff_parser = subparsers.add_parser(
        "handoff", parents=[common], help="Generate Voyager handoff files"
    )
    handoff_parser.add_argument("--run-id", required=True)
    handoff_parser.add_argument("--desc", default="")

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
    release_parser.add_argument("--version", type=int)
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
    resume_parser.add_argument("--version", type=int)
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
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    store = _build_store(config)
    try:
        if args.command == "inspect":
            experiment, _ = _inspect_and_pick(
                args.experiment,
                config,
                remote=args.remote,
                remote_python=args.remote_python,
            )
            _print(experiment, as_json=args.json)
            return 0
        if args.command == "pick":
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
            _print(_command_export(args, config, store), as_json=args.json)
            return 0
        if args.command == "ifx":
            record = store.load(args.run_id) if args.run_id else None
            _print(_command_ifx(args, config, store, record), as_json=args.json)
            return 0
        if args.command == "handoff":
            record = store.load(args.run_id)
            _print(_command_handoff(args, config, store, record), as_json=args.json)
            return 0
        if args.command == "release":
            record = _command_export(args, config, store)
            record = _command_ifx(args, config, store, record)
            record = _command_handoff(args, config, store, record)
            _print(record, as_json=args.json)
            return 0
        if args.command == "resume":
            _print(_resume(args, config, store), as_json=args.json)
            return 0
        if args.command == "offboard":
            record = store.load(args.run_id) if args.run_id else None
            _print(_command_offboard(args, config, store, record), as_json=args.json)
            return 0
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
