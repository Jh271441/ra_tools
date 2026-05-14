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
from model_release_pipeline.onboard.export import (
    export_failed,
    run_export,
    select_candidate,
    select_manual_epoch_candidate,
)
from model_release_pipeline.onboard.handoff import (
    ifx_mapping_from_record,
    run_apply_handoff,
    run_dcl,
    run_handoff,
)
from model_release_pipeline.onboard.parser import build_parser
from model_release_pipeline.onboard.upload import (
    run_ifx_poll,
    run_ifx_convert,
    run_upload,
    upload_description,
    validate_upload_binding,
)
from model_release_pipeline.offboard.runner import run_offboard
from model_release_pipeline.output import (
    append_command_result as output_append_command_result,
    candidate_metric_text as output_candidate_metric_text,
    command_state as output_command_state,
    format_combined_recommendations as output_format_combined_recommendations,
    format_epoch as output_format_epoch,
    format_inspect_result as output_format_inspect_result,
    format_number as output_format_number,
    format_pick_result as output_format_pick_result,
    format_record_result as output_format_record_result,
    format_task_sections as output_format_task_sections,
    format_tensorboard_fallbacks as output_format_tensorboard_fallbacks,
    format_top_by_metric as output_format_top_by_metric,
    tail_text as output_tail_text,
)
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.ifx_pipeline import IfxPipeline, IfxPipelineError
from model_release_pipeline.services.luban_runner import LubanRunner
from model_release_pipeline.services.model_picker import ModelPicker
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore
from model_release_pipeline.web_app import serve as serve_web


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
    return output_format_number(value)


def _format_epoch(epoch: Any) -> str:
    return output_format_epoch(epoch)


def _candidate_metric_text(candidate: Dict[str, Any], first_metric: str) -> str:
    return output_candidate_metric_text(candidate, first_metric)


def _format_top_by_metric(task: str, candidates: list[Dict[str, Any]], metric: str, top_n: int) -> str:
    return output_format_top_by_metric(task, candidates, metric, top_n)


def _format_task_sections(task: str, task_result: Dict[str, Any], top_n: int, policy: str) -> str:
    return output_format_task_sections(task, task_result, top_n, policy)


def _format_combined_recommendations(pick_result: Dict[str, Any], top_n: int) -> str:
    return output_format_combined_recommendations(pick_result, top_n)


def _format_tensorboard_fallbacks(pick_result: Dict[str, Any]) -> str:
    return output_format_tensorboard_fallbacks(pick_result)


def _format_pick_result(pick_result: Dict[str, Any]) -> str:
    return output_format_pick_result(pick_result)


def _command_state(result: Optional[Dict[str, Any]]) -> str:
    return output_command_state(result)


def _tail_text(text: Any, max_lines: int = 8) -> list[str]:
    return output_tail_text(text, max_lines=max_lines)


def _append_command_result(
    lines: list[str],
    label: str,
    result: Optional[Dict[str, Any]],
    show_error: bool = True,
) -> None:
    output_append_command_result(lines, label, result, show_error=show_error)


def _format_record_result(record: Dict[str, Any]) -> str:
    return output_format_record_result(record)


def _format_inspect_result(experiment: Dict[str, Any]) -> str:
    return output_format_inspect_result(experiment)


def _print_record(record: Dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        _print(record, as_json=True)
    else:
        print("\n" + _format_record_result(record))


def _record_failed(record: Dict[str, Any]) -> bool:
    return record.get("status") == "failed"


def _export_failed(export_result: Dict[str, Any]) -> bool:
    return export_failed(export_result)



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
    return select_candidate(pick_result, experiment_path, epoch, task)


def _select_manual_epoch_candidate(
    experiment: Any,
    experiment_path: str,
    epoch: int,
) -> Dict[str, Any]:
    return select_manual_epoch_candidate(experiment, experiment_path, epoch)


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
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        step: Optional[int],
        total: Optional[int],
        icon: str,
        detail: Optional[str],
        blank_before: bool,
    ) -> None:
        _progress(
            progress_args,
            title,
            step=step,
            total=total,
            blank_before=blank_before,
            icon=icon,
            detail=detail,
        )

    return run_export(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        progress=progress,
        confirm=_confirm,
        format_epoch=_format_epoch,
        inspector_cls=ExperimentInspector,
        picker_cls=ModelPicker,
        luban_runner_cls=LubanRunner,
    )


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
    return upload_description(args, record, format_epoch=_format_epoch)


