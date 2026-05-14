"""Central dispatch for all record-mutating pipeline commands."""

from __future__ import annotations

import argparse
from typing import Any, Dict, Optional, Tuple

from model_release_pipeline.config import ReleaseConfig
from model_release_pipeline.output import format_epoch, progress as _progress
from model_release_pipeline.onboard.export import (
    export_failed,
    run_export,
    run_pick,
    select_candidate,
    select_manual_epoch_candidate,
)
from model_release_pipeline.onboard.handoff import (
    run_apply_handoff,
    run_dcl,
    run_handoff,
)
from model_release_pipeline.onboard.upload import (
    run_ifx_convert,
    run_ifx_poll,
    run_upload,
    validate_upload_binding,
)
from model_release_pipeline.offboard.runner import run_offboard
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.ifx_pipeline import IfxPipeline, IfxPipelineError
from model_release_pipeline.services.luban_runner import LubanRunner
from model_release_pipeline.services.model_picker import ModelPicker
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _make_progress(args: argparse.Namespace):
    def _prog(
        progress_args: argparse.Namespace,
        title: str,
        step: Optional[int] = None,
        total: Optional[int] = None,
        icon: str = "▶",
        detail: Optional[str] = None,
        blank_before: bool = True,
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
    return _prog


def _run_pick(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return run_pick(
        args,
        config,
        store,
        record,
        progress=_make_progress(args),
        inspector_cls=ExperimentInspector,
        picker_cls=ModelPicker,
    )


def _run_export(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 3,
) -> Dict[str, Any]:
    return run_export(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        progress=_make_progress(args),
        confirm=_confirm,
        format_epoch=format_epoch,
        inspector_cls=ExperimentInspector,
        picker_cls=ModelPicker,
        luban_runner_cls=LubanRunner,
    )


def _run_upload(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 3,
    confirm: bool = True,
) -> Dict[str, Any]:
    return run_upload(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        confirm_upload=confirm,
        progress=_make_progress(args),
        confirm=_confirm,
        format_epoch=format_epoch,
        ifx_pipeline_cls=IfxPipeline,
    )


def _run_ifx_convert(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 2,
    confirm: bool = True,
) -> Dict[str, Any]:
    return run_ifx_convert(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        confirm_convert=confirm,
        progress=_make_progress(args),
        confirm=_confirm,
        ifx_pipeline_cls=IfxPipeline,
        ifx_pipeline_error_cls=IfxPipelineError,
    )


def _run_ifx_poll(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    step_offset: int = 0,
    total_steps: int = 1,
) -> Dict[str, Any]:
    return run_ifx_poll(
        args,
        config,
        store,
        record,
        step_offset=step_offset,
        total_steps=total_steps,
        progress=_make_progress(args),
        ifx_pipeline_cls=IfxPipeline,
        ifx_pipeline_error_cls=IfxPipelineError,
    )


def _run_ifx(
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
        validate_upload_binding(args, record)
    if not _confirm(f"Upload {local_onnx_file} and trigger IFX conversion?", args.yes):
        raise RuntimeError("IFX stage cancelled by user.")
    record = _run_upload(
        args,
        config,
        store,
        record=record,
        step_offset=step_offset,
        total_steps=total_steps,
        confirm=False,
    )
    return _run_ifx_convert(
        args,
        config,
        store,
        record=record,
        step_offset=step_offset + 3,
        total_steps=total_steps,
        confirm=False,
    )


def _run_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    step: int = 1,
    total_steps: int = 1,
) -> Dict[str, Any]:
    return run_handoff(
        args,
        config,
        store,
        record,
        step=step,
        total_steps=total_steps,
        progress=_make_progress(args),
        service_cls=VoyagerHandoffService,
    )


def _run_apply_handoff(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    return run_apply_handoff(
        args,
        config,
        store,
        record,
        progress=_make_progress(args),
        confirm=_confirm,
        service_cls=VoyagerHandoffService,
    )


def _run_dcl(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    return run_dcl(
        args,
        config,
        store,
        record,
        progress=_make_progress(args),
        confirm=_confirm,
        service_cls=VoyagerHandoffService,
    )


def _run_offboard(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return run_offboard(
        args,
        config,
        store,
        record,
        progress=_make_progress(args),
        confirm=_confirm,
        inspector_cls=ExperimentInspector,
        luban_runner_cls=LubanRunner,
    )


def _resume(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
) -> Dict[str, Any]:
    record = store.load(args.run_id)
    if not getattr(args, "remote", None):
        args.remote = record.get("experiment", {}).get("remote_host")
    if not getattr(args, "remote_python", None):
        args.remote_python = config.luban.remote_python_bin
    if not record.get("export", {}).get("local_onnx_file"):
        args.experiment = record["experiment_path"]
        record = _run_export(args, config, store, record=record)
    if record.get("status") == "failed":
        return record
    if not record.get("ifx", {}).get("ifx_mapping"):
        record = _run_ifx(args, config, store, record=record, step_offset=0, total_steps=6)
    if not record.get("handoff", {}).get("commands_file"):
        record = _run_handoff(args, config, store, record, step=6, total_steps=6)
    return record


def dispatch(
    command: str,
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
) -> Tuple[Dict[str, Any], int]:
    """Run a record-mutating command; return (record, exit_code)."""
    if command == "pick":
        return _run_pick(args, config, store), 0

    if command == "export":
        record = _run_export(args, config, store)
        return record, 1 if export_failed(record) else 0

    if command in {"upload", "ifx-upload"}:
        record = store.load(args.run_id) if args.run_id else None
        return _run_upload(args, config, store, record, step_offset=0, total_steps=3), 0

    if command == "ifx-convert":
        record = store.load(args.run_id)
        return _run_ifx_convert(args, config, store, record, step_offset=0, total_steps=2), 0

    if command == "ifx-poll":
        record = store.load(args.run_id)
        return _run_ifx_poll(args, config, store, record), 0

    if command == "ifx":
        record = store.load(args.run_id) if args.run_id else None
        return _run_ifx(args, config, store, record, step_offset=0, total_steps=5), 0

    if command == "handoff":
        record = store.load(args.run_id)
        return _run_handoff(args, config, store, record, step=1, total_steps=1), 0

    if command == "apply-handoff":
        record = store.load(args.run_id)
        return _run_apply_handoff(args, config, store, record), 0

    if command == "dcl":
        record = store.load(args.run_id)
        return _run_dcl(args, config, store, record), 0

    if command == "release":
        record = _run_export(args, config, store, step_offset=0, total_steps=9)
        if export_failed(record):
            return record, 1
        record = _run_ifx(args, config, store, record, step_offset=3, total_steps=9)
        record = _run_handoff(args, config, store, record, step=9, total_steps=9)
        return record, 0

    if command == "resume":
        record = _resume(args, config, store)
        return record, 1 if record.get("status") == "failed" else 0

    if command == "offboard":
        record = store.load(args.run_id) if args.run_id else None
        record = _run_offboard(args, config, store, record)
        return record, 1 if record.get("status") == "failed" else 0

    raise ValueError(f"Unknown command: {command}")
