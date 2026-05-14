"""CLI for scenario dnn release tooling."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from model_release_pipeline.config import (
    DEFAULT_TEMPLATE_PATH,
    ReleaseConfig,
    load_config,
)
from model_release_pipeline.onboard.parser import build_parser
from model_release_pipeline.output import (
    format_epoch,
    format_inspect_result,
    format_pick_result,
)
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.services.model_picker import ModelPicker
from model_release_pipeline.state_store import StateStore
from model_release_pipeline.steps.runner import dispatch
from model_release_pipeline.web_app import serve as serve_web


def _print(payload: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(payload)


def _print_record(record: Dict[str, Any], as_json: bool = False) -> None:
    from model_release_pipeline.output import format_record_result
    if as_json:
        _print(record, as_json=True)
    else:
        print("\n" + format_record_result(record))


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


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    store = StateStore(config.runs_dir)

    try:
        if args.command == "inspect":
            from model_release_pipeline.output import progress, separator
            progress(
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
            _print(experiment if args.json else format_inspect_result(experiment), as_json=False)
            return 0

        if args.command == "pick":
            from model_release_pipeline.output import progress
            progress(
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
            _print(pick_result if args.json else format_pick_result(pick_result), as_json=False)
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

        if args.command == "web":
            serve_web(
                config,
                host=args.host,
                port=args.port,
                open_browser=args.open,
                config_path=args.config,
            )
            return 0

        record, exit_code = dispatch(args.command, args, config, store)
        _print_record(record, as_json=args.json)
        return exit_code

    except Exception as exc:  # pylint: disable=broad-except
        if getattr(args, "run_id", None):
            try:
                record = store.load(args.run_id)
                store.add_error(record, str(exc))
            except Exception:
                pass
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
