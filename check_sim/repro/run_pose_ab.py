#!/usr/bin/env python3
"""Run two EzSim experiments that isolate ego pose and smart-agent effects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

if __package__:
    from .ezsim import DEFAULT_EXTRA_ARGS, EzSimClient, get_trail_trip_segment
else:
    from ezsim import DEFAULT_EXTRA_ARGS, EzSimClient, get_trail_trip_segment


EXPERIMENTS = {
    "replay_road_pose": (
        DEFAULT_EXTRA_ARGS + " --sim_overwrite_ego_pose_with_trip_pose"
    ),
    "disable_smart_agent": DEFAULT_EXTRA_ARGS + " --sim_smart_agent=false",
}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8")


def replace_symlink(link: Path, target: Path) -> None:
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise RuntimeError(f"Refusing to replace non-symlink: {link}")
    link.symlink_to(target)


def existing_success(metadata_path: Path) -> dict[str, Any] | None:
    if not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf8"))
    sim_bag = Path(metadata.get("sim_bag", ""))
    if metadata.get("sim_status") == "Success" and sim_bag.is_file():
        return metadata
    return None


def run_experiment(
    client: EzSimClient,
    *,
    scenario_id: str,
    binary: int | None,
    build: str | None,
    warmup_ms: int,
    poll: int,
    timeout: int,
    name: str,
    extra_args: str,
    output_dir: Path,
    road_bag: Path,
    trip_segment: dict[str, Any],
    force: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "metadata.json"
    if not force:
        previous = existing_success(metadata_path)
        if previous is not None:
            print(f"[{name}] reusing successful sim {previous['sim_id']}")
            return previous

    metadata: dict[str, Any] = {
        "scenario_id": scenario_id,
        "experiment": name,
        "trip_segment": trip_segment,
        "requested_binary_id": binary,
        "requested_build": build,
        "warmup_ms": warmup_ms,
        "extra_args": extra_args,
        "road_bag": str(road_bag),
        "sim_status": "Starting",
    }
    write_json(metadata_path, metadata)
    print(f"[{name}] starting EzSim")
    created = client.start_by_scenario_id(
        scenario_id=scenario_id,
        extra_args=extra_args,
        warmup_ms=warmup_ms,
        skip_map_update=False,
        skip_model_update=False,
        binary_id=binary,
        build=build,
    )
    sim_id = created["id"]
    metadata["sim_id"] = sim_id
    metadata["sim_status"] = created.get("status", "Created")
    write_json(metadata_path, metadata)
    print(f"[{name}] created {sim_id}")

    final = client.wait(sim_id, poll=poll, timeout=timeout)
    sim_dir = Path.home() / ".voyager/ezsim/simulation" / sim_id
    sim_bag = sim_dir / "output.bag"
    events_log = sim_dir / "events.log"
    metadata.update(
        {
            "sim_status": final.get("status"),
            "sim_failure": final.get("failure", ""),
            "sim_durations": final.get("durations", {}),
            "sim_options": final.get("options", {}),
            "sim_artifact_dir": str(sim_dir),
            "sim_bag": str(sim_bag),
            "events_log": str(events_log),
        }
    )
    write_json(metadata_path, metadata)
    if final.get("status") != "Success":
        raise RuntimeError(
            f"[{name}] EzSim failed: {final.get('status')}: "
            f"{final.get('failure', '')}"
        )
    if not sim_bag.is_file():
        raise FileNotFoundError(f"[{name}] sim bag not found: {sim_bag}")

    replace_symlink(output_dir / "road.bag", road_bag.resolve())
    replace_symlink(output_dir / "sim.bag", sim_bag.resolve())
    if events_log.is_file():
        replace_symlink(output_dir / "events.log", events_log.resolve())
    print(f"[{name}] complete: {output_dir}")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario_id")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--binary", type=int)
    selector.add_argument("--build")
    parser.add_argument("--output-root", default="/home/didi/ra_bags")
    parser.add_argument("--warmup", type=int, default=5000)
    parser.add_argument("--poll", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--server", help="EzSim server URL")
    parser.add_argument(
        "--experiment",
        action="append",
        choices=sorted(EXPERIMENTS),
        help="run only this experiment; repeat to select both",
    )
    parser.add_argument("--force", action="store_true", help="rerun successful experiments")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario_dir = Path(args.output_root).expanduser() / f"scenario_{args.scenario_id}"
    source_metadata_path = scenario_dir / "metadata.json"
    if not source_metadata_path.is_file():
        raise FileNotFoundError(
            f"Base scenario metadata not found: {source_metadata_path}. "
            "Run scenario_repro.py first."
        )
    source_metadata = json.loads(source_metadata_path.read_text(encoding="utf8"))
    road_bag = Path(source_metadata["road_bag"])
    if not road_bag.is_file():
        raise FileNotFoundError(f"Road bag not found: {road_bag}")
    trip_segment = source_metadata.get("trip_segment")
    if not trip_segment:
        trip_segment = get_trail_trip_segment(args.scenario_id)["trip_segment"]

    selected = args.experiment or list(EXPERIMENTS)
    client = EzSimClient(server=args.server)
    print(f"EzSim server: {client.base_url}")
    results = {}
    for name in selected:
        output_dir = scenario_dir / "experiments" / name
        results[name] = run_experiment(
            client,
            scenario_id=args.scenario_id,
            binary=args.binary,
            build=args.build,
            warmup_ms=args.warmup,
            poll=args.poll,
            timeout=args.timeout,
            name=name,
            extra_args=EXPERIMENTS[name],
            output_dir=output_dir,
            road_bag=road_bag,
            trip_segment=trip_segment,
            force=args.force,
        )

    summary_path = scenario_dir / "experiments" / "summary.json"
    write_json(summary_path, results)
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
