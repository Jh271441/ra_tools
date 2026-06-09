"""Log views derived from release records."""

from __future__ import annotations

import re
from typing import Any, Dict

from model_release_pipeline.web.summary import actual_onnx


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def tail(value: Any, max_lines: int = 80) -> list[str]:
    lines = str(value or "").splitlines()
    return lines[-max_lines:]


def clean_log_line(value: Any) -> str:
    return ANSI_RE.sub("", str(value))


def upload_stdout(ifx: Dict[str, Any]) -> list[str]:
    if not ifx:
        return []
    lines = []
    runner = ifx.get("truck_runner") or {}
    onnx = ifx.get("onnx") or {}
    if runner:
        lines.append(
            "truck runner: "
            f"{runner.get('configured') or 'NA'} -> {runner.get('selected') or 'NA'}"
        )
    if onnx:
        lines.append(
            "uploaded onnx: "
            f"{onnx.get('module') or 'NA'} {onnx.get('name') or 'NA'} "
            f"-v {onnx.get('version') if onnx.get('version') is not None else 'NA'}"
        )
        if onnx.get("local_path"):
            lines.append(f"local onnx: {onnx.get('local_path')}")
    if ifx.get("upload_description"):
        lines.append(f"upload desc: {ifx.get('upload_description')}")
    if ifx.get("precision_test_arg"):
        lines.append(f"precision test: {ifx.get('precision_test_arg')}")
    return lines


def upload_stderr(record: Dict[str, Any]) -> list[str]:
    stage = str(record.get("stage") or "")
    if not stage.startswith("ifx_upload"):
        return []
    return [
        str(item.get("message") or item)
        for item in (record.get("errors") or [])[-20:]
    ]


def ifx_stdout(ifx: Dict[str, Any]) -> list[str]:
    if not ifx:
        return []
    lines: list[str] = []
    onnx = actual_onnx(ifx)
    if onnx:
        lines.append(
            "onnx: "
            f"{onnx.get('module') or 'planner.model-files'} "
            f"{onnx.get('name') or 'NA'} "
            f"-v {onnx.get('version') if onnx.get('version') is not None else 'NA'}"
        )
    if ifx.get("precision_test_arg"):
        lines.append(f"precision test: {ifx.get('precision_test_arg')}")
    jenkins = ifx.get("jenkins") or {}
    if jenkins:
        if jenkins.get("queue_url"):
            lines.append(f"jenkins queue: {jenkins.get('queue_url')}")
        if jenkins.get("build_url"):
            lines.append(f"jenkins build: {jenkins.get('build_url')}")
        if jenkins.get("build_number") is not None:
            lines.append(f"jenkins build_number: {jenkins.get('build_number')}")
        if jenkins.get("result"):
            lines.append(f"jenkins result: {jenkins.get('result')}")
    mapping = ifx.get("ifx_mapping") or ifx.get("dry_run_mapping") or {}
    if mapping:
        lines.append("ifx artifacts:")
        for platform, item in sorted(mapping.items()):
            if platform == "onnx":
                continue
            lines.append(
                "  "
                f"{platform}: {item.get('name') or 'NA'} "
                f"-v {item.get('version') if item.get('version') is not None else 'NA'}"
            )
    failed_uploads = ifx.get("failed_uploads") or []
    if failed_uploads:
        lines.append("failed uploads:")
        for item in failed_uploads:
            lines.append(f"  {clean_log_line(item)}")
    console_tail = (jenkins.get("console_tail") or [])[-30:]
    if console_tail:
        lines.append("")
        lines.append("jenkins console tail:")
        lines.extend(clean_log_line(line) for line in console_tail)
    return lines


def ifx_stderr(record: Dict[str, Any]) -> list[str]:
    stage = str(record.get("stage") or "")
    if not (stage == "ifx_converting" or stage.startswith("ifx_convert")):
        return []
    return [
        str(item.get("message") or item)
        for item in (record.get("errors") or [])[-20:]
    ]


def record_logs(record: Dict[str, Any]) -> Dict[str, list[str]]:
    branch_prep = record.get("branch_prep") or {}
    dcl_patch = record.get("dcl_patch") or {}
    export = record.get("export") or {}
    ifx = record.get("ifx") or {}
    upload_log_source = (
        ifx.get("dry_run_upload")
        if str(record.get("stage") or "") == "ifx_upload_dry_run"
        else ifx
    )
    jenkins = ifx.get("jenkins") or {}
    apply_handoff = record.get("apply_handoff") or {}
    dcl = record.get("dcl") or {}
    sim_plan = record.get("sim_plan") or {}
    offboard = record.get("offboard") or {}
    return {
        "branch_prep_stdout": tail(branch_prep.get("stdout")),
        "branch_prep_stderr": tail(branch_prep.get("stderr")),
        "dcl_patch_stdout": tail(dcl_patch.get("stdout")),
        "dcl_patch_stderr": tail(dcl_patch.get("stderr")),
        "export_stdout": tail((export.get("export") or {}).get("stdout")),
        "export_stderr": tail((export.get("export") or {}).get("stderr")),
        "upload_stdout": upload_stdout(upload_log_source),
        "upload_stderr": upload_stderr(record),
        "ifx_stdout": ifx_stdout(ifx),
        "ifx_stderr": ifx_stderr(record),
        "jenkins_console": jenkins.get("console_tail") or [],
        "handoff_stdout": tail(apply_handoff.get("stdout")),
        "handoff_stderr": tail(apply_handoff.get("stderr")),
        "dcl_stdout": tail(dcl.get("stdout")),
        "dcl_stderr": tail(dcl.get("stderr")),
        "sim_plan_stdout": tail(sim_plan.get("stdout"), 120),
        "sim_plan_stderr": tail(sim_plan.get("stderr"), 120),
        "offboard_stdout": tail(offboard.get("stdout"), 120),
        "offboard_stderr": tail(offboard.get("stderr"), 80),
    }
