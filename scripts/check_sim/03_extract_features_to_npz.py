#!/usr/bin/env python3

import argparse

import numpy as np

from planning_seed_reader import get_frame, get_tensor_dict


EXPECTED_SHAPES = {
    "old_dnn_features": (1, 9800),
    "ego_geometric": (1, 1, 10, 5, 2),
    "ego_heading": (1, 1, 10, 1),
    "ego_continuous": (1, 1, 10, 3),
    "ego_discrete": (1, 1, 10, 1),
    "ego_trajectory": (1, 1, 10, 100, 4),
    "ego_valid_geometric": (1, 1, 10),
    "ego_valid_history": (1, 1),
    "ego_valid_trajectory": (1, 1, 10),
    "agent_geometric": (1, 50, 30, 5, 2),
    "agent_heading": (1, 50, 30, 1),
    "agent_continuous": (1, 50, 30, 6),
    "agent_discrete": (1, 50, 30, 12),
    "agent_trajectory": (1, 50, 30, 50, 4),
    "agent_valid_geometric": (1, 50, 30),
    "agent_valid_history": (1, 50),
    "agent_valid_trajectory": (1, 50, 30),
    "zone_geometric": (1, 10, 1, 32, 2),
    "zone_discrete": (1, 10, 1, 7),
    "zone_valid_geometric": (1, 10, 1),
    "zone_valid_history": (1, 10),
    "obj_geometric": (1, 20, 1, 10, 2),
    "obj_discrete": (1, 20, 1, 1),
    "obj_valid_geometric": (1, 20, 1),
    "obj_valid_history": (1, 20),
    "tl_continuous": (1, 10, 30, 4),
    "tl_discrete": (1, 10, 30, 5),
    "tl_valid_history": (1, 10),
    "nearby_lane_geometric": (1, 90, 1, 62, 2),
    "nearby_lane_continuous": (1, 90, 1, 2),
    "nearby_lane_discrete": (1, 90, 1, 7),
    "nearby_lane_valid_geometric": (1, 90, 1),
    "nearby_lane_valid_history": (1, 90),
}


def convert_to_numpy(value, target_shape):
    values = list(value.float_vals) + list(value.double_vals) + list(value.int_vals)
    dtype = np.int64 if value.int_vals and not value.float_vals else np.float32
    array = np.asarray(values, dtype=dtype)
    expected_size = int(np.prod(target_shape))
    if array.size != expected_size:
        raise ValueError(
            f"expected shape {target_shape} ({expected_size} values), got {array.size}"
        )
    return array.reshape(target_shape)


def extract_features(frame, label):
    tensor_dict = get_tensor_dict(frame.message)
    if not tensor_dict:
        raise RuntimeError(f"TensorDict is empty in selected {label} frame")

    missing = sorted(set(EXPECTED_SHAPES) - set(tensor_dict))
    if missing:
        raise RuntimeError(f"Missing {label} features: {', '.join(missing)}")
    return {
        name: convert_to_numpy(tensor_dict[name], shape)
        for name, shape in EXPECTED_SHAPES.items()
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract one aligned TensorDict frame to NPZ"
    )
    parser.add_argument("--road", default="road.bag")
    parser.add_argument("--sim", default="sim.bag")
    parser.add_argument(
        "--ts", type=int, required=True, help="target timestamp in milliseconds"
    )
    parser.add_argument("--offset", type=int, default=-1)
    parser.add_argument("--road-output", default="road_features.npz")
    parser.add_argument("--sim-output", default="sim_features.npz")
    args = parser.parse_args()

    road_frame = get_frame(args.road, args.ts, args.offset)
    sim_frame = get_frame(args.sim, args.ts, args.offset)
    if road_frame is None or sim_frame is None:
        raise RuntimeError("Could not find the requested frame in both bags")

    road_features = extract_features(road_frame, "road")
    sim_features = extract_features(sim_frame, "sim")
    np.savez(args.road_output, **road_features)
    np.savez(args.sim_output, **sim_features)
    print(f"road frame: {road_frame.time_s:.6f} -> {args.road_output}")
    print(f"sim frame : {sim_frame.time_s:.6f} -> {args.sim_output}")

    print("\n--- Feature Difference Analysis ---")
    print(f"{'Feature':<30} | {'Max Abs Diff':<15}")
    print("-" * 50)
    for name in EXPECTED_SHAPES:
        diff = np.max(
            np.abs(road_features[name].astype(float) - sim_features[name].astype(float))
        )
        print(f"{name:<30} | {diff:<15.6f}")


if __name__ == "__main__":
    main()
