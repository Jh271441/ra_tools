"""Run the road-bag and EzSim reproduction workflow for one Trail scenario."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

if __package__:
    from .ezsim import EzSimClient, get_trail_trip_segment
else:
    from ezsim import EzSimClient, get_trail_trip_segment


RA_TOPICS = [
    "/planning/seed",
    "/planning/planning_debug",
    "/planning/remote_assist_model_debug",
    "/planning/assist_request",
    "/planning/stuck_detection_recall_signal",
]
DEFAULT_ROAD_TOPICS_FILE = Path(__file__).resolve().parent / "default_road_topics.txt"
PROTOBUF_PYTHON_WARNING = (
    "Warning: the Protobuf library implementation is in Python, "
    "which could significantly impact performance."
)


def voy_sdk_env(
    binary_id: int | None,
    protobuf_implementation: str = "python",
) -> dict[str, str]:
    env = os.environ.copy()
    binary_root = Path.home() / ".voyager/ezsim/binary"
    requested_lib = binary_root / str(binary_id) / "tmp/lib" if binary_id else None
    fallback_lib = binary_root / "1665523/tmp/lib"
    lib_dir = requested_lib if requested_lib and requested_lib.is_dir() else fallback_lib
    if lib_dir.is_dir():
        env["LD_LIBRARY_PATH"] = ":".join(
            item for item in [str(lib_dir), env.get("LD_LIBRARY_PATH", "")] if item
        )
    sdk_python = "/opt/voy-sdk/lib/python3/dist-packages"
    env["PYTHONPATH"] = ":".join(
        item for item in [sdk_python, env.get("PYTHONPATH", "")] if item
    )
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = protobuf_implementation
    return env


def road_download_command(
    output: Path,
    trip_id: str,
    start_ms: int,
    end_ms: int,
    topics: list[str] | None = None,
) -> list[str]:
    voy_bag = shutil.which("voy-bag") or "/home/didi/.local/bin/voy-bag"
    command = [
        voy_bag,
        "download",
        str(output),
        "-t",
        trip_id,
        "-s",
        str(start_ms),
        "-e",
        str(end_ms),
    ]
    if topics:
        command.extend(["-T", *topics])
    return command


def normalize_topics(topics: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for topic in topics:
        value = topic.strip()
        if not value.startswith("/"):
            raise ValueError(f"Road topic must start with '/': {topic!r}")
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def load_topic_file(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Road topic config not found: {path}")
    topics = [
        line.strip()
        for line in path.read_text(encoding="utf8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    normalized = normalize_topics(topics)
    if not normalized:
        raise RuntimeError(f"Road topic config is empty: {path}")
    return normalized


def filtered_bag_name(topics: list[str], custom: bool) -> str:
    if not custom:
        return "road_filtered.bag"
    digest = hashlib.sha256("\n".join(sorted(topics)).encode("utf8")).hexdigest()[:8]
    return f"road_filtered_{digest}.bag"


def road_bag_name(topics_source_type: str, topics: list[str]) -> str:
    if topics_source_type in {
        "scenario_sim_bag",
        "explicit_sim_bag",
        "default_sim_snapshot",
    }:
        return "road.bag"
    if topics_source_type == "raw":
        return "road_raw.bag"
    if topics_source_type == "ra_default":
        return "road_filtered.bag"
    return filtered_bag_name(topics, custom=True)


def road_download_signature(
    trip_id: str,
    start_ms: int,
    end_ms: int,
    topics: list[str],
) -> str:
    payload = {
        "trip_id": trip_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "topics": sorted(topics),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf8"
    )
    return hashlib.sha256(encoded).hexdigest()


def completion_marker_matches(path: Path, signature: str) -> bool:
    if not path.is_file():
        return False
    try:
        marker = json.loads(path.read_text(encoding="utf8"))
    except (json.JSONDecodeError, OSError):
        return False
    return marker.get("signature") == signature


def write_completion_marker(path: Path, signature: str) -> None:
    path.write_text(
        json.dumps({"signature": signature}, indent=2) + "\n",
        encoding="utf8",
    )


def ensure_nofile_limit(minimum: int) -> tuple[int, int]:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = min(max(soft, minimum), hard)
    if target > soft:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    return resource.getrlimit(resource.RLIMIT_NOFILE)


def relay_download_stderr(stream: Any) -> None:
    for line in stream:
        if line.strip() == PROTOBUF_PYTHON_WARNING:
            continue
        sys.stderr.write(line)
        sys.stderr.flush()


def run_download(
    command: list[str],
    env: dict[str, str],
    cwd: Path,
    output: Path,
    stall_warning_seconds: int,
) -> None:
    process = subprocess.Popen(
        command,
        env=env,
        cwd=cwd,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        bufsize=1,
    )
    assert process.stderr is not None
    stderr_thread = threading.Thread(
        target=relay_download_stderr,
        args=(process.stderr,),
        daemon=True,
    )
    stderr_thread.start()

    last_size = output.stat().st_size if output.exists() else 0
    last_change = time.monotonic()
    last_report = 0.0
    last_stall_warning = 0.0
    while process.poll() is None:
        now = time.monotonic()
        size = output.stat().st_size if output.exists() else 0
        if size != last_size:
            last_size = size
            last_change = now
        if now - last_report >= 30:
            print(f"[road-download] output_size={size / (1024 ** 3):.2f} GiB")
            last_report = now
        stalled_for = now - last_change
        if (
            stall_warning_seconds > 0
            and stalled_for >= stall_warning_seconds
            and now - last_stall_warning >= 60
        ):
            print(
                f"[road-download] warning: output has not grown for "
                f"{int(stalled_for)} seconds; voy-bag is still running",
                file=sys.stderr,
            )
            last_stall_warning = now
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    stderr_thread.join(timeout=5)
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def topic_counts(path: Path, env: dict[str, str]) -> dict[str, int]:
    code = """
