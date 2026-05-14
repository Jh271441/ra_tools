"""Release-record summaries, timelines, and generated CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from model_release_pipeline.pipeline_steps import WEB_PIPELINE_STEPS


def command_state(result: Optional[Dict[str, Any]]) -> str:
    if not result:
        return "missing"
    returncode = result.get("returncode")
    stderr = str(result.get("stderr") or "")
    if returncode == 0:
        return "done"
    if returncode is None and stderr.startswith("Skipped"):
        return "skipped"
    if returncode is None:
        return "dry_run"
    return "failed"


def actual_onnx(ifx: Dict[str, Any]) -> Dict[str, Any]:
    onnx = ifx.get("onnx") or {}
    mapping_onnx = (ifx.get("ifx_mapping") or {}).get("onnx") or {}
    runner = ifx.get("truck_runner") or {}
    dry_run_polluted = runner.get("selected") == "dry_run" or onnx.get("version") == 0
    if onnx and not dry_run_polluted:
        return onnx
    return mapping_onnx or onnx


def step_status(record: Dict[str, Any], key: str) -> str:
    stage = str(record.get("stage") or "")
    status = str(record.get("status") or "")
    if key == "inspect":
        return "done" if record.get("experiment") else "pending"
    if key == "pick":
        selection = record.get("selection") or {}
        return "done" if selection.get("selected_epoch") is not None else "pending"
    if key == "export":
        export = record.get("export") or {}
        if not export:
            return "pending"
        if stage == "export_failed":
            return "failed"
        export_state = command_state(export.get("export"))
        scp_state = command_state(export.get("scp"))
        if "failed" in {export_state, scp_state}:
            return "failed"
        if export_state in {"done", "skipped", "dry_run"} and scp_state in {
            "done",
            "dry_run",
        }:
            return "dry_run" if stage == "export_dry_run" else "done"
        return "running" if key in stage else "pending"
    if key == "upload":
        ifx = record.get("ifx") or {}
        if stage == "ifx_upload_dry_run":
            return "dry_run"
        if status == "failed" and stage.startswith("ifx_upload"):
            return "failed"
        if not ifx.get("onnx"):
            return "running" if stage == "ifx_uploading" else "pending"
        return "done"
    if key == "ifx":
        ifx = record.get("ifx") or {}
        if stage in ("ifx_converting", "ifx_polling"):
            return "running"
        if stage in ("ifx_convert_failed", "ifx_poll_failed") or (
            status == "failed" and stage.startswith("ifx_convert")
        ):
            return "failed"
        if ifx.get("ifx_mapping"):
            return "dry_run" if stage == "ifx_convert_dry_run" else "done"
        return "pending"
    if key == "handoff":
        if stage == "apply_handoff_dry_run":
            return "dry_run"
        if stage == "apply_handoff_failed":
            return "failed"
        if record.get("apply_handoff"):
            return command_state(record.get("apply_handoff"))
        if record.get("handoff"):
            return "done"
        return "pending"
    if key == "dcl":
        dcl = record.get("dcl") or {}
        if stage == "dcl_failed":
            return "failed"
        if stage == "dcl_dry_run":
            return "dry_run"
        if stage == "dcl_complete":
            return "done"
        if dcl:
            return command_state(dcl)
        apply_handoff = record.get("apply_handoff") or {}
        return "ready" if stage == "apply_handoff_complete" and apply_handoff else "pending"
    if key == "offboard":
        offboard = record.get("offboard") or {}
        if not offboard:
            return "pending"
        if stage == "offboard_failed":
            return "failed"
        return command_state(offboard)
    return "pending"


def record_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    experiment = record.get("experiment") or {}
    selection = record.get("selection") or {}
    ifx = record.get("ifx") or {}
    mapping = ifx.get("ifx_mapping") or {}
    errors = record.get("errors") or []
    return {
        "release_id": record.get("release_id"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "stage": record.get("stage"),
        "status": record.get("status"),
        "experiment_name": experiment.get("name")
        or Path(str(record.get("experiment_path") or "")).name,
        "experiment_path": record.get("experiment_path"),
        "selected_epoch": selection.get("selected_epoch"),
        "selection_source": selection.get("selection_source"),
        "onnx_version": actual_onnx(ifx).get("version"),
        "ifx_platforms": len([key for key in mapping if key != "onnx"]),
        "offboard_status": step_status(record, "offboard"),
        "error_count": len(errors),
    }


def timeline(record: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [
        {
            "key": step.key,
            "title": step.title,
            "description": step.description,
            "status": step_status(record, step.key),
        }
        for step in WEB_PIPELINE_STEPS
    ]


def commands(record: Dict[str, Any]) -> Dict[str, Any]:
    release_id = record.get("release_id")
    experiment_path = record.get("experiment_path") or "<experiment_path>"
    selected_epoch = (record.get("selection") or {}).get("selected_epoch")
    epoch_arg = (
        f"--epoch {int(selected_epoch):03d}"
        if selected_epoch is not None
        else "--epoch <epoch>"
    )
    return {
        "export": (
            "python3 -m model_release_pipeline.cli export "
            f"--remote luban_2_card --experiment {experiment_path!r} {epoch_arg}"
        ),
        "upload": (
            "python3 -m model_release_pipeline.cli upload "
            f"--run-id {release_id} --onnx-version <version> --desc '<desc>'"
        ),
        "ifx_convert": (
            f"python3 -m model_release_pipeline.cli ifx-convert --run-id {release_id}"
        ),
        "apply_handoff": (
            f"python3 -m model_release_pipeline.cli apply-handoff --run-id {release_id}"
        ),
        "dcl": f"python3 -m model_release_pipeline.cli dcl --run-id {release_id}",
        "offboard": (
            "python3 -m model_release_pipeline.cli offboard "
            f"--run-id {release_id} --remote luban_2_card"
        ),
        "dcl_commands": (record.get("apply_handoff") or {}).get("dcl_commands") or [],
    }


def extract_metric_table(stdout: str) -> list[str]:
    lines = stdout.splitlines()
    keep: list[str] = []
    capture = False
    for line in lines:
        if "Validation Metrics" in line or "Saved metric analysis" in line:
            capture = True
        if capture:
            keep.append(line)
            if line.startswith("+------------") and len(keep) > 3:
                break
    return keep[-12:]
