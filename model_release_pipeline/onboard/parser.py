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

    export_parser = subparsers.add_parser(
        "export", parents=[common], help="Export ONNX from Luban"
    )
    _add_experiment_options(export_parser)
    _add_picker_options(export_parser)
    export_parser.add_argument("--desc", default="")
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
    dcl_parser.add_argument("--dry-run", action="store_true")
    dcl_parser.add_argument("--lint", action="store_true")
    dcl_parser.add_argument("--allow-dirty", action="store_true")

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
    offboard_parser.add_argument("--desc", default="")
    offboard_parser.add_argument("--dry-run", action="store_true")

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
