#!/usr/bin/env python3
"""Compare road and simulation ROS1 bags by topic count and record timestamp."""

from __future__ import annotations

import argparse
import bisect
import contextlib
import io
import json
import logging
import math
import statistics
import sys
from pathlib import Path
from typing import Any

try:
    from rosbags.rosbag1 import Reader
except ModuleNotFoundError:
    Reader = None
    voyager_sdk = Path("/opt/voy-sdk/lib/python3/dist-packages")
    if voyager_sdk.is_dir():
        sys.path.insert(0, str(voyager_sdk))
    import rosbag

    logging.getLogger("rosbag").setLevel(logging.ERROR)


DEFAULT_TOPICS = [
    "/planning/seed",
    "/planning/planning_debug",
    "/planning/remote_assist_model_debug",
    "/planning/assist_request",
    "/planning/stuck_detection_recall_signal",
]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def nearest_deltas_ms(source: list[int], target: list[int]) -> list[float]:
    """Return the absolute delta from each source timestamp to its nearest target."""
    if not source or not target:
        return []
    result = []
    for timestamp in source:
        index = bisect.bisect_left(target, timestamp)
        candidates = []
        if index < len(target):
            candidates.append(abs(target[index] - timestamp))
        if index:
            candidates.append(abs(target[index - 1] - timestamp))
        result.append(min(candidates) / 1_000_000)
    return result


def read_bag(path: Path, topics: list[str]) -> dict[str, Any]:
    timestamps = {topic: [] for topic in topics}
    if Reader is None:
        return read_bag_with_rosbag(path, timestamps)

    with Reader(path) as reader:
        counts = {topic: info.msgcount for topic, info in reader.topics.items()}
        connections = [
            connection
            for connection in reader.connections
            if connection.topic in timestamps
        ]
        for connection, timestamp, _ in reader.messages(connections=connections):
            timestamps[connection.topic].append(timestamp)

        return {
            "path": str(path.resolve()),
            "size_gb": round(path.resolve().stat().st_size / 1024**3, 3),
            "start_ms": reader.start_time // 1_000_000,
            "end_ms": reader.end_time // 1_000_000,
            "duration_s": round(reader.duration / 1_000_000_000, 3),
            "topic_count": len(counts),
            "counts": counts,
            "timestamps": timestamps,
        }


def read_bag_with_rosbag(
    path: Path, timestamps: dict[str, list[int]]
) -> dict[str, Any]:
    # The SDK prints a known PlanningSeed placeholder-md5 warning to stderr even
    # for raw reads. Keep command output machine-readable while exceptions propagate.
    with contextlib.redirect_stderr(io.StringIO()):
        with rosbag.Bag(str(path)) as bag:
            counts = {
                topic: info.message_count
                for topic, info in bag.get_type_and_topic_info().topics.items()
            }
            for topic, _, timestamp in bag.read_messages(
                topics=list(timestamps), raw=True
            ):
                timestamps[topic].append(timestamp.to_nsec())
            start_ns = int(bag.get_start_time() * 1_000_000_000)
            end_ns = int(bag.get_end_time() * 1_000_000_000)
            return {
                "path": str(path.resolve()),
                "size_gb": round(path.resolve().stat().st_size / 1024**3, 3),
                "start_ms": start_ns // 1_000_000,
                "end_ms": end_ns // 1_000_000,
                "duration_s": round((end_ns - start_ns) / 1_000_000_000, 3),
                "topic_count": len(counts),
                "counts": counts,
                "timestamps": timestamps,
            }


