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
        "extra_args": ["--remote", "luban_1_card"],
        "needs_run_id": False,
    },
    "branch-prep": {
        "command": "branch-prep",
        "label": "Branch Prep",
        "supports_dry_run": True,
        "requires_confirm": False,
        "extra_args": [],
        "needs_run_id": False,
    },
    "dcl-patch": {
        "command": "dcl-patch",
        "label": "DCL Patch Apply",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "rule-setup": {
        "command": "rule-setup",
        "label": "Rule Setup",
        "supports_dry_run": False,
        "requires_confirm": False,
        "extra_args": [],
        "needs_run_id": False,
    },
    "rule-release": {
        "command": "rule-release",
        "label": "Run Validate",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
    },
    "rule-sim": {
        "command": "rule-sim",
        "label": "Trigger Sim",
        "supports_dry_run": True,
        "requires_confirm": True,
        "extra_args": [],
        "needs_run_id": True,
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
            test_yamls = payload.get("test_yamls") or payload.get("test_yaml") or []
            if isinstance(test_yamls, str):
                test_yamls = [test_yamls]
            for test_yaml in test_yamls:
                text = str(test_yaml or "").strip()
                if text:
                    command.extend(["--test-yaml", text])
        else:
            command.extend(["--run-id", release_id])
            remote = str(payload.get("remote") or "").strip()
            if remote:
                command.extend(["--remote", remote])
            else:
                command.extend(spec["extra_args"])
            test_yamls = payload.get("test_yamls") or payload.get("test_yaml") or []
            if isinstance(test_yamls, str):
                test_yamls = [test_yamls]
            for test_yaml in test_yamls:
                text = str(test_yaml or "").strip()
                if text:
                    command.extend(["--test-yaml", text])
    elif action == "branch-prep":
        # Entry step for Rule Patch: create a new run unless an existing one is
        # targeted (mirrors how `export` treats --run-id as optional).
        if release_id != "__draft__":
            command.extend(["--run-id", release_id])
        base_branch = str(payload.get("base_branch") or "").strip()
        if base_branch:
            command.extend(["--base-branch", base_branch])
        new_branch = str(payload.get("new_branch") or "").strip()
        if new_branch:
            command.extend(["--new-branch", new_branch])
    elif action == "dcl-patch":
        revision_id = str(payload.get("revision_id") or "").strip()
        if not revision_id:
            raise ValueError("DCL Patch requires revision_id.")
        command.extend(["--revision-id", revision_id])
        branch = str(payload.get("branch") or "").strip()
        if branch:
            command.extend(["--branch", branch])
        if payload.get("nobranch"):
            command.append("--nobranch")
    elif action == "rule-setup":
        # Entry step for the Rule Patch matrix: create a new run unless an
        # existing one is targeted (mirrors `branch-prep`/`export`).
        if release_id != "__draft__":
            command.extend(["--run-id", release_id])
        revision_id = str(payload.get("revision_id") or "").strip()
        if not revision_id:
            raise ValueError("Rule Setup requires revision_id (the rule CR).")
        command.extend(["--revision-id", revision_id])
        rule_name = str(payload.get("rule_name") or "").strip()
        if not rule_name:
            raise ValueError("Rule Setup requires rule_name.")
        command.extend(["--rule-name", rule_name])
        branch_prefix = str(payload.get("branch_prefix") or "").strip()
        if branch_prefix:
            command.extend(["--branch-prefix", branch_prefix])
        releases = payload.get("releases") or []
        if isinstance(releases, str):
            releases = [releases]
        seen = []
        for release in releases:
            text = str(release or "").strip()
            if text and text not in seen:
                seen.append(text)
                command.extend(["--release", text])
        if not seen:
            raise ValueError("Rule Setup requires at least one release.")
        desc = str(payload.get("description") or payload.get("desc") or "").strip()
        if desc:
            command.extend(["--desc", desc])
    elif action == "rule-release":
        release = str(payload.get("release") or "").strip()
        release_index = payload.get("release_index")
        if release:
            command.extend(["--release", release])
        elif release_index is not None and str(release_index).strip() != "":
            command.extend(["--release-index", str(int(release_index))])
        else:
            raise ValueError("Run Validate requires release or release_index.")
    elif action == "rule-sim":
        release = str(payload.get("release") or "").strip()
        release_index = payload.get("release_index")
        if release:
            command.extend(["--release", release])
        elif release_index is not None and str(release_index).strip() != "":
            command.extend(["--release-index", str(int(release_index))])
        else:
            raise ValueError("Trigger Sim requires release or release_index.")
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
    else:
        command.extend(spec["extra_args"])

    # Run-creating actions persist the active workflow type into record.metadata
    # so the sidebar can group runs by workflow.
    if action in ("pick", "export", "offboard", "branch-prep", "rule-setup"):
        workflow_type = str(payload.get("workflow_type") or "").strip()
        if workflow_type:
            command.extend(["--workflow-type", workflow_type])

    command.append("--yes")
    if dry_run:
        command.append("--dry-run")
    return command
