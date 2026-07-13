#!/usr/bin/env python3
"""Download minimal road/base-sim bags and classify RA reproduction gaps."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import traceback
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from check_sim.bag.compare_ra_debug import Frame, read_frames
from check_sim.repro.ezsim import EzSimClient, get_trail_trip_segment
from check_sim.repro.scenario_repro import (
    ensure_nofile_limit,
    road_download_command,
    run_download,
    voy_sdk_env,
)


ROAD_TOPICS = ["/planning/planning_debug", "/pose"]
SIM_TOPICS = [
    "/planning/planning_debug",
    "/simulation/pose",
    "/planning/assist_request",
    "/planning/stuck_detection_recall_signal",
]
TASK_ID_PATTERN = re.compile(r"\b(\d{16})\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--output-root", type=Path, default=Path("/home/didi/ra_batch_39367009")
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--keep-bags", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--poll", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def base_task_id(row: dict[str, str]) -> int:
    job_id = row["orion_job_id.group1"]
    for value in row.values():
        for match in TASK_ID_PATTERN.findall(value or ""):
            if match.startswith(job_id):
                return int(match)
    raise ValueError(f"No base task id found for scenario {row['scenario_id']}")


def task_version(row: dict[str, str]) -> int:
    for key, value in row.items():
        if key.endswith(".group1") and value:
            match = re.search(r"task_version=(\d+)", value)
            if match:
                return int(match.group(1))
    return 0


def sim_download_command(output: Path, task_id: int, version: int) -> list[str]:
    voy_bag = shutil.which("voy-bag") or "/home/didi/.local/bin/voy-bag"
    return [
        voy_bag,
        "download",
        str(output),
        "--orion_task_id",
        str(task_id),
        "--orion_task_version",
        str(version),
        "--is_exclude_sim_input_topic",
        "1",
        "-T",
        *SIM_TOPICS,
    ]


def first(frames: list[Frame], predicate) -> Frame | None:
    return next((frame for frame in frames if predicate(frame)), None)


def summarize_frames(frames: list[Frame], start_ms: int) -> dict[str, Any]:
    formal = [frame for frame in frames if frame.timestamp_ms >= start_ms]
    requests = [frame for frame in formal if frame.status == "MODEL_REQUEST"]
    model_frames = [
        frame for frame in formal if frame.process_reason == "ASSIST_STUCK_MODEL"
    ]
    model_detected = [frame for frame in formal if frame.model_detected]
    waiting_model = [
        frame
        for frame in model_frames
        if frame.status == "WAITTING_CORE_PLANNER_UNSTUCK"
    ]
    scores = [frame.scenario_dnn for frame in formal if frame.scenario_dnn is not None]
    fp_reasons = Counter(reason for frame in formal for reason in frame.fp_reasons)
    request = requests[0] if requests else None
    first_model = model_frames[0] if model_frames else None
    first_fail = first(
        formal, lambda frame: frame.non_voluntary_unstuck_reason == "UnstuckFail"
    )
    opened = [frame for frame in formal if frame.assist_session_opened]
    return {
        "frame_count": len(formal),
        "start_ms": start_ms,
        "statuses": dict(Counter(frame.status for frame in formal)),
        "fp_reasons": dict(fp_reasons),
        "request_count": len(requests),
        "request_timestamp_ms": request.timestamp_ms if request else None,
        "request_frame": asdict(request) if request else None,
        "model_reason_frames": len(model_frames),
        "model_detected_frames": len(model_detected),
        "first_model_timestamp_ms": first_model.timestamp_ms if first_model else None,
        "first_model_frame": asdict(first_model) if first_model else None,
        "waiting_model_frames": len(waiting_model),
        "first_waiting_model_frame": asdict(waiting_model[0]) if waiting_model else None,
        "first_unstuck_fail_frame": asdict(first_fail) if first_fail else None,
        "max_scenario_dnn": max(scores) if scores else None,
        "max_stationary_cycles": max(
            (frame.stationary_cycles for frame in formal), default=0
        ),
        "assist_session_opened_frames": len(opened),
        "first_assist_session_opened_ms": opened[0].timestamp_ms if opened else None,
    }


def dominant_reason(counts: dict[str, int]) -> str | None:
    return max(counts, key=counts.get) if counts else None


def classify(road: dict[str, Any], sim: dict[str, Any]) -> tuple[str, list[str]]:
    evidence = []
    road_request = road["request_frame"]
    if road_request:
        evidence.append(f"road request @ {road_request['timestamp_ms']}")
        if (
            road_request["non_voluntary_unstuck_reason"] == "UnstuckFail"
            and road_request["stuck_signal_start_ms"] is None
            and road_request["stuck_signal_last_ms"] is not None
        ):
            evidence.append("road request coincides with StuckSignal start=0/last>0 dropout")
    else:
        return "ROAD_REQUEST_NOT_FOUND", ["No MODEL_REQUEST in formal road window"]

    if sim["request_count"]:
        session_text = (
            f"assist session opened in {sim['assist_session_opened_frames']} frames"
            if sim["assist_session_opened_frames"]
            else "assist session never opened"
        )
        return "SIM_REQUESTED_BUT_METRIC_MISSED", evidence + [
            f"sim bag contains {sim['request_count']} MODEL_REQUEST frame(s)",
            session_text,
        ]

    if sim["model_reason_frames"] == 0:
        if sim["max_scenario_dnn"] is None:
            return "SIM_MODEL_NO_OUTPUT", evidence + ["No scenario DNN output"]
        return "SIM_MODEL_NOT_RECALLED", evidence + [
            f"sim max score={sim['max_scenario_dnn']:.4f}"
        ]

    if sim["waiting_model_frames"]:
        waiting = sim["first_waiting_model_frame"]
        evidence.append(
            "sim model detected but voluntary unstuck gate returned "
            "WAITTING_CORE_PLANNER_UNSTUCK"
        )
        if waiting:
            evidence.append(
                f"sim stuck signal duration={waiting['stuck_signal_duration_ms']} ms, "
                f"modes={waiting['unstuck_modes']}"
            )
        if road_request and road_request["stuck_signal_start_ms"] is None:
            return "ROAD_SIGNAL_DROPOUT_VS_SIM_VOLUNTARY_GATE", evidence
        return "SIM_VOLUNTARY_UNSTUCK_GATE", evidence

    fp_reason = dominant_reason(sim["fp_reasons"])
    if fp_reason:
        return f"SIM_FP_SUPPRESSED:{fp_reason}", evidence + [
            f"dominant sim FP={fp_reason}"
        ]

    return "SIM_REQUEST_STATE_OR_OTHER_GATE", evidence + [
        "Model reason exists without request, waiting, or recorded FP"
    ]


def analyze_case(
    row: dict[str, str],
    output_root: Path,
    keep_bags: bool,
    force: bool,
    poll: int,
    timeout: int,
) -> dict[str, Any]:
    scenario_id = row["scenario_id"]
    case_dir = output_root / f"case_{scenario_id}"
    case_dir.mkdir(parents=True, exist_ok=True)
    summary_path = case_dir / "summary.json"
    if summary_path.is_file() and not force:
        return json.loads(summary_path.read_text(encoding="utf8"))

    info = get_trail_trip_segment(scenario_id)
    segment = info["trip_segment"]
    start_ms = int(segment["startTimestamp"])
    downloaded_road_bag = case_dir / "road.bag"
    downloaded_sim_bag = case_dir / "base_sim.bag"
    env = voy_sdk_env(int(row["binary_id.group1"]), "python")
    ensure_nofile_limit(65536)
    reused_road_bag = Path(f"/home/didi/ra_bags/scenario_{scenario_id}/road.bag")
    if reused_road_bag.exists() and not force:
        road_bag = reused_road_bag.resolve()
    else:
        road_bag = downloaded_road_bag
        road_bag.unlink(missing_ok=True)
        run_download(
            road_download_command(
                road_bag,
                str(segment["tripId"]),
                max(0, start_ms - 5000),
                int(segment["endTimestamp"]),
                ROAD_TOPICS,
            ),
            env,
            case_dir,
            road_bag,
            300,
        )
    task_id = base_task_id(row)
    version = task_version(row)
    sim_id = None
    reused_sim_bag = Path(f"/home/didi/ra_bags/scenario_{scenario_id}/sim.bag")
    if reused_sim_bag.exists() and not force:
        sim_bag = reused_sim_bag.resolve()
        sim_source = "existing_local_ezsim"
    else:
        downloaded_sim_bag.unlink(missing_ok=True)
        client = EzSimClient()
        created = client.start_by_scenario_id(
            scenario_id=scenario_id,
            warmup_ms=5000,
            skip_map_update=False,
            skip_model_update=False,
            binary_id=int(row["binary_id.group1"]),
        )
        sim_id = created["id"]
        final = client.wait(sim_id, poll=poll, timeout=timeout)
        if final.get("status") != "Success":
            raise RuntimeError(
                f"EzSim {sim_id} failed: {final.get('status')}: {final.get('failure')}"
            )
        sim_bag = Path.home() / ".voyager/ezsim/simulation" / sim_id / "output.bag"
        if not sim_bag.is_file():
            raise FileNotFoundError(f"EzSim output bag not found: {sim_bag}")
        sim_source = "rerun_local_ezsim"

    road = summarize_frames(read_frames(road_bag), start_ms)
    sim = summarize_frames(read_frames(sim_bag), start_ms)
    root_cause, evidence = classify(road, sim)
    result = {
        "scenario_id": scenario_id,
        "scenario_name": row["scenario_name"],
        "issue_label": next(
            (item for item in re.findall(r"#\d+", row["scenario_labels"])), None
        ),
        "base_job_id": int(row["orion_job_id.group1"]),
        "base_task_id": task_id,
        "base_task_version": version,
        "base_binary_id": int(row["binary_id.group1"]),
        "feature_binary_id": int(row["binary_id.group2"]),
        "csv_base_assist_value": row.get(
            "dpe_assist_channel_triggered.value.group1"
        ),
        "trip_segment": segment,
        "sim_source": sim_source,
        "sim_id": sim_id,
        "sim_bag": str(sim_bag),
        "root_cause": root_cause,
        "evidence": evidence,
        "road": road,
        "sim": sim,
    }
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    if not keep_bags:
        downloaded_road_bag.unlink(missing_ok=True)
        downloaded_sim_bag.unlink(missing_ok=True)
    return result


def write_report(results: list[dict[str, Any]], path: Path) -> None:
    successful = [result for result in results if "root_cause" in result]
    failures = [result for result in results if "error" in result]
    causes = Counter(result["root_cause"] for result in successful)
    lines = [
        "# RA 路测触发 / Base Sim 未触发：50 Case 复现性分析",
        "",
        "## 范围与方法",
        "",
        f"- 输入 case：{len(results)}；成功解析：{len(successful)}；失败：{len(failures)}。",
        "- 对比从 Trail `trip_segment.startTimestamp` 开始，排除 EzSim warmup。",
        "- 信号来自 `/planning/planning_debug`，重点检查模型召回、FP、voluntary unstuck、StuckSignal 和正式请求。",
        "- 原 Orion output bag 已超过保留期；除已有本地 case 外，sim 使用 CSV 中的 base binary 和同一组标准 extra args 重新运行。",
        "- CSV DPE 是历史任务指标，报告中的 planning/session 信号来自当前重跑；二者不一致时单独标记为跨运行复现不稳定。",
        "",
        "## 根因分布",
        "",
        "| 根因 | 数量 |",
        "|---|---:|",
    ]
    lines.extend(f"| `{cause}` | {count} |" for cause, count in causes.most_common())
    lines.extend(
        [
            "",
            "## Case 明细",
            "",
            "| Scenario | Issue | 根因 | Road request | Sim model frames | Sim waiting | Sim session opened | Sim max score |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for result in successful:
        road_ts = result["road"]["request_timestamp_ms"] or "-"
        score = result["sim"]["max_scenario_dnn"]
        score_text = f"{score:.4f}" if score is not None else "-"
        lines.append(
            f"| {result['scenario_id']} | {result.get('issue_label') or '-'} | "
            f"`{result['root_cause']}` | {road_ts} | "
            f"{result['sim']['model_reason_frames']} | "
            f"{result['sim']['waiting_model_frames']} | "
            f"{result['sim']['assist_session_opened_frames']} | {score_text} |"
        )
    if failures:
        lines.extend(["", "## 失败项", ""])
        for result in failures:
            lines.append(f"- `{result['scenario_id']}`: {result['error']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf8")


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv_path)
    selected = set(args.scenario)
    if selected:
        rows = [row for row in rows if row["scenario_id"] in selected]
    if args.limit is not None:
        rows = rows[: args.limit]
    args.output_root.mkdir(parents=True, exist_ok=True)
    results = []
    for index, row in enumerate(rows, 1):
        scenario_id = row["scenario_id"]
        print(f"[{index}/{len(rows)}] scenario {scenario_id}", flush=True)
        try:
            result = analyze_case(
                row,
                args.output_root,
                args.keep_bags,
                args.force,
                args.poll,
                args.timeout,
            )
        except Exception as exc:  # Continue the overnight batch on per-case failures.
            traceback.print_exc()
            result = {"scenario_id": scenario_id, "error": repr(exc)}
            error_path = args.output_root / f"case_{scenario_id}" / "error.json"
            error_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf8",
            )
        results.append(result)
        report_path = args.report or args.output_root / "report.md"
        write_report(results, report_path)
        (args.output_root / "summary.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )


if __name__ == "__main__":
    main()
