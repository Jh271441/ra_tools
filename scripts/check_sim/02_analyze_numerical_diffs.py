#!/usr/bin/env python3

import argparse

import numpy as np

from planning_seed_reader import get_frame, get_tensor_dict


def get_values(value):
    result = []
    result.extend(getattr(value, "float_vals", []))
    result.extend(getattr(value, "double_vals", []))
    result.extend(getattr(value, "int_vals", []))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compare TensorDict values at one aligned frame"
    )
    parser.add_argument("--road", default="road.bag")
    parser.add_argument("--sim", default="sim.bag")
    parser.add_argument(
        "--ts", type=int, required=True, help="target timestamp in milliseconds"
    )
    parser.add_argument("--offset", type=int, default=-1)
    parser.add_argument("--threshold", type=float, default=0.01)
    args = parser.parse_args()

    road_frame = get_frame(args.road, args.ts, args.offset)
    sim_frame = get_frame(args.sim, args.ts, args.offset)
    if road_frame is None or sim_frame is None:
        raise RuntimeError("Could not find the requested frame in both bags")

    road = get_tensor_dict(road_frame.message)
    sim = get_tensor_dict(sim_frame.message)
    if not road or not sim:
        raise RuntimeError("TensorDict is empty in one or both selected frames")

    print(f"road frame: {road_frame.time_s:.6f}")
    print(f"sim frame : {sim_frame.time_s:.6f}")
    print(
        f"{'Feature Name':<28} | {'Road [Min, Max]':<25} | "
        f"{'Sim [Min, Max]':<25} | {'Max Abs Diff':<12}"
    )
    print("-" * 100)

    for name in sorted(set(road) | set(sim)):
        road_values = get_values(road[name]) if name in road else []
        sim_values = get_values(sim[name]) if name in sim else []
        if not road_values or not sim_values:
            print(f"{name:<28} | {'MISSING':<25} | {'MISSING':<25} | {'N/A':<12}")
            continue
        if len(road_values) != len(sim_values):
            print(
                f"{name:<28} | Size Mismatch: "
                f"{len(road_values)} vs {len(sim_values)}"
            )
            continue

        road_array = np.asarray(road_values)
        sim_array = np.asarray(sim_values)
        max_diff = float(np.max(np.abs(road_array - sim_array)))
        if max_diff <= args.threshold:
            continue
        road_range = f"[{np.min(road_array):.3f}, {np.max(road_array):.3f}]"
        sim_range = f"[{np.min(sim_array):.3f}, {np.max(sim_array):.3f}]"
        print(f"{name:<28} | {road_range:<25} | {sim_range:<25} | {max_diff:<12.4f}")

        if name == "old_dnn_features":
            indices = np.where(np.abs(road_array - sim_array) > args.threshold)[0]
            print(f"  differing indices: {len(indices)}")
            print(f"  first indices: {indices[:20].tolist()}")


if __name__ == "__main__":
    main()
