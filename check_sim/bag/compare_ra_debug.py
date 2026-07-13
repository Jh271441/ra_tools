#!/usr/bin/env python3
"""Compare road/sim RA stuck decisions from /planning/planning_debug."""

from __future__ import annotations

import argparse
import bisect
import contextlib
import io
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from rosbags.rosbag1 import Reader
except ModuleNotFoundError:
    Reader = None
    sdk_path = Path("/opt/voy-sdk/lib/python3/dist-packages")
    if sdk_path.is_dir():
        sys.path.insert(0, str(sdk_path))
    import rosbag

    logging.getLogger("rosbag").setLevel(logging.ERROR)

try:
    from .planning_stub_pb2 import PlanningDebug
except ImportError:
    from planning_stub_pb2 import PlanningDebug


TOPIC = "/planning/planning_debug"


@dataclass(frozen=True)
class Frame:
    timestamp_ms: int
    status: str
    process_reason: str
    rule_decision: str
    fp_reasons: tuple[str, ...]
    fn_reasons: tuple[str, ...]
    active_rules: tuple[str, ...]
    lane_change_forbid_timestamp_ms: int | None
    model_detected: bool
    scenario_dnn: float | None
    threshold: float
    stationary_cycles: int


def enum_name(field, value: int) -> str:
    return field.enum_type.values_by_number[value].name


def optional_double(message, field_name: str) -> float | None:
    try:
        if not message.HasField(field_name):
            return None
    except ValueError:
        pass
    return float(getattr(message, field_name))


def parse_frame(timestamp_ms: int, payload: bytes) -> Frame:
    message = PlanningDebug()
    message.ParseFromString(payload)
    debug = message.behavior_reasoner_debug.ego_stuck_debug
    rules = debug.rules_debug
    activation = rules.rule_activation
    active_rules = tuple(
        field.name
        for field, value in activation.ListFields()
        if field.type == field.TYPE_BOOL and value
    )
    status_field = debug.DESCRIPTOR.fields_by_name["unstuck_status"]
    reason_field = debug.DESCRIPTOR.fields_by_name["assist_model_process_reason"]
    decision_field = rules.DESCRIPTOR.fields_by_name["rule_decision"]
    lane_change_ts = rules.fp_lane_change_debug.lane_change_forbid_requirement_timestmap
    return Frame(
        timestamp_ms=timestamp_ms,
        status=enum_name(status_field, debug.unstuck_status),
        process_reason=enum_name(reason_field, debug.assist_model_process_reason),
        rule_decision=enum_name(decision_field, rules.rule_decision),
        fp_reasons=tuple(enum_name(reason_field, value) for value in rules.fp_process_reasons),
        fn_reasons=tuple(enum_name(reason_field, value) for value in rules.fn_process_reasons),
        active_rules=active_rules,
        lane_change_forbid_timestamp_ms=lane_change_ts or None,
        model_detected=debug.is_stuck_detected_by_model,
        scenario_dnn=optional_double(debug, "scenario_dnn_stuck_likelihood_from_ra_vnode"),
        threshold=debug.stuck_threshold,
        stationary_cycles=debug.stationary_cycle_count,
    )


def unwrap_ros_payload(raw_message) -> bytes:
    data = raw_message[1] if isinstance(raw_message, tuple) else raw_message
    declared_size = int.from_bytes(data[:4], "little")
    return data[4 : 4 + declared_size]


