"""Run the road-bag and EzSim reproduction workflow for one Trail scenario."""

from __future__ import annotations

import argparse
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

from ezsim_run import EzSimClient, _get_trail_trip_segment


RA_TOPICS = [
    "/planning/seed",
    "/planning/planning_debug",
    "/planning/remote_assist_model_debug",
    "/planning/assist_request",
    "/planning/stuck_detection_recall_signal",
]
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
        "--dry-run",
        action="store_true",
        help="Query Trail and print planned paths/commands without downloading or simulating",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    info = _get_trail_trip_segment(args.scenario_id)
    segment = info["trip_segment"]
    work_dir = Path(args.output_root).expanduser() / f"scenario_{args.scenario_id}"
    road_mode = "filtered" if args.filtered_road else "raw"
    road_bag = work_dir / f"road_{road_mode}.bag"
    road_complete = Path(f"{road_bag}.complete")
    start_ms = max(0, int(segment["startTimestamp"]) - args.road_prefix_ms)
    end_ms = int(segment["endTimestamp"])
    download_cmd = road_download_command(
        road_bag,
        str(segment["tripId"]),
        start_ms,
        end_ms,
        topics=RA_TOPICS if args.filtered_road else None,
    )

    metadata: dict[str, Any] = {
        "scenario_id": str(args.scenario_id),
        "scenario_name": info["name"],
        "issue_id": info["issue_id"],
        "trip_segment": segment,
        "road_download_start_ms": start_ms,
        "road_download_end_ms": end_ms,
        "road_download_mode": road_mode,
        "road_download_topics": RA_TOPICS if args.filtered_road else None,
        "requested_binary_id": args.binary,
        "requested_build": args.build,
        "warmup_ms": args.warmup,
        "road_bag": str(road_bag),
        "road_download_complete_marker": str(road_complete),
        "road_download_protobuf_implementation": args.download_protobuf,
    }

    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print("Road download command:")
    print(" ".join(download_cmd))
    if not args.filtered_road:
        print("Warning: raw road bag download can use tens of GB of disk space.")
    if args.dry_run:
        return

    work_dir.mkdir(parents=True, exist_ok=True)
    write_metadata(work_dir / "metadata.json", metadata)
    analysis_env = voy_sdk_env(args.binary, protobuf_implementation="python")
    download_env = voy_sdk_env(
        args.binary,
        protobuf_implementation=args.download_protobuf,
    )

    if not args.skip_road_download:
        if road_bag.exists() and road_complete.exists() and not args.force_road_download:
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
            road_complete.write_text("complete\n", encoding="ascii")
        metadata["road_download_complete"] = road_complete.exists()
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
