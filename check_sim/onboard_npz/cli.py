"""CLI for two-layer offline Onboard Stuck NPZ inference, bag export, and parity verification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

from .bag_exporter import download_road_scenario_bag, export_road_bag_to_npz
from .batch_export_1030 import DEFAULT_1030_ISSUES, DEFAULT_1030_SCENARIOS, stream_export_1030_dataset
from .detector_replay import infer_npz_file
from .diff_report_1030 import (
    DEFAULT_ALL1563_REQUESTS,
    DEFAULT_COHORT_JSON,
    DEFAULT_ORION_COMPARE_JSON,
    run_1030_evaluation_and_diff,
)
from .historical_shuyi_eval import run_multi_release_shuyi_suite, stream_export_population_dataset
from .model_runner import OnboardModelRunner
from .schema import OnboardDetectorConfig


def _collect_npz_paths(targets: Sequence[str]) -> List[Path]:
    found: List[Path] = []
    for raw in targets:
        p = Path(raw).expanduser().resolve()
        if p.is_file() and p.suffix == ".npz":
            found.append(p)
        elif p.is_file() and p.suffix in (".txt", ".json"):
            if p.suffix == ".json":
                payload = json.loads(p.read_text(encoding="utf-8"))
                items = payload if isinstance(payload, list) else payload.get("npz_paths", [])
                found.extend(Path(x).expanduser().resolve() for x in items)
            else:
                for line in p.read_text(encoding="utf-8").splitlines():
                    s = line.strip()
                    if s and not s.startswith("#"):
                        found.append(Path(s).expanduser().resolve())
        elif p.is_dir():
            found.extend(sorted(p.rglob("*.npz")))
        else:
            raise FileNotFoundError(f"Target NPZ / directory / manifest not found: {p}")
    # Deduplicate preserving order
    seen = set()
    unique: List[Path] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _cmd_export_bag(args: argparse.Namespace) -> int:
    if bool(args.bag) == bool(args.scenario_id):
        raise SystemExit("Specify exactly one of --bag or --scenario-id")

    temp_bag_dir: Optional[Path] = None
    bag_path: Path
    if args.scenario_id:
        out_path = Path(args.output).expanduser().resolve()
        temp_bag_dir = out_path.parent / f".tmp_download_{args.scenario_id}"
        bag_path = download_road_scenario_bag(args.scenario_id, temp_bag_dir)
        case_id = args.case_id or args.scenario_id
    else:
        bag_path = Path(args.bag).expanduser().resolve()
        case_id = args.case_id

    try:
        receipt = export_road_bag_to_npz(
            bag_path,
            args.output,
            case_id=case_id,
            trip_id=args.trip_id,
            source_kind=args.source_kind,
            overwrite=args.overwrite,
        )
    finally:
        if temp_bag_dir is not None and not args.keep_downloaded_bag:
            for f in temp_bag_dir.rglob("*"):
                if f.is_file():
                    f.unlink(missing_ok=True)
            for d in sorted(temp_bag_dir.rglob("*"), reverse=True):
                if d.is_dir():
                    d.rmdir()
            if temp_bag_dir.is_dir():
                temp_bag_dir.rmdir()

    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def _cmd_infer(args: argparse.Namespace) -> int:
    npz_paths = _collect_npz_paths(args.targets)
    if not npz_paths:
        raise SystemExit("No .npz files found in targets")

    cfg = OnboardDetectorConfig(enable_uncertain_delay=args.enable_uncertain_delay)
    t0 = time.perf_counter()
    summaries: List[Dict[str, Any]] = []
    with OnboardModelRunner(args.model, device=args.device, bridge_so=args.bridge_so) as runner:
        for npz_path in npz_paths:
            res = infer_npz_file(
                npz_path,
                runner,
                mode=args.mode,
                config=cfg,
                threshold_override=args.threshold,
                verify_parity=args.verify_parity,
                infer_all_frames=args.infer_all_frames,
            )
            summaries.append(res.to_summary_dict(include_frame_scores=args.include_frame_scores))

    elapsed = time.perf_counter() - t0
    envelope = {
        "count": len(summaries),
        "triggered_request_count": sum(1 for s in summaries if s["triggered_request"]),
        "triggered_by_model_count": sum(1 for s in summaries if s["triggered_by_model"]),
        "elapsed_sec": round(elapsed, 4),
        "results": summaries,
    }
    text = json.dumps(envelope, ensure_ascii=False, indent=2)
    if args.json_out:
        out_p = Path(args.json_out).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _cmd_verify_parity(args: argparse.Namespace) -> int:
    npz_paths = _collect_npz_paths(args.targets)
    if not npz_paths:
        raise SystemExit("No .npz files found in targets")

    cfg = OnboardDetectorConfig(enable_uncertain_delay=args.enable_uncertain_delay)
    reports: List[Dict[str, Any]] = []
    all_passed = True
    with OnboardModelRunner(args.model, device=args.device, bridge_so=args.bridge_so) as runner:
        for npz_path in npz_paths:
            res = infer_npz_file(
                npz_path,
                runner,
                mode="onboard_full",
                config=cfg,
                verify_parity=True,
                infer_all_frames=False,
            )
            if res.parity is None or not res.parity.passed:
                all_passed = False
            reports.append(res.to_summary_dict())

    envelope = {
        "all_passed": all_passed,
        "cases_checked": len(reports),
        "cases_passed": sum(1 for r in reports if r.get("parity", {}).get("passed")),
        "total_cycles_checked": sum(int(r.get("num_cycles", 0)) for r in reports),
        "results": reports,
    }
    text = json.dumps(envelope, ensure_ascii=False, indent=2)
    if args.json_out:
        out_p = Path(args.json_out).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if all_passed else 1


def _cmd_batch_eval(args: argparse.Namespace) -> int:
    npz_paths = _collect_npz_paths(args.targets)
    if not npz_paths:
        raise SystemExit("No .npz files found in targets")

    cfg = OnboardDetectorConfig(enable_uncertain_delay=args.enable_uncertain_delay)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    arm_reports: List[Dict[str, Any]] = []

    for model_spec in args.models:
        label, _, raw_path = model_spec.partition("=")
        if not raw_path:
            raw_path = label
            label = Path(raw_path).name if raw_path != "recorded" else "recorded"

        t0 = time.perf_counter()
        with OnboardModelRunner(raw_path, device=args.device, bridge_so=args.bridge_so) as runner:
            for mode_name in modes:
                rows: List[Dict[str, Any]] = []
                for npz_path in npz_paths:
                    res = infer_npz_file(
                        npz_path,
                        runner,
                        mode=mode_name,
                        config=cfg,
                        threshold_override=args.threshold,
                    )
                    rows.append(res.to_summary_dict())
                arm_reports.append({
                    "label": label,
                    "model": raw_path,
                    "backend": runner.backend_name,
                    "mode": mode_name,
                    "cases": len(rows),
                    "triggered_request_count": sum(1 for r in rows if r["triggered_request"]),
                    "triggered_by_model_count": sum(1 for r in rows if r["triggered_by_model"]),
                    "trigger_rate": round(
                        sum(1 for r in rows if r["triggered_request"]) / max(1, len(rows)), 4
                    ),
                    "elapsed_sec": round(time.perf_counter() - t0, 4),
                    "case_results": rows,
                })

    summary = {"npz_count": len(npz_paths), "arms": arm_reports}
    if args.json_out:
        out_p = Path(args.json_out).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.md_out:
        lines = [
            "# Offline Onboard NPZ Evaluation Summary",
            "",
            "| Arm | Backend | Mode | Cases | Triggered (Total) | Triggered (By Model) | Trigger Rate | Elapsed (s) |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for arm in arm_reports:
            lines.append(
                f"| `{arm['label']}` | `{arm['backend']}` | `{arm['mode']}` | {arm['cases']} | "
                f"{arm['triggered_request_count']} | {arm['triggered_by_model_count']} | "
                f"{arm['trigger_rate']:.2%} | {arm['elapsed_sec']:.2f} |"
            )
        md_p = Path(args.md_out).expanduser().resolve()
        md_p.parent.mkdir(parents=True, exist_ok=True)
        md_p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({k: v for k, v in summary.items() if k != "arms"} | {
        "arms": [{k: v for k, v in a.items() if k != "case_results"} for a in arm_reports]
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_export_1030(args: argparse.Namespace) -> int:
    summary = stream_export_1030_dataset(
        args.out_root,
        scenarios_jsonl=args.scenarios_jsonl,
        issues_jsonl=args.issues_jsonl,
        warmup_ms=args.warmup_ms,
        workers=args.workers,
        limit=args.limit,
        overwrite=args.overwrite,
        min_free_gb=args.min_free_gb,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if int(summary["failed"]) == 0 else 1


def _cmd_eval_1030(args: argparse.Namespace) -> int:
    summary = run_1030_evaluation_and_diff(
        args.npz_dir,
        args.out_dir,
        base_model=args.base_model,
        feature_model=args.feature_model,
        include_recorded=not args.no_recorded,
        all1563_jsonl=args.all1563_jsonl,
        cohort_json=args.cohort_json,
        orion_compare_json=args.orion_compare_json,
        device=args.device,
        workers=args.workers,
    )
    compact = {
        "scenarios_evaluated": summary["scenarios_evaluated"],
        "parity_summaries": summary["parity_summaries"],
        "base_all_business": summary["cohort_metrics_onboard_full"]["base_v89"]["all_business"]["unified_binary"],
        "feature_all_business": summary["cohort_metrics_onboard_full"]["feature_cr7028995_v122"]["all_business"][
            "unified_binary"
        ],
        "paired_transitions": {
            k: v["count"]
            for k, v in summary["paired_diff_base_v89_vs_feature_cr7028995_v122"]["all_business"][
                "transitions"
            ].items()
        },
        "artifacts": summary["artifacts"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


def _cmd_export_population(args: argparse.Namespace) -> int:
    summary = stream_export_population_dataset(
        args.out_root,
        args.population_jsonl,
        release_tag=args.release_tag,
        warmup_ms=args.warmup_ms,
        workers=args.workers,
        limit=args.limit,
        overwrite=args.overwrite,
        min_free_gb=args.min_free_gb,
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "failures"} | {
        "failure_count": len(summary.get("failures", [])),
    }, ensure_ascii=False, indent=2))
    return 0 if int(summary["failed"]) == 0 else 1


def _cmd_eval_shuyi_suite(args: argparse.Namespace) -> int:
    summary = run_multi_release_shuyi_suite(
        args.config_json,
        args.out_dir,
        device=args.device,
        workers=args.workers,
    )
    print(json.dumps({
        "releases": [r["release"] for r in summary["releases"]],
        "csv_path": summary["csv_path"],
        "report_md": summary["report_md"],
        "summary_json": summary["summary_json"],
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m check_sim.onboard_npz",
        description="Simulation-free Voyager Onboard Stuck DNN NPZ inference & 10Hz road-test replicator",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_exp = sub.add_parser("export-bag", help="Export road/sim bag (or scenario ID) to Enhanced Road NPZ")
    p_exp.add_argument("--bag", help="Local .bag file path")
    p_exp.add_argument("--scenario-id", help="Scenario/issue ID to download 5 lightweight topics via voy-bag")
    p_exp.add_argument("--output", "-o", required=True, help="Output .npz path")
    p_exp.add_argument("--case-id", help="Explicit case/issue ID")
    p_exp.add_argument("--trip-id", default="", help="Optional trip ID")
    p_exp.add_argument("--source-kind", default="road", choices=("road", "simulation"))
    p_exp.add_argument("--overwrite", action="store_true")
    p_exp.add_argument("--keep-downloaded-bag", action="store_true")
    p_exp.set_defaults(func=_cmd_export_bag)

    p_inf = sub.add_parser("infer", help="Run offline Onboard inference on Layer 1 or Layer 2 NPZ(s)")
    p_inf.add_argument("targets", nargs="+", help=".npz file(s), directory, or manifest (.txt/.json)")
    p_inf.add_argument("--model", default="recorded", help="Path to .ifxmodel, .onnx, or 'recorded'")
    p_inf.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    p_inf.add_argument("--bridge-so", type=Path, help="Optional prebuilt ifx_native_bridge.so path")
    p_inf.add_argument(
        "--mode",
        default="auto",
        choices=("auto", "onboard_full", "onboard_strict_road", "onboard_light_counterfactual", "model_only", "cropped_model_only"),
    )
    p_inf.add_argument("--threshold", type=float, help="Optional stuck threshold override")
    p_inf.add_argument("--enable-uncertain-delay", action="store_true")
    p_inf.add_argument("--verify-parity", action="store_true")
    p_inf.add_argument("--infer-all-frames", action="store_true")
    p_inf.add_argument("--include-frame-scores", action="store_true")
    p_inf.add_argument("--json-out", help="Write full JSON output to file")
    p_inf.set_defaults(func=_cmd_infer)

    p_par = sub.add_parser("verify-parity", help="Verify 100%% cycle-by-cycle Onboard parity on Enhanced Road NPZ(s)")
    p_par.add_argument("targets", nargs="+", help="Enhanced Road .npz file(s) or directory")
    p_par.add_argument("--model", default="recorded", help="Path to matching .ifxmodel/.onnx, or 'recorded'")
    p_par.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    p_par.add_argument("--bridge-so", type=Path, help="Optional prebuilt ifx_native_bridge.so path")
    p_par.add_argument("--enable-uncertain-delay", action="store_true")
    p_par.add_argument("--json-out", help="Write parity report JSON to file")
    p_par.set_defaults(func=_cmd_verify_parity)

    p_bat = sub.add_parser("batch-eval", help="Batch-evaluate one or more models/modes across NPZ sets")
    p_bat.add_argument("targets", nargs="+", help=".npz files, directory, or manifest")
    p_bat.add_argument(
        "--model",
        dest="models",
        action="append",
        required=True,
        help="Model spec 'label=/path/to/model.ifxmodel' or path (repeatable)",
    )
    p_bat.add_argument("--modes", default="auto", help="Comma-separated modes (e.g. onboard_full,model_only)")
    p_bat.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    p_bat.add_argument("--bridge-so", type=Path, help="Optional prebuilt ifx_native_bridge.so path")
    p_bat.add_argument("--threshold", type=float, help="Optional stuck threshold override")
    p_bat.add_argument("--enable-uncertain-delay", action="store_true")
    p_bat.add_argument("--json-out", help="Write full JSON summary")
    p_bat.add_argument("--md-out", help="Write Markdown table summary")
    p_bat.set_defaults(func=_cmd_batch_eval)

    p_e1030 = sub.add_parser(
        "export-1030",
        help="Stream-export Release 1030 scenarios from road bags to Enhanced Road NPZs (zero leftover bags)",
    )
    p_e1030.add_argument("--out-root", required=True, type=Path, help="Target dataset root directory")
    p_e1030.add_argument("--scenarios-jsonl", type=Path, default=DEFAULT_1030_SCENARIOS)
    p_e1030.add_argument("--issues-jsonl", type=Path, default=DEFAULT_1030_ISSUES)
    p_e1030.add_argument("--warmup-ms", type=int, default=5000)
    p_e1030.add_argument("--workers", type=int, default=12)
    p_e1030.add_argument("--limit", type=int, help="Optional scenario limit for smoke testing")
    p_e1030.add_argument("--min-free-gb", type=float, default=50.0)
    p_e1030.add_argument("--overwrite", action="store_true")
    p_e1030.set_defaults(func=_cmd_export_1030)

    p_d1030 = sub.add_parser(
        "eval-1030",
        help="Run full Release 1030 Base vs Feature offline IFX evaluation and paired TE7 Diff report",
    )
    p_d1030.add_argument("--npz-dir", required=True, type=Path, help="1030 Enhanced Road NPZ directory")
    p_d1030.add_argument("--out-dir", required=True, type=Path, help="Report output directory")
    p_d1030.add_argument("--base-model", required=True, help="Base .ifxmodel / .onnx path")
    p_d1030.add_argument("--feature-model", required=True, help="Feature .ifxmodel / .onnx path")
    p_d1030.add_argument("--no-recorded", action="store_true", help="Skip 'recorded' car-score arm")
    p_d1030.add_argument("--all1563-jsonl", type=Path, default=DEFAULT_ALL1563_REQUESTS)
    p_d1030.add_argument("--cohort-json", type=Path, default=DEFAULT_COHORT_JSON)
    p_d1030.add_argument("--orion-compare-json", type=Path, default=DEFAULT_ORION_COMPARE_JSON)
    p_d1030.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    p_d1030.add_argument("--workers", type=int, default=8)
    p_d1030.set_defaults(func=_cmd_eval_1030)

    p_epop = sub.add_parser(
        "export-population",
        help="Stream-export any release population.jsonl to Enhanced Road NPZs (zero leftover bags)",
    )
    p_epop.add_argument("--out-root", required=True, type=Path, help="Target dataset root directory")
    p_epop.add_argument("--population-jsonl", required=True, type=Path, help="Release population.jsonl path")
    p_epop.add_argument("--release-tag", default="", help="Optional release tag for progress logs")
    p_epop.add_argument("--warmup-ms", type=int, default=5000)
    p_epop.add_argument("--workers", type=int, default=20)
    p_epop.add_argument("--limit", type=int, help="Optional scenario limit for smoke testing")
    p_epop.add_argument("--min-free-gb", type=float, default=150.0)
    p_epop.add_argument("--overwrite", action="store_true")
    p_epop.set_defaults(func=_cmd_export_population)

    p_shuyi = sub.add_parser(
        "eval-shuyi-suite",
        help="Run multi-release offline NPZ inference and reconcile P/R against Shuyi board 288969/6276081",
    )
    p_shuyi.add_argument("--config-json", required=True, type=Path, help="Suite configuration JSON")
    p_shuyi.add_argument("--out-dir", required=True, type=Path, help="Suite report output directory")
    p_shuyi.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    p_shuyi.add_argument("--workers", type=int, default=16)
    p_shuyi.set_defaults(func=_cmd_eval_shuyi_suite)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