def read_frames(path: Path) -> list[Frame]:
    if Reader is not None:
        frames = []
        with Reader(path) as reader:
            connections = [c for c in reader.connections if c.topic == TOPIC]
            for _, timestamp, rawdata in reader.messages(connections=connections):
                frames.append(parse_frame(timestamp // 1_000_000, rawdata[4:]))
        return frames

    frames = []
    with contextlib.redirect_stderr(io.StringIO()):
        with rosbag.Bag(str(path)) as bag:
            for _, raw_message, timestamp in bag.read_messages(topics=[TOPIC], raw=True):
                frames.append(
                    parse_frame(timestamp.to_nsec() // 1_000_000, unwrap_ros_payload(raw_message))
                )
    return frames


def nearest(frame: Frame, candidates: list[Frame], times: list[int]) -> tuple[Frame, int]:
    index = bisect.bisect_left(times, frame.timestamp_ms)
    choices = [i for i in (index - 1, index) if 0 <= i < len(candidates)]
    best = min(choices, key=lambda i: abs(times[i] - frame.timestamp_ms))
    return candidates[best], abs(times[best] - frame.timestamp_ms)


def decision_key(frame: Frame) -> tuple:
    return (
        frame.status,
        frame.process_reason,
        frame.rule_decision,
        frame.fp_reasons,
        frame.fn_reasons,
        frame.active_rules,
    )


def histogram(frames: list[Frame], attribute: str) -> dict[str, int]:
    return dict(Counter(str(getattr(frame, attribute)) for frame in frames))


def compare(road: list[Frame], sim: list[Frame], tolerance_ms: int) -> dict:
    sim_times = [frame.timestamp_ms for frame in sim]
    aligned = []
    mismatches = []
    for road_frame in road:
        sim_frame, delta_ms = nearest(road_frame, sim, sim_times)
        if delta_ms > tolerance_ms:
            continue
        pair = {"delta_ms": delta_ms, "road": asdict(road_frame), "sim": asdict(sim_frame)}
        aligned.append(pair)
        if decision_key(road_frame) != decision_key(sim_frame):
            mismatches.append(pair)
    return {
        "road_frames": len(road),
        "sim_frames": len(sim),
        "aligned_frames": len(aligned),
        "mismatched_frames": len(mismatches),
        "road_statuses": histogram(road, "status"),
        "sim_statuses": histogram(sim, "status"),
        "road_process_reasons": histogram(road, "process_reason"),
        "sim_process_reasons": histogram(sim, "process_reason"),
        "first_mismatches": mismatches[:10],
    }


def metadata_start_ms(road_path: Path, sim_path: Path) -> tuple[int, Path] | None:
    candidates = [road_path.parent / "metadata.json", sim_path.parent / "metadata.json"]
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            continue
        metadata = json.loads(path.read_text())
        start_ms = metadata.get("trip_segment", {}).get("startTimestamp")
        if start_ms is not None:
            return int(start_ms), path
    return None


def comparison_start_ms(
    road_path: Path,
    sim_path: Path,
    road: list[Frame],
    sim: list[Frame],
    *,
    explicit_start_ms: int | None,
    warmup_ms: int,
    include_warmup: bool,
) -> tuple[int | None, str]:
    if include_warmup:
        return None, "warmup included by --include-warmup"
    if explicit_start_ms is not None:
        return explicit_start_ms, "explicit --start-ms"
    metadata_start = metadata_start_ms(road_path, sim_path)
    if metadata_start is not None:
        start_ms, path = metadata_start
        return start_ms, f"trip_segment.startTimestamp from {path}"
    common_start_ms = max(road[0].timestamp_ms, sim[0].timestamp_ms)
    return common_start_ms + warmup_ms, f"common bag start + {warmup_ms} ms warmup"


def format_frame(frame: dict) -> str:
    return (
        f"ts={frame['timestamp_ms']} status={frame['status']} "
        f"reason={frame['process_reason']} decision={frame['rule_decision']} "
        f"fp={list(frame['fp_reasons'])} active={list(frame['active_rules'])} "
        f"scen_dnn={frame['scenario_dnn']} threshold={frame['threshold']} "
        f"lane_change_forbid_ts={frame['lane_change_forbid_timestamp_ms']}"
    )


def print_text(result: dict) -> None:
    window = result["comparison_window"]
    print(
        f"comparison start: {window['start_ms']} "
        f"({window['source']}); excluded warmup frames: "
        f"road={window['road_excluded']} sim={window['sim_excluded']}"
    )
    print(
        f"frames: road={result['road_frames']} sim={result['sim_frames']} "
        f"aligned={result['aligned_frames']} mismatched={result['mismatched_frames']}"
    )
    print(f"road statuses: {result['road_statuses']}")
    print(f"sim statuses:  {result['sim_statuses']}")
    print(f"road reasons:  {result['road_process_reasons']}")
    print(f"sim reasons:   {result['sim_process_reasons']}")
    if not result["first_mismatches"]:
        print("No aligned RA decision mismatch found.")
        return
    print("\nFirst aligned mismatches:")
    for index, pair in enumerate(result["first_mismatches"], start=1):
        print(f"[{index}] delta={pair['delta_ms']} ms")
        print(f"  road {format_frame(pair['road'])}")
        print(f"  sim  {format_frame(pair['sim'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("road", type=Path)
    parser.add_argument("sim", type=Path)
    parser.add_argument("--tolerance-ms", type=int, default=50)
    parser.add_argument(
        "--start-ms",
        type=int,
        help="explicit comparison start timestamp; overrides metadata and warmup",
    )
    parser.add_argument(
        "--warmup-ms",
        type=int,
        default=5000,
        help="warmup excluded when metadata.json is unavailable (default: 5000)",
    )
    parser.add_argument(
        "--include-warmup",
        action="store_true",
        help="compare from bag start, including warmup frames",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    for path in (args.road, args.sim):
        if not path.is_file():
            parser.error(f"bag does not exist: {path}")
    if args.warmup_ms < 0:
        parser.error("--warmup-ms must be non-negative")
    road = read_frames(args.road)
    sim = read_frames(args.sim)
    if not road or not sim:
        parser.error(f"{TOPIC} is missing from one or both bags")
    start_ms, start_source = comparison_start_ms(
        args.road,
        args.sim,
        road,
        sim,
        explicit_start_ms=args.start_ms,
        warmup_ms=args.warmup_ms,
        include_warmup=args.include_warmup,
    )
    road_before_filter = len(road)
    sim_before_filter = len(sim)
    if start_ms is not None:
        road = [frame for frame in road if frame.timestamp_ms >= start_ms]
        sim = [frame for frame in sim if frame.timestamp_ms >= start_ms]
    if not road or not sim:
        parser.error("comparison window contains no planning_debug frames")
    result = compare(road, sim, args.tolerance_ms)
    result["comparison_window"] = {
        "start_ms": start_ms,
        "source": start_source,
        "road_excluded": road_before_filter - len(road),
        "sim_excluded": sim_before_filter - len(sim),
    }
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_text(result)


if __name__ == "__main__":
    main()
