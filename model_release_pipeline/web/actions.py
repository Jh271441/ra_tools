"""Web action definitions and CLI command construction."""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional


ACTIONS = {
    "pick": {
        "command": "pick",
        "label": "Pick Epoch",
        "supports_dry_run": False,
        "requires_confirm": False,
        "extra_args": [],
        "needs_run_id": False,
    },
    "export": {
        "command": "export",
        "label": "Model Export",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": False,
    },
    "upload": {
        "command": "upload",
        "label": "Upload ONNX",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "handoff": {
        "command": "handoff",
        "label": "Generate Handoff",
        "supports_dry_run": False,
        "requires_confirm": False,
        "extra_args": [],
        "needs_run_id": True,
    },
    "ifx-convert": {
        "command": "ifx-convert",
        "label": "Trigger IFX Convert",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "ifx-poll": {
        "command": "ifx-poll",
        "label": "Poll IFX Result",
        "supports_dry_run": False,
        "requires_confirm": False,
        "extra_args": [],
        "needs_run_id": True,
    },
    "apply-handoff": {
        "command": "apply-handoff",
        "label": "Apply Handoff",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "dcl": {
        "command": "dcl",
        "label": "Run DCL Diff",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "sim-plan": {
        "command": "sim-plan",
        "label": "Trigger Sim Plan",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "sim-plan-status": {
        "command": "sim-plan-status",
        "label": "Refresh Sim Plan",
        "supports_dry_run": False,
        "requires_confirm": False,
        "extra_args": [],
        "needs_run_id": True,
    },
    "sim-plan-cancel": {
        "command": "sim-plan-cancel",
        "label": "Cancel Sim Plan",
        "supports_dry_run": False,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "offboard": {
        "command": "offboard",
        "label": "Run Offboard",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": ["--remote", "luban_2_card"],
        "needs_run_id": False,
    },
}


def action_specs() -> list[Dict[str, Any]]:
    return [
        {
            "key": key,
            "label": spec["label"],
            "supports_dry_run": spec["supports_dry_run"],
            "requires_confirm": spec["requires_confirm"],
            "needs_run_id": spec.get("needs_run_id", True),
        }
        for key, spec in ACTIONS.items()
    ]


def build_cli_command(
    release_id: str,
    action: str,
    *,
    dry_run: bool = False,
    payload: Optional[Dict[str, Any]] = None,
    config_path: Optional[str] = None,
) -> list[str]:
    if action not in ACTIONS:
        raise ValueError(f"Unsupported action: {action}")
    spec = ACTIONS[action]
    if dry_run and not spec["supports_dry_run"]:
        raise ValueError(f"Action {action} does not support dry_run.")

    command = [sys.executable, "-m", "model_release_pipeline.cli"]
    if config_path:
        command.extend(["--config", config_path])
    command.append(spec["command"])

    payload = payload or {}
    if spec.get("needs_run_id", True):
        command.extend(["--run-id", release_id])
    if action == "pick":
        experiment = str(payload.get("experiment") or "").strip()
        if not experiment:
            raise ValueError("Pick requires experiment.")
        command.extend(["--experiment", experiment])
        remote = str(payload.get("remote") or "").strip()
        if remote:
            command.extend(["--remote", remote])
        remote_python = str(payload.get("remote_python") or "").strip()
        if remote_python:
            command.extend(["--remote-python", remote_python])
        desc = str(payload.get("desc") or "").strip()
        if desc:
            command.extend(["--desc", desc])
        command.append("--save")
    elif action == "export":
        if release_id != "__draft__":
            command.extend(["--run-id", release_id])
        experiment = str(payload.get("experiment") or "").strip()
        if not experiment:
            raise ValueError("Model export requires experiment.")
        command.extend(["--experiment", experiment])
        remote = str(payload.get("remote") or "").strip()
        if remote:
            command.extend(["--remote", remote])
        remote_python = str(payload.get("remote_python") or "").strip()
        if remote_python:
            command.extend(["--remote-python", remote_python])
        epoch = str(payload.get("epoch") or "").strip()
        if epoch:
            if not epoch.isdigit():
                raise ValueError("epoch must be an integer.")
            command.extend(["--epoch", str(int(epoch))])
        task = str(payload.get("task") or "").strip()
        if task:
            command.extend(["--task", task])
        desc = str(payload.get("desc") or "").strip()
        if desc:
            command.extend(["--desc", desc])
    elif action == "upload":
        desc = str(payload.get("desc") or "").strip()
        if desc:
            command.extend(["--desc", desc])
        version = str(payload.get("version") or "").strip()
        if version:
            if not version.isdigit():
                raise ValueError("ONNX version must be an integer.")
            command.extend(["--onnx-version", str(int(version))])
        if payload.get("replace_upload"):
            command.append("--replace-upload")
    elif action == "ifx-poll":
        build_url = str(payload.get("build_url") or "").strip()
        if build_url:
            command.extend(["--build-url", build_url])
    elif action == "apply-handoff":
        branch = str(payload.get("branch") or "").strip()
        if branch:
            command.extend(["--branch", branch])
        checkout_branch = str(payload.get("checkout_branch") or "").strip()
        if checkout_branch:
            command.extend(["--checkout-branch", checkout_branch])
        update_diff_ids = payload.get("update_diff_ids")
        if update_diff_ids:
            if isinstance(update_diff_ids, (list, tuple)):
                update_diff_ids = ",".join(str(item) for item in update_diff_ids)
            command.extend(["--update-diff-ids", str(update_diff_ids)])
        sim_plan = str(payload.get("sim_plan") or "").strip()
        if sim_plan:
            command.extend(["--sim-plan", sim_plan])
        desc = str(payload.get("desc") or "").strip()
        if desc:
            command.extend(["--desc", desc])
        if payload.get("allow_dirty"):
            command.append("--allow-dirty")
    elif action == "dcl":
        branch = str(payload.get("branch") or "").strip()
        if branch:
            command.extend(["--branch", branch])
        checkout_branch = str(payload.get("checkout_branch") or "").strip()
        if checkout_branch:
            command.extend(["--checkout-branch", checkout_branch])
        update_diff_ids = payload.get("update_diff_ids")
        if update_diff_ids:
            if isinstance(update_diff_ids, (list, tuple)):
                update_diff_ids = ",".join(str(item) for item in update_diff_ids)
            command.extend(["--update-diff-ids", str(update_diff_ids)])
        sim_plan = str(payload.get("sim_plan") or "").strip()
        if sim_plan:
            command.extend(["--sim-plan", sim_plan])
        if payload.get("lint"):
            command.append("--lint")
        if payload.get("allow_dirty"):
            command.append("--allow-dirty")
    elif action == "sim-plan":
        branch = str(payload.get("branch") or "").strip()
        if branch:
            command.extend(["--branch", branch])
        revision_id = str(payload.get("revision_id") or "").strip()
        if revision_id:
            if not revision_id.isdigit():
                raise ValueError("revision_id must be an integer.")
            command.extend(["--revision-id", str(int(revision_id))])
        plans = payload.get("plans") or payload.get("plan") or []
        if isinstance(plans, str):
            plans = [plans]
        for plan in plans:
            text = str(plan or "").strip()
            if text:
                command.extend(["--plan", text])
        priority = str(payload.get("priority") or "").strip()
        if priority:
            if not priority.isdigit():
                raise ValueError("priority must be an integer.")
            command.extend(["--priority", str(int(priority))])
        time_sensitive_hour = str(payload.get("time_sensitive_hour") or "").strip()
        if time_sensitive_hour:
            float(time_sensitive_hour)
            command.extend(["--time-sensitive-hour", time_sensitive_hour])
    elif action == "sim-plan-cancel":
        record_id = str(payload.get("record_id") or "").strip()
        if not record_id:
            raise ValueError("Sim Plan cancel requires record_id.")
        command.extend(["--record-id", record_id])
    elif action == "offboard":
        experiment = str(payload.get("experiment") or "").strip()
        epoch = str(payload.get("epoch") or "").strip()
        if experiment or release_id == "__draft__":
            if not experiment:
                raise ValueError("Direct offboard requires experiment.")
            if not epoch:
                raise ValueError("Direct offboard requires epoch.")
            if not epoch.isdigit():
                raise ValueError("epoch must be an integer.")
            command.extend(["--experiment", experiment, "--epoch", str(int(epoch))])
            remote = str(payload.get("remote") or "").strip()
            if remote:
                command.extend(["--remote", remote])
            remote_python = str(payload.get("remote_python") or "").strip()
            if remote_python:
                command.extend(["--remote-python", remote_python])
            desc = str(payload.get("desc") or "").strip()
            if desc:
                command.extend(["--desc", desc])
        else:
            command.extend(["--run-id", release_id])
            remote = str(payload.get("remote") or "").strip()
            if remote:
                command.extend(["--remote", remote])
            else:
                command.extend(spec["extra_args"])
    else:
        command.extend(spec["extra_args"])

    command.append("--yes")
    if dry_run:
        command.append("--dry-run")
    return command