import json
import rosbag
import sys

topics = json.loads(sys.argv[2])
with rosbag.Bag(sys.argv[1]) as bag:
    info = bag.get_type_and_topic_info().topics
    print(json.dumps({t: info[t].message_count if t in info else 0 for t in topics}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), json.dumps(RA_TOPICS)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def bag_topics(path: Path, env: dict[str, str]) -> list[str]:
    code = """
import json
import rosbag
import sys

with rosbag.Bag(sys.argv[1]) as bag:
    print(json.dumps(sorted(bag.get_type_and_topic_info().topics)))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def replace_symlink(link: Path, target: Path) -> None:
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise RuntimeError(f"Refusing to replace non-symlink: {link}")
    link.symlink_to(target)


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a road bag and run EzSim for one Trail scenario."
    )
    parser.add_argument("scenario_id", help="Trail scenario id")
    build = parser.add_mutually_exclusive_group(required=True)
    build.add_argument("--binary", type=int, help="Road-test Orion binary id")
    build.add_argument("--build", help="Registered EzSim build alias, hash, or path")
    parser.add_argument(
        "--output-root",
        default="/home/didi/ra_bags",
        help="Root directory for per-scenario artifacts",
    )
    parser.add_argument("--warmup", type=int, default=5000, help="EzSim warmup in ms")
    parser.add_argument(
        "--road-prefix-ms",
        type=int,
        default=5000,
        help="Extra road-bag time before scenario start",
    )
    parser.add_argument("--poll", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--force-road-download", action="store_true")
    parser.add_argument("--skip-road-download", action="store_true")
    parser.add_argument(
        "--road-only",
        action="store_true",
        help="Download/reuse the road bag and stop before starting EzSim",
    )
    parser.add_argument(
        "--nofile-limit",
        type=int,
        default=65536,
        help="Soft file-descriptor limit used by voy-bag",
    )
    parser.add_argument(
        "--stall-warning-seconds",
        type=int,
        default=300,
        help="Warn when the road bag output has not grown for this duration",
    )
    parser.add_argument(
        "--download-protobuf",
        choices=["cpp", "python"],
        default="python",
        help="Protobuf implementation used by voy-bag",
    )
    parser.add_argument(
        "--filtered-road",
        action="store_true",
        help="Download only RA topics instead of the complete raw road bag",
    )
    parser.add_argument(
        "--raw-road",
        action="store_true",
        help="Download the complete raw road bag without a topic filter",
    )
    parser.add_argument(
        "--road-topic",
        action="append",
        default=[],
        metavar="TOPIC",
        help="Road bag topic to include; repeat for multiple topics",
    )
    parser.add_argument(
        "--road-topics-from-sim-bag",
        nargs="?",
        const="AUTO",
        metavar="PATH",
        help="Use topics from a sim bag; defaults to the scenario sim.bag symlink",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query Trail and print planned paths/commands without downloading or simulating",
    )
    args = parser.parse_args()
    selectors = sum(
        [
            bool(args.raw_road),
            bool(args.filtered_road),
            bool(args.road_topic),
            args.road_topics_from_sim_bag is not None,
        ]
    )
    if selectors > 1:
        parser.error(
            "choose only one of --raw-road, --filtered-road, --road-topic, "
            "or --road-topics-from-sim-bag"
        )
    return args


def main() -> None:
    args = parse_args()
    info = get_trail_trip_segment(args.scenario_id)
    segment = info["trip_segment"]
    work_dir = Path(args.output_root).expanduser() / f"scenario_{args.scenario_id}"
    analysis_env = voy_sdk_env(args.binary, protobuf_implementation="python")
    topics_source_bag = None
    topics_source_type = ""
    if args.road_topics_from_sim_bag is not None:
        topics_source_bag = (
            work_dir / "sim.bag"
            if args.road_topics_from_sim_bag == "AUTO"
            else Path(args.road_topics_from_sim_bag).expanduser().resolve()
        )
        if not topics_source_bag.exists():
            raise FileNotFoundError(f"Sim bag not found: {topics_source_bag}")
        custom_topics = normalize_topics(bag_topics(topics_source_bag, analysis_env))
        if not custom_topics:
            raise RuntimeError(f"Sim bag has no topics: {topics_source_bag}")
        print(f"Loaded {len(custom_topics)} topics from sim bag: {topics_source_bag}")
        topics_source_type = "explicit_sim_bag"
    elif args.raw_road:
        custom_topics = []
        topics_source_type = "raw"
    elif args.filtered_road:
        custom_topics = list(RA_TOPICS)
        topics_source_type = "ra_default"
    elif args.road_topic:
        custom_topics = normalize_topics(args.road_topic)
        topics_source_type = "custom"
    else:
        auto_sim_bag = work_dir / "sim.bag"
        if auto_sim_bag.exists():
            topics_source_bag = auto_sim_bag
            custom_topics = normalize_topics(bag_topics(auto_sim_bag, analysis_env))
            if not custom_topics:
                raise RuntimeError(f"Sim bag has no topics: {auto_sim_bag}")
            topics_source_type = "scenario_sim_bag"
            print(f"Loaded {len(custom_topics)} topics from sim bag: {auto_sim_bag}")
        else:
            custom_topics = load_topic_file(DEFAULT_ROAD_TOPICS_FILE)
            topics_source_type = "default_sim_snapshot"
            print(
                f"Loaded {len(custom_topics)} default topics from: "
                f"{DEFAULT_ROAD_TOPICS_FILE}"
            )
    road_topics = custom_topics
    road_mode = "filtered" if road_topics else "raw"
    road_filename = road_bag_name(topics_source_type, road_topics)
    road_bag = work_dir / road_filename
    road_complete = Path(f"{road_bag}.complete")
    start_ms = max(0, int(segment["startTimestamp"]) - args.road_prefix_ms)
    end_ms = int(segment["endTimestamp"])
    download_signature = road_download_signature(
        str(segment["tripId"]), start_ms, end_ms, road_topics
    )
    download_cmd = road_download_command(
        road_bag,
        str(segment["tripId"]),
        start_ms,
        end_ms,
        topics=road_topics or None,
    )

    metadata: dict[str, Any] = {
        "scenario_id": str(args.scenario_id),
        "scenario_name": info["name"],
        "issue_id": info["issue_id"],
        "trip_segment": segment,
        "road_download_start_ms": start_ms,
        "road_download_end_ms": end_ms,
        "road_download_mode": road_mode,
        "road_download_topics": road_topics or None,
        "road_topics_source_type": topics_source_type,
        "road_topics_source_sim_bag": (
            str(topics_source_bag) if topics_source_bag is not None else None
        ),
        "road_topics_source_file": (
            str(DEFAULT_ROAD_TOPICS_FILE)
            if topics_source_type == "default_sim_snapshot"
            else None
        ),
        "road_topics_source_count": len(road_topics) if road_topics else 0,
        "requested_binary_id": args.binary,
        "requested_build": args.build,
        "warmup_ms": args.warmup,
        "road_bag": str(road_bag),
        "road_download_complete_marker": str(road_complete),
        "road_download_signature": download_signature,
        "road_download_protobuf_implementation": args.download_protobuf,
    }

    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print("Road download command:")
    print(" ".join(download_cmd))
    if not road_topics:
        print("Warning: raw road bag download can use tens of GB of disk space.")
    if args.dry_run:
        return

    work_dir.mkdir(parents=True, exist_ok=True)
    write_metadata(work_dir / "metadata.json", metadata)
    download_env = voy_sdk_env(
        args.binary,
        protobuf_implementation=args.download_protobuf,
    )

    if not args.skip_road_download:
        if (
            road_bag.exists()
            and completion_marker_matches(road_complete, download_signature)
            and not args.force_road_download
        ):
            print(f"Reusing road bag: {road_bag}")
        else:
            if road_bag.exists():
                road_bag.unlink()
            if road_complete.exists():
                road_complete.unlink()
            soft_limit, hard_limit = ensure_nofile_limit(args.nofile_limit)
            metadata["nofile_soft_limit"] = soft_limit
            metadata["nofile_hard_limit"] = hard_limit
            write_metadata(work_dir / "metadata.json", metadata)
            print(f"File descriptor limit: soft={soft_limit} hard={hard_limit}")
            try:
                run_download(
                    download_cmd,
                    env=download_env,
                    cwd=work_dir,
                    output=road_bag,
                    stall_warning_seconds=args.stall_warning_seconds,
                )
            except subprocess.CalledProcessError:
                metadata["workflow_status"] = "road_download_failed"
                write_metadata(work_dir / "metadata.json", metadata)
                raise
            write_completion_marker(road_complete, download_signature)
        metadata["road_download_complete"] = completion_marker_matches(
            road_complete, download_signature
        )
        write_metadata(work_dir / "metadata.json", metadata)

    if args.road_only:
        metadata["workflow_status"] = "road_download_complete"
        write_metadata(work_dir / "metadata.json", metadata)
        print(f"Road-only workflow complete: {road_bag}")
        return

    client = EzSimClient()
    sim = client.start_by_scenario_id(
        scenario_id=args.scenario_id,
        warmup_ms=args.warmup,
        skip_map_update=False,
        skip_model_update=False,
        binary_id=args.binary,
        build=args.build,
    )
    sim_id = sim["id"]
    print(f"EzSim created: {sim_id}")
    final = client.wait(sim_id, poll=args.poll, timeout=args.timeout)
    metadata["sim_id"] = sim_id
    metadata["sim_status"] = final.get("status")
    metadata["sim_failure"] = final.get("failure")
    metadata["sim_durations"] = final.get("durations", {})
    sim_options = final.get("options", {})
    metadata["sim_binary_id"] = sim_options.get("binary_id")
    metadata["sim_build_dir_hash"] = final.get("build_dir_hash")
    metadata["sim_runtime_dir"] = final.get("sim_runtime_dir")
    metadata["sim_server_version"] = final.get("server_version")
    metadata["sim_skip_map_update"] = sim_options.get("skip_map_update")
    metadata["sim_skip_model_update"] = sim_options.get("skip_model_update")

    sim_dir = Path.home() / ".voyager/ezsim/simulation" / sim_id
    sim_bag = sim_dir / "output.bag"
    events_log = sim_dir / "events.log"
    metadata["sim_artifact_dir"] = str(sim_dir)
    metadata["sim_bag"] = str(sim_bag)
    metadata["events_log"] = str(events_log)

    if final.get("status") != "Success":
        write_metadata(work_dir / "metadata.json", metadata)
        raise RuntimeError(
            f"EzSim failed: {final.get('status')}: {final.get('failure', '')}"
        )
    if not sim_bag.exists():
        raise FileNotFoundError(f"EzSim output bag not found: {sim_bag}")

    replace_symlink(work_dir / "sim.bag", sim_bag)
    if events_log.exists():
        replace_symlink(work_dir / "events.log", events_log)

    counts: dict[str, Any] = {"sim": topic_counts(sim_bag, analysis_env)}
    if road_bag.exists():
        counts["road"] = topic_counts(road_bag, analysis_env)
    metadata["topic_counts"] = counts
    write_metadata(work_dir / "metadata.json", metadata)

    print("Topic counts:")
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print(f"Artifacts: {work_dir}")


if __name__ == "__main__":
    main()
