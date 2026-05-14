"""ONNX upload and IFX conversion steps."""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, Optional

from model_release_pipeline.config import ReleaseConfig
from model_release_pipeline.services.ifx_pipeline import IfxPipeline, IfxPipelineError
from model_release_pipeline.state_store import StateStore

ProgressFn = Callable[
    [argparse.Namespace, str, int, int, str, Optional[str]],
    None,
]
ConfirmFn = Callable[[str, bool], bool]
FormatEpochFn = Callable[[Any], str]


def upload_description(
    args: argparse.Namespace,
    record: Dict[str, Any],
    *,
    format_epoch: FormatEpochFn,
) -> str:
    experiment_name = record.get("experiment", {}).get("name") or "manual_onnx"
    selected_epoch = record.get("selection", {}).get("selected_epoch")
    epoch_text = (
        f"epoch={format_epoch(selected_epoch)}"
        if selected_epoch is not None
        else "epoch=unknown"
    )
    user_desc = args.desc or record.get("description", "")
    upload_desc = f"{experiment_name}, {epoch_text}"
    if user_desc:
        upload_desc = f"{upload_desc}, {user_desc}"
    return f"{upload_desc}."


def validate_upload_binding(args: argparse.Namespace, record: Dict[str, Any]) -> None:
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


def run_upload(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    *,
    step_offset: int = 0,
    total_steps: int = 3,
    confirm_upload: bool = True,
    progress: ProgressFn,
    confirm: ConfirmFn,
    format_epoch: FormatEpochFn,
    ifx_pipeline_cls: Any = IfxPipeline,
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

    validate_upload_binding(args, record)

    if confirm_upload and not confirm(f"Upload {local_onnx_file} to truck?", args.yes):
        raise RuntimeError("Upload cancelled by user.")

    record["stage"] = "ifx_uploading"
    record["status"] = "running"
    store.save(record)

    def ifx_progress(title: str, substep: int, detail: Optional[str] = None) -> None:
        progress(
            args,
            title,
            step_offset + substep,
            total_steps,
            "🚚",
            detail,
        )

    result = ifx_pipeline_cls(config.ifx).upload(
        local_onnx_file=local_onnx_file,
        description=upload_description(args, record, format_epoch=format_epoch),
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


def run_ifx_convert(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    *,
    step_offset: int = 0,
    total_steps: int = 2,
    confirm_convert: bool = True,
    progress: ProgressFn,
    confirm: ConfirmFn,
    ifx_pipeline_cls: Any = IfxPipeline,
    ifx_pipeline_error_cls: Any = IfxPipelineError,
) -> Dict[str, Any]:
    if record is None:
        if not args.run_id:
            raise RuntimeError("Provide --run-id.")
        record = store.load(args.run_id)
    if not record.get("ifx", {}).get("onnx"):
        raise RuntimeError("No uploaded ONNX found in release record. Run upload first.")
    if confirm_convert and not confirm("Trigger IFX conversion from uploaded ONNX?", args.yes):
        raise RuntimeError("IFX conversion cancelled by user.")
    if args.dry_run:
        record = json.loads(json.dumps(record))
    record["stage"] = "ifx_converting"
    record["status"] = "running"
    if not args.dry_run:
        store.save(record)

    def convert_progress(title: str, substep: int, detail: Optional[str] = None) -> None:
        progress(
            args,
            title,
            step_offset + substep,
            total_steps,
            "🚚",
            detail,
        )

    try:
        result = ifx_pipeline_cls(config.ifx).convert(
            upload_result=record.get("ifx", {}),
            dry_run=args.dry_run,
            progress=convert_progress if not getattr(args, "json", False) else None,
            step_offset=0,
        )
    except ifx_pipeline_error_cls as exc:
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


def run_ifx_poll(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Optional[Dict[str, Any]] = None,
    *,
    step_offset: int = 0,
    total_steps: int = 1,
    progress: ProgressFn,
    ifx_pipeline_cls: Any = IfxPipeline,
    ifx_pipeline_error_cls: Any = IfxPipelineError,
) -> Dict[str, Any]:
    if record is None:
        if not args.run_id:
            raise RuntimeError("Provide --run-id.")
        record = store.load(args.run_id)
    if not record.get("ifx", {}).get("onnx"):
        raise RuntimeError("No uploaded ONNX found in release record. Run upload first.")
    if not record.get("ifx", {}).get("jenkins"):
        raise RuntimeError("No Jenkins state found in release record. Run ifx-convert first.")
    build_url = str(getattr(args, "build_url", "") or "").strip()
    if build_url:
        record["ifx"] = {
            **record.get("ifx", {}),
            "jenkins": {
                **(record.get("ifx", {}).get("jenkins") or {}),
                "build_url": build_url,
            },
        }

    record["stage"] = "ifx_polling"
    record["status"] = "running"
    store.save(record)

    def poll_progress(title: str, substep: int, detail: Optional[str] = None) -> None:
        progress(
            args,
            title,
            step_offset + substep,
            total_steps,
            "🚚",
            detail,
        )

    try:
        result = ifx_pipeline_cls(config.ifx).poll_existing(
            upload_result=record.get("ifx", {}),
            progress=poll_progress if not getattr(args, "json", False) else None,
            step_offset=0,
        )
    except ifx_pipeline_error_cls as exc:
        if exc.partial_result:
            record["ifx"] = {**record.get("ifx", {}), **exc.partial_result}
            store.save(record)
        raise

    record["ifx"] = {**record.get("ifx", {}), **result}
    record["stage"] = "ifx_complete"
    record["status"] = "running"
    store.save(record)
    return record
