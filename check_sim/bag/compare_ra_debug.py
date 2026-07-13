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
    yield_dynamic_decision: str
    yielding_object_id: int | None
    yielding_object_speed: float | None
    yield_hold_cycles: int
    yield_temp_parked_cycles: int
    right_lane_yield_cycles: int
    total_yielding_cycles: int
    model_detected: bool
    scenario_dnn: float | None
    scenario_dnn_strict: float | None
    threshold: float
    stationary_cycles: int
    non_voluntary_unstuck_reason: str
    stuck_timer_ms: float
    strict_model_detected: bool
    uncertain_stuck: bool
    selected_maneuver_type: str
    stuck_signal_start_ms: int | None
    stuck_signal_last_ms: int | None
    stuck_signal_duration_ms: int | None
    stuck_signal_reason: str | None
    stuck_signal_score: float | None
    stuck_signal_object_ids: tuple[int, ...]
    unstuck_modes: tuple[int, ...]


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
    voluntary_reason_field = debug.DESCRIPTOR.fields_by_name[
        "non_voluntary_unstuck_reason"
    ]
    decision_field = rules.DESCRIPTOR.fields_by_name["rule_decision"]
    lane_change_ts = rules.fp_lane_change_debug.lane_change_forbid_requirement_timestmap
    yield_debug = rules.fp_yield_dynamic_object_debug
    yield_decision_field = yield_debug.DESCRIPTOR.fields_by_name["decision_reason"]
    behavior_debug = message.behavior_reasoner_debug
    maneuver_type_field = behavior_debug.DESCRIPTOR.fields_by_name[
        "selected_maneuver_type"
    ]
    selected_maneuver = next(
        (
            maneuver
            for maneuver in behavior_debug.decoupled_maneuvers
            if maneuver.type == behavior_debug.selected_maneuver_type
        ),
        None,
    )
    if selected_maneuver is None and len(behavior_debug.decoupled_maneuvers) == 1:
        # The top-level type may retain legacy LANE_FOLLOW while the active
        # decoupled debug is DECOUPLED_FORWARD.
        selected_maneuver = behavior_debug.decoupled_maneuvers[0]
    stuck_debug = None
    if selected_maneuver is not None:
        selection_debug = selected_maneuver.trajectory_selection_debug
        if selection_debug.HasField("stuck_debug"):
            stuck_debug = selection_debug.stuck_debug
    stuck_signal = stuck_debug.stuck_signal if stuck_debug is not None else None
    stuck_signal_reason_field = (
        stuck_signal.DESCRIPTOR.fields_by_name["reason"]
        if stuck_signal is not None
        else None
    )
    stuck_start_ms = stuck_signal.start_timestamp if stuck_signal is not None else 0
    stuck_last_ms = stuck_signal.last_stuck_timestamp if stuck_signal is not None else 0
    return Frame(
        timestamp_ms=timestamp_ms,
        status=enum_name(status_field, debug.unstuck_status),
        process_reason=enum_name(reason_field, debug.assist_model_process_reason),
        rule_decision=enum_name(decision_field, rules.rule_decision),
        fp_reasons=tuple(enum_name(reason_field, value) for value in rules.fp_process_reasons),
        fn_reasons=tuple(enum_name(reason_field, value) for value in rules.fn_process_reasons),
        active_rules=active_rules,
        lane_change_forbid_timestamp_ms=lane_change_ts or None,
        yield_dynamic_decision=enum_name(
            yield_decision_field, yield_debug.decision_reason
        ),
        yielding_object_id=yield_debug.yielding_object_id or None,
        yielding_object_speed=(
            float(yield_debug.yielding_object_speed)
            if yield_debug.yielding_object_id
            else None
        ),
        yield_hold_cycles=yield_debug.yield_hold_cycles,
        yield_temp_parked_cycles=yield_debug.yield_temp_parked_cycles,
        right_lane_yield_cycles=yield_debug.right_lane_yield_cycles,
        total_yielding_cycles=yield_debug.total_yielding_cycles,
        model_detected=debug.is_stuck_detected_by_model,
        scenario_dnn=optional_double(debug, "scenario_dnn_stuck_likelihood_from_ra_vnode"),
        scenario_dnn_strict=optional_double(
            debug, "scenario_dnn_strict_stuck_likelihood_from_ra_vnode"
        ),
        threshold=debug.stuck_threshold,
        stationary_cycles=debug.stationary_cycle_count,
        non_voluntary_unstuck_reason=enum_name(
            voluntary_reason_field, debug.non_voluntary_unstuck_reason
        ),
        stuck_timer_ms=debug.stuck_status_timer_elapsed_time_in_ms,
        strict_model_detected=debug.is_strict_stuck_detected_by_dnn_model,
        uncertain_stuck=debug.is_uncertain_stuck,
        selected_maneuver_type=enum_name(
            maneuver_type_field, behavior_debug.selected_maneuver_type
        ),
        stuck_signal_start_ms=stuck_start_ms or None,
        stuck_signal_last_ms=stuck_last_ms or None,
        stuck_signal_duration_ms=(
            stuck_last_ms - stuck_start_ms if stuck_start_ms and stuck_last_ms else None
        ),
        stuck_signal_reason=(
            enum_name(stuck_signal_reason_field, stuck_signal.reason)
            if stuck_signal is not None
            else None
        ),
        stuck_signal_score=(
            float(stuck_signal.stuck_score) if stuck_signal is not None else None
        ),
        stuck_signal_object_ids=(
            tuple(stuck_signal.object_ids) if stuck_signal is not None else ()
        ),
        unstuck_modes=(
            tuple(stuck_debug.unstuck_mode_seed.unstuck_modes)
            if stuck_debug is not None
            else ()
        ),
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


def repeated_reason_histogram(frames: list[Frame], attribute: str) -> dict[str, int]:
    return dict(
        Counter(
            reason
            for frame in frames
            for reason in getattr(frame, attribute)
        )
    )


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
        "road_fp_reason_frames": repeated_reason_histogram(road, "fp_reasons"),
        "sim_fp_reason_frames": repeated_reason_histogram(sim, "fp_reasons"),
        "road_yield_dynamic_decisions": histogram(road, "yield_dynamic_decision"),
        "sim_yield_dynamic_decisions": histogram(sim, "yield_dynamic_decision"),
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
        f"yield={frame['yield_dynamic_decision']} "
        f"yield_obj={frame['yielding_object_id']} "
        f"yield_speed={frame['yielding_object_speed']} "
        f"yield_hold={frame['yield_hold_cycles']} "
        f"scen_dnn={frame['scenario_dnn']} strict_dnn={frame['scenario_dnn_strict']} "
        f"threshold={frame['threshold']} strict={frame['strict_model_detected']} "
        f"uncertain={frame['uncertain_stuck']} "
        f"voluntary_exit={frame['non_voluntary_unstuck_reason']} "
        f"stuck_timer_ms={frame['stuck_timer_ms']:.0f} "
        f"stuck_signal_ms={frame['stuck_signal_duration_ms']} "
        f"stuck_reason={frame['stuck_signal_reason']} "
        f"unstuck_modes={frame['unstuck_modes']} "
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
    print(f"road FP frames: {result['road_fp_reason_frames']}")
    print(f"sim FP frames:  {result['sim_fp_reason_frames']}")
    print(f"road yield decisions: {result['road_yield_dynamic_decisions']}")
    print(f"sim yield decisions:  {result['sim_yield_dynamic_decisions']}")
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
