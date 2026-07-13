#!/usr/bin/env python3

import argparse

import numpy as np

if __package__:
    from .model_io import create_session, run_inference
    from .tensor_io import load_npz
else:
    from model_io import create_session, run_inference
    from tensor_io import load_npz


def main():
    parser = argparse.ArgumentParser(
        description="Compare ONNX outputs for road and sim NPZ inputs"
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--road", default="road_features.npz")
    parser.add_argument("--sim", default="sim_features.npz")
    parser.add_argument("--intra-op-threads", type=int, default=4)
    args = parser.parse_args()

    session = create_session(args.model, args.intra_op_threads)
    print(f"Running inference on {args.road}...")
    road_outputs = run_inference(session, load_npz(args.road))
    print(f"Running inference on {args.sim}...")
    sim_outputs = run_inference(session, load_npz(args.sim))

    print("\n--- Model Output Comparison ---")
    for name, road_value in road_outputs.items():
        sim_value = sim_outputs[name]
        diff = np.max(np.abs(road_value - sim_value))
        print(f"Output: {name}")
        print(f"  Shape: {road_value.shape}")
        print(f"  Max Abs Diff: {diff:.6f}")
        if diff > 0.001:
            print(f"  Road output sample: {road_value.flatten()[:5]}")
            print(f"  Sim  output sample: {sim_value.flatten()[:5]}")
        else:
            print("  Outputs are practically IDENTICAL.")
        print("-" * 30)


if __name__ == "__main__":
    main()
