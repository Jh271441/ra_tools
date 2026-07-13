#!/usr/bin/env python3
"""Read protobuf-backed PlanningSeed messages from Voyager ROS1 bags."""

from __future__ import annotations

import contextlib
import io
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator


TOPIC = "/planning/seed"


@lru_cache(maxsize=1)
def _load_runtime():
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

    sdk_path = Path("/opt/voy-sdk/lib/python3/dist-packages")
    if sdk_path.is_dir() and str(sdk_path) not in sys.path:
        sys.path.insert(0, str(sdk_path))

    proto_root = Path(
        os.environ.get(
            "VOYAGER_PROTO_PB",
            "~/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb",
        )
    ).expanduser()
    if not proto_root.is_dir():
        raise RuntimeError(
            "Voyager protobuf Python bindings not found. Set VOYAGER_PROTO_PB "
            f"or build them at {proto_root}"
        )
    if str(proto_root) not in sys.path:
        sys.path.insert(0, str(proto_root))

    import rosbag
    from planner_protos import planning_seed_pb2

    return rosbag, planning_seed_pb2.PlanningSeed


@dataclass(frozen=True)
class SeedFrame:
    time_s: float
    message: object


def _raw_payload(raw_message) -> bytes:
    data = raw_message[1] if isinstance(raw_message, tuple) else raw_message
    if not isinstance(data, bytes) or len(data) < 4:
        raise ValueError("PlanningSeed raw message does not contain a ROS byte payload")

    declared_size = int.from_bytes(data[:4], byteorder="little", signed=False)
    available_size = len(data) - 4
    if declared_size > available_size:
        raise ValueError(
            f"Invalid PlanningSeed payload length: {declared_size} > {available_size}"
        )
    return data[4 : 4 + declared_size]


def _parse_seed(raw_message):
    _, planning_seed = _load_runtime()
    message = planning_seed()
    message.ParseFromString(_raw_payload(raw_message))
    return message


def read_raw_records(path: str | Path, topic: str = TOPIC):
    """Load record timestamps and raw messages without ROS deserialization."""
    rosbag, _ = _load_runtime()
    records = []
    with contextlib.redirect_stderr(io.StringIO()):
        with rosbag.Bag(str(path), "r") as bag:
            for _, raw_message, timestamp in bag.read_messages(
                topics=[topic], raw=True
            ):
                records.append((timestamp.to_sec(), raw_message))
    return records


def get_nearby_frames(
    path: str | Path,
    target_time_ms: int,
    count: int = 1,
    topic: str = TOPIC,
) -> list[dict]:
    records = read_raw_records(path, topic)
    if not records:
        return []

    target_time_s = target_time_ms / 1000.0
    best_index = min(
        range(len(records)), key=lambda index: abs(records[index][0] - target_time_s)
    )
    start = max(0, best_index - count)
    end = min(len(records), best_index + count + 1)
    return [
        {
            "index_offset": index - best_index,
            "time": records[index][0],
            "msg": _parse_seed(records[index][1]),
        }
        for index in range(start, end)
    ]


def get_frame(
    path: str | Path,
    target_time_ms: int,
    offset: int = -1,
    topic: str = TOPIC,
) -> SeedFrame | None:
    records = read_raw_records(path, topic)
    if not records:
        return None

    target_time_s = target_time_ms / 1000.0
    best_index = min(
        range(len(records)), key=lambda index: abs(records[index][0] - target_time_s)
    )
    selected_index = best_index + offset
    if selected_index < 0 or selected_index >= len(records):
        return None
    time_s, raw_message = records[selected_index]
    return SeedFrame(time_s=time_s, message=_parse_seed(raw_message))


def iter_frames(path: str | Path, topic: str = TOPIC) -> Iterator[SeedFrame]:
    """Parse every PlanningSeed frame for explicit full-bag analysis."""
    rosbag, _ = _load_runtime()
    with contextlib.redirect_stderr(io.StringIO()):
        with rosbag.Bag(str(path), "r") as bag:
            for _, raw_message, timestamp in bag.read_messages(
                topics=[topic], raw=True
            ):
                yield SeedFrame(timestamp.to_sec(), _parse_seed(raw_message))


def get_tensor_dict(message):
    return (
        message.behavior_seed
        .assist_stuck_seed
        .assist_stuck_model_output
        .tensor_dict
    )
