"""Run the road-bag and EzSim reproduction workflow for one Trail scenario."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
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


def voy_sdk_env(binary_id: int | None) -> dict[str, str]:
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
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    return env


def road_download_command(
    output: Path,
    trip_id: str,
    start_ms: int,
    end_ms: int,
) -> list[str]:
    voy_bag = shutil.which("voy-bag") or "/home/didi/.local/bin/voy-bag"
    return [
        voy_bag,
        "download",
        str(output),
        "-t",
        trip_id,
        "-s",
        str(start_ms),
        "-e",
        str(end_ms),
        "-T",
        *RA_TOPICS,
    ]


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
    road_bag = work_dir / "road.bag"
    start_ms = max(0, int(segment["startTimestamp"]) - args.road_prefix_ms)
    end_ms = int(segment["endTimestamp"])
    download_cmd = road_download_command(
        road_bag, str(segment["tripId"]), start_ms, end_ms
    )

    metadata: dict[str, Any] = {
        "scenario_id": str(args.scenario_id),
        "scenario_name": info["name"],
        "issue_id": info["issue_id"],
        "trip_segment": segment,
        "road_download_start_ms": start_ms,
        "road_download_end_ms": end_ms,
        "requested_binary_id": args.binary,
        "requested_build": args.build,
        "warmup_ms": args.warmup,
        "road_bag": str(road_bag),
    }

    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print("Road download command:")
    print(" ".join(download_cmd))
    if args.dry_run:
        return

    work_dir.mkdir(parents=True, exist_ok=True)
    write_metadata(work_dir / "metadata.json", metadata)
    env = voy_sdk_env(args.binary)

    if not args.skip_road_download:
        if road_bag.exists() and not args.force_road_download:
            print(f"Reusing road bag: {road_bag}")
        else:
            if road_bag.exists():
                road_bag.unlink()
            subprocess.run(download_cmd, env=env, cwd=work_dir, check=True)

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

    counts: dict[str, Any] = {"sim": topic_counts(sim_bag, env)}
    if road_bag.exists():
        counts["road"] = topic_counts(road_bag, env)
    metadata["topic_counts"] = counts
    write_metadata(work_dir / "metadata.json", metadata)

    print("Topic counts:")
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print(f"Artifacts: {work_dir}")


if __name__ == "__main__":
    main()
