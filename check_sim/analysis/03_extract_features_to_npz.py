#!/usr/bin/env python3

import argparse

import numpy as np

if __package__:
    from .features import EXPECTED_SHAPES
    from .planning_seed_reader import get_frame, get_tensor_dict
    from .tensor_io import tensor_dict_to_features
else:
    from features import EXPECTED_SHAPES
    from planning_seed_reader import get_frame, get_tensor_dict
    from tensor_io import tensor_dict_to_features


def extract_features(frame, label):
    tensor_dict = get_tensor_dict(frame.message)
    if not tensor_dict:
        raise RuntimeError(f"TensorDict is empty in selected {label} frame")

    try:
        return tensor_dict_to_features(tensor_dict)
    except (RuntimeError, ValueError) as error:
        raise RuntimeError(f"Invalid {label} TensorDict: {error}") from error


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