def summarize_topic(
    road_timestamps: list[int],
    sim_timestamps: list[int],
    tolerance_ms: float,
) -> dict[str, Any]:
    road_deltas = nearest_deltas_ms(road_timestamps, sim_timestamps)
    sim_deltas = nearest_deltas_ms(sim_timestamps, road_timestamps)

    def coverage(deltas: list[float]) -> float | None:
        if not deltas:
            return None
        return round(sum(delta <= tolerance_ms for delta in deltas) / len(deltas), 4)

    return {
        "road_count": len(road_timestamps),
        "sim_count": len(sim_timestamps),
        "count_delta": len(sim_timestamps) - len(road_timestamps),
        "road_coverage": coverage(road_deltas),
        "sim_coverage": coverage(sim_deltas),
        "nearest_delta_ms": {
            "median": round(statistics.median(road_deltas), 3) if road_deltas else None,
            "p95": round(percentile(road_deltas, 0.95), 3) if road_deltas else None,
            "max": round(max(road_deltas), 3) if road_deltas else None,
        },
    }


def compare(
    road_path: Path,
    sim_path: Path,
    topics: list[str],
    tolerance_ms: float,
) -> dict[str, Any]:
    road = read_bag(road_path, topics)
    sim = read_bag(sim_path, topics)
    road_topics = set(road["counts"])
    sim_topics = set(sim["counts"])
    topic_results = {
        topic: summarize_topic(
            road["timestamps"][topic], sim["timestamps"][topic], tolerance_ms
        )
        for topic in topics
    }
    for bag in (road, sim):
        del bag["timestamps"]
        del bag["counts"]
    return {
        "road": road,
        "sim": sim,
        "topic_sets": {
            "common_count": len(road_topics & sim_topics),
            "road_only": sorted(road_topics - sim_topics),
            "sim_only": sorted(sim_topics - road_topics),
        },
        "alignment_tolerance_ms": tolerance_ms,
        "topics": topic_results,
    }


def print_text(result: dict[str, Any]) -> None:
    road = result["road"]
    sim = result["sim"]
    topic_sets = result["topic_sets"]
    print(
        f"road: {road['path']} ({road['size_gb']} GB, {road['duration_s']} s, "
        f"{road['topic_count']} topics)"
    )
    print(
        f"sim:  {sim['path']} ({sim['size_gb']} GB, {sim['duration_s']} s, "
        f"{sim['topic_count']} topics)"
    )
    print(
        f"topic sets: {topic_sets['common_count']} common, "
        f"{len(topic_sets['road_only'])} road-only, "
        f"{len(topic_sets['sim_only'])} sim-only"
    )
    print(f"timestamp tolerance: {result['alignment_tolerance_ms']} ms")
    print()
    print(
        f"{'topic':48} {'road':>6} {'sim':>6} {'delta':>7} "
        f"{'road cov':>9} {'sim cov':>9} {'p95 ms':>9}"
    )
    for topic, summary in result["topics"].items():
        road_coverage = summary["road_coverage"]
        sim_coverage = summary["sim_coverage"]
        p95 = summary["nearest_delta_ms"]["p95"]
        road_cov_text = "-" if road_coverage is None else f"{road_coverage:.1%}"
        sim_cov_text = "-" if sim_coverage is None else f"{sim_coverage:.1%}"
        p95_text = "-" if p95 is None else f"{p95:.3f}"
        print(
            f"{topic:48} {summary['road_count']:6d} {summary['sim_count']:6d} "
            f"{summary['count_delta']:+7d} {road_cov_text:>9} "
            f"{sim_cov_text:>9} {p95_text:>9}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare road.bag and sim.bag topic counts and timestamps"
    )
    parser.add_argument("road", type=Path, help="road bag path")
    parser.add_argument("sim", type=Path, help="simulation bag path")
    parser.add_argument(
        "--topic",
        action="append",
        dest="topics",
        help="topic to compare; repeat for multiple topics",
    )
    parser.add_argument(
        "--tolerance-ms",
        type=float,
        default=50.0,
        help="nearest timestamp match tolerance (default: 50 ms)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()

    for path in (args.road, args.sim):
        if not path.is_file():
            parser.error(f"bag does not exist: {path}")
    if args.tolerance_ms < 0:
        parser.error("--tolerance-ms must be non-negative")

    result = compare(
        args.road, args.sim, args.topics or DEFAULT_TOPICS, args.tolerance_ms
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_text(result)


if __name__ == "__main__":
    main()