def _validate_upload_binding(args: argparse.Namespace, record: Dict[str, Any]) -> None:
    validate_upload_binding(args, record)


def _command_upload(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 3,
    confirm: bool = True,
) -> Dict[str, Any]:
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        step: int,
        total: int,
        icon: str,
        detail: Optional[str],
    ) -> None:
        _progress(
            progress_args,
            title,
            step=step,
            total=total,
            icon=icon,
            detail=detail,
        )

    return run_upload(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        confirm_upload=confirm,
        progress=progress,
        confirm=_confirm,
        format_epoch=_format_epoch,
        ifx_pipeline_cls=IfxPipeline,
    )


def _command_ifx_convert(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 2,
    confirm: bool = True,
) -> Dict[str, Any]:
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        step: int,
        total: int,
        icon: str,
        detail: Optional[str],
    ) -> None:
        _progress(
            progress_args,
            title,
            step=step,
            total=total,
            icon=icon,
            detail=detail,
        )

    return run_ifx_convert(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        confirm_convert=confirm,
        progress=progress,
        confirm=_confirm,
        ifx_pipeline_cls=IfxPipeline,
        ifx_pipeline_error_cls=IfxPipelineError,
    )


def _command_ifx_poll(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 1,
) -> Dict[str, Any]:
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        step: int,
        total: int,
        icon: str,
        detail: Optional[str],
    ) -> None:
        _progress(
            progress_args,
            title,
            step=step,
            total=total,
            icon=icon,
            detail=detail,
        )

    return run_ifx_poll(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        progress=progress,
        ifx_pipeline_cls=IfxPipeline,
        ifx_pipeline_error_cls=IfxPipelineError,
    )


def _command_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    step: int = 1,
    total_steps: int = 1,
) -> Dict[str, Any]:
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        substep: int,
        total: int,
        icon: str,
        detail: str,
    ) -> None:
        _progress(
            progress_args,
            title,
            step=substep,
            total=total,
            icon=icon,
            detail=detail or None,
        )

    return run_handoff(
        args,
        config,
        store,
        record,
        step=step,
        total_steps=total_steps,
        progress=progress,
        service_cls=VoyagerHandoffService,
    )


def _ifx_mapping_from_record(record: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return ifx_mapping_from_record(record)


def _command_apply_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        step: int,
        total: int,
        icon: str,
        detail: str,
    ) -> None:
        _progress(
            progress_args,
            title,
            step=step,
            total=total,
            icon=icon,
            detail=detail,
        )

    return run_apply_handoff(
        args,
        config,
        store,
        record,
        progress=progress,
        confirm=_confirm,
        service_cls=VoyagerHandoffService,
    )


def _command_dcl(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        step: int,
        total: int,
        icon: str,
        detail: str,
    ) -> None:
        _progress(
            progress_args,
            title,
            step=step,
            total=total,
            icon=icon,
            detail=detail,
        )

    return run_dcl(
        args,
        config,
        store,
        record,
        progress=progress,
        confirm=_confirm,
        service_cls=VoyagerHandoffService,
    )


def _command_offboard(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    def progress(
        progress_args: argparse.Namespace,
        title: str,
        step: int,
        total: int,
        icon: str,
        detail: str,
    ) -> None:
        _progress(
            progress_args,
            title,
            step=step,
            total=total,
            icon=icon,
            detail=detail,
        )

    return run_offboard(
        args,
        config,
        store,
        record,
        progress=progress,
        confirm=_confirm,
        inspector_cls=ExperimentInspector,
        luban_runner_cls=LubanRunner,
    )


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
        if args.command == "ifx-poll":
            record = store.load(args.run_id)
            _print_record(
                _command_ifx_poll(args, config, store, record),
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
