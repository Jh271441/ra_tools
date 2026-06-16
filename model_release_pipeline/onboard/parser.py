"""Argument parser for the seven-step onboard release CLI plus offboard."""

from __future__ import annotations

import argparse


def _add_experiment_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--remote", help="SSH host alias for remote inspect/export")
    parser.add_argument("--remote-python", help="Python command on remote host")


def _add_picker_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task", help="Task/head to use for auto epoch selection")
    parser.add_argument("--epoch", type=int)
    parser.add_argument("--policy", choices=["precision_first", "recall_first"])
    parser.add_argument("--top-n", type=int)
    parser.add_argument("--loss-tolerance-pct", type=float)


def _add_upload_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id")
    parser.add_argument("--onnx-file")
    parser.add_argument("--desc", default="")
    parser.add_argument(
        "--version",
        "--onnx-version",
        dest="version",
        type=int,
        help="Explicit ONNX fileserver version. Defaults to latest+1.",
    )
    parser.add_argument(
        "--replace-upload",
        action="store_true",
        help="Allow replacing an existing ONNX upload binding in this run record.",
    )
    parser.add_argument("--dry-run", action="store_true")


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
    pick_parser.add_argument("--desc", default="")
    pick_parser.add_argument(
        "--workflow-type",
        help="Workflow type tag stored in record.metadata (default full_release).",
    )
    pick_parser.add_argument(
        "--save",
        action="store_true",
        help="Create a StateStore release record for this pick run",
    )

    export_parser = subparsers.add_parser(
        "export", parents=[common], help="Export ONNX from Luban"
    )
    _add_experiment_options(export_parser)
    _add_picker_options(export_parser)
    export_parser.add_argument("--run-id")
    export_parser.add_argument("--desc", default="")
    export_parser.add_argument(
        "--workflow-type",
        help="Workflow type tag stored in record.metadata (default full_release).",
    )
    export_parser.add_argument("--dry-run", action="store_true")

    ifx_parser = subparsers.add_parser(
        "ifx", parents=[common], help="Push ONNX and trigger IFX"
    )
    _add_upload_options(ifx_parser)

    upload_parser = subparsers.add_parser(
        "upload",
        aliases=["ifx-upload"],
        parents=[common],
        help="Upload ONNX to truck and prepare precision test",
    )
    _add_upload_options(upload_parser)

    convert_parser = subparsers.add_parser(
        "ifx-convert",
        parents=[common],
        help="Trigger Jenkins IFX from an uploaded ONNX",
    )
    convert_parser.add_argument("--run-id", required=True)
    convert_parser.add_argument("--dry-run", action="store_true")

    poll_parser = subparsers.add_parser(
        "ifx-poll",
        parents=[common],
        help="Poll an already-triggered Jenkins IFX build and collect artifacts",
    )
    poll_parser.add_argument("--run-id", required=True)
    poll_parser.add_argument(
        "--build-url",
        help="Jenkins build URL to use when the recorded queue item has expired.",
    )

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
    apply_handoff_parser.add_argument(
        "--checkout-branch",
        help="Temporary checkout branch override for the selected branch.",
    )
    apply_handoff_parser.add_argument(
        "--update-diff-ids",
        help="Temporary comma-separated DCL update diff ids for the selected branch.",
    )
    apply_handoff_parser.add_argument(
        "--sim-plan",
        help="Temporary sim plan label for the selected branch.",
    )
    apply_handoff_parser.add_argument("--desc", default="")
    apply_handoff_parser.add_argument("--dry-run", action="store_true")
    apply_handoff_parser.add_argument("--no-commit", action="store_true")
    apply_handoff_parser.add_argument("--allow-dirty", action="store_true")
    apply_handoff_parser.add_argument("--allow-append", action="store_true")

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
    dcl_parser.add_argument(
        "--checkout-branch",
        help="Temporary checkout branch override for the selected branch.",
    )
    dcl_parser.add_argument(
        "--update-diff-ids",
        help="Temporary comma-separated DCL update diff ids for the selected branch.",
    )
    dcl_parser.add_argument(
        "--sim-plan",
        help="Temporary sim plan label for the selected branch.",
    )
    dcl_parser.add_argument("--dry-run", action="store_true")
    dcl_parser.add_argument("--lint", action="store_true")
    dcl_parser.add_argument("--allow-dirty", action="store_true")

    sim_plan_parser = subparsers.add_parser(
        "sim-plan",
        parents=[common],
        help="Trigger Kunpeng/SimOne Sim Plan jobs for DCL revision ids",
    )
    sim_plan_parser.add_argument("--run-id", required=True)
    sim_plan_parser.add_argument(
        "--branch",
        help="Configured branch name or checkout branch. If omitted, trigger enabled default plans for all branches.",
    )
    sim_plan_parser.add_argument(
        "--revision-id",
        type=int,
        help="Explicit DCL revision id. Defaults to the revision id recorded by the DCL step.",
    )
    sim_plan_parser.add_argument(
        "--plan",
        action="append",
        help="Sim Plan name to trigger. Can be repeated or comma-separated.",
    )
    sim_plan_parser.add_argument("--priority", type=int)
    sim_plan_parser.add_argument("--time-sensitive-hour", type=float)
    sim_plan_parser.add_argument("--dry-run", action="store_true")

    sim_status_parser = subparsers.add_parser(
        "sim-plan-status",
        parents=[common],
        help="Refresh stored Sim Plan status from Kunpeng/SimOne",
    )
    sim_status_parser.add_argument("--run-id", required=True)

    sim_cancel_parser = subparsers.add_parser(
        "sim-plan-cancel",
        parents=[common],
        help="Cancel a Kunpeng/SimOne Sim Plan record",
    )
    sim_cancel_parser.add_argument("--run-id", required=True)
    sim_cancel_parser.add_argument("--record-id", required=True)

    release_parser = subparsers.add_parser(
        "release", parents=[common], help="Run export -> ifx -> handoff"
    )
    _add_experiment_options(release_parser)
    _add_picker_options(release_parser)
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
    offboard_parser.add_argument(
        "--test-yaml",
        action="append",
        help="Offboard test yaml under configs/. Can be repeated. Must match scenario_dnn_finetune_test*.yaml.",
    )
    offboard_parser.add_argument("--desc", default="")
    offboard_parser.add_argument(
        "--workflow-type",
        help="Workflow type tag stored in record.metadata (default offboard_only).",
    )
    offboard_parser.add_argument("--dry-run", action="store_true")

    branch_prep_parser = subparsers.add_parser(
        "branch-prep",
        parents=[common],
        help="Checkout a release branch and create a new working branch in Voyager docker",
    )
    branch_prep_parser.add_argument(
        "--run-id",
        help="Existing release id. Omit to create a new run (Rule Patch entry step).",
    )
    branch_prep_parser.add_argument(
        "--workflow-type",
        help="Workflow type tag stored in record.metadata (default rule_patch).",
    )
    branch_prep_parser.add_argument(
        "--base-branch",
        help="Release branch to checkout, e.g. gen4_release_20260508.",
    )
    branch_prep_parser.add_argument(
        "--new-branch",
        help="New working branch to create with git checkout -b.",
    )
    branch_prep_parser.add_argument(
        "--docker",
        help="Voyager docker container. Defaults to CONTAINER_NAME_GEN4 or config.",
    )
    branch_prep_parser.add_argument("--dry-run", action="store_true")

    dcl_patch_parser = subparsers.add_parser(
        "dcl-patch",
        parents=[common],
        help="Apply a DCL patch revision inside Voyager docker: dcl patch --revision <id>",
    )
    dcl_patch_parser.add_argument("--run-id", required=True)
    dcl_patch_parser.add_argument(
        "--revision-id",
        required=True,
        help="DCL revision id to apply, e.g. 6231959.",
    )
    dcl_patch_parser.add_argument(
        "--branch",
        help="Configured branch name. If omitted, apply to all configured branches.",
    )
    dcl_patch_parser.add_argument(
        "--nobranch",
        action="store_true",
        help="Pass --nobranch to dcl patch (apply without creating a branch).",
    )
    dcl_patch_parser.add_argument(
        "--docker",
        help="Voyager docker container. Defaults to CONTAINER_NAME_GEN4 or config.",
    )
    dcl_patch_parser.add_argument("--dry-run", action="store_true")

    rule_setup_parser = subparsers.add_parser(
        "rule-setup",
        parents=[common],
        help="Create a Rule Patch run: one rule CR validated across a release matrix",
    )
    rule_setup_parser.add_argument(
        "--run-id",
        help="Existing run id. Omit to create a new run (Rule Patch entry step).",
    )
    rule_setup_parser.add_argument(
        "--workflow-type",
        help="Workflow type tag stored in record.metadata (default rule_patch).",
    )
    rule_setup_parser.add_argument(
        "--revision-id", help="Rule CR revision id to validate, e.g. 6231959."
    )
    rule_setup_parser.add_argument(
        "--rule-name", help="Short rule name used in working branch, e.g. FN_forcing_recall."
    )
    rule_setup_parser.add_argument(
        "--branch-prefix",
        help="Working branch prefix, e.g. jasperchen. Branch = <prefix>/<release>/<rule>.",
    )
    rule_setup_parser.add_argument(
        "--release",
        action="append",
        help="Target release branch (repeatable), e.g. gen4_release_20260508.",
    )
    rule_setup_parser.add_argument(
        "--releases", help="Comma-separated target release branches."
    )
    rule_setup_parser.add_argument("--desc", default="")
    rule_setup_parser.add_argument("--dry-run", action="store_true")

    rule_release_parser = subparsers.add_parser(
        "rule-release",
        parents=[common],
        help="Run the validate chain (branch prep + dcl patch + dcl diff) for one release",
    )
    rule_release_parser.add_argument("--run-id", required=True)
    rule_release_parser.add_argument(
        "--release", help="Target release branch within this run."
    )
    rule_release_parser.add_argument(
        "--release-index", type=int, help="Target release by index instead of name."
    )
    rule_release_parser.add_argument(
        "--docker",
        help="Voyager docker container. Defaults to CONTAINER_NAME_GEN4 or config.",
    )
    rule_release_parser.add_argument("--dry-run", action="store_true")

    rule_sim_parser = subparsers.add_parser(
        "rule-sim",
        parents=[common],
        help="Trigger Sim Plan for one release's test CR within a Rule Patch run",
    )
    rule_sim_parser.add_argument("--run-id", required=True)
    rule_sim_parser.add_argument(
        "--release", help="Target release branch within this run."
    )
    rule_sim_parser.add_argument(
        "--release-index", type=int, help="Target release by index instead of name."
    )
    rule_sim_parser.add_argument(
        "--plan", action="append", help="Sim plan name (repeatable)."
    )
    rule_sim_parser.add_argument("--priority", type=int)
    rule_sim_parser.add_argument("--time-sensitive-hour", type=float)
    rule_sim_parser.add_argument("--dry-run", action="store_true")

    config_parser = subparsers.add_parser(
        "print-config", parents=[common], help="Show bundled config"
    )
    config_parser.add_argument("--copy", action="store_true")

    web_parser = subparsers.add_parser(
        "web", parents=[common], help="Start the read-only release web console"
    )
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument("--open", action="store_true")
    return parser
