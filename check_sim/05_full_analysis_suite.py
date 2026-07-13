#!/usr/bin/env python3

import argparse
import os

import numpy as np

if __package__:
    from .model_io import create_session, run_inference
    from .planning_seed_reader import get_frame, get_tensor_dict, iter_frames
    from .tensor_io import tensor_dict_to_features
else:
    from model_io import create_session, run_inference
    from planning_seed_reader import get_frame, get_tensor_dict, iter_frames
    from tensor_io import tensor_dict_to_features


class VoyagerAnalyzer:
    def __init__(self, model_path, intra_op_threads=4):
        self.model_path = model_path
        self.intra_op_threads = intra_op_threads
        self.session = None

    def _session(self):
        if self.session is None:
            self.session = create_session(self.model_path, self.intra_op_threads)
        return self.session

    def infer(self, features):
        return run_inference(self._session(), features)

    def analyze_single_frame(
        self, road_path, sim_path, target_ms, offset, road_output, sim_output
    ):
        print(f"\n[1] Analyzing Specific Frame ({offset:+d} offset from {target_ms}ms)")
        road_frame = get_frame(road_path, target_ms, offset=offset)
        sim_frame = get_frame(sim_path, target_ms, offset=offset)
        if road_frame is None or sim_frame is None:
            raise RuntimeError("Could not find the requested frame in both bags")

        road_tensor_dict = get_tensor_dict(road_frame.message)
        sim_tensor_dict = get_tensor_dict(sim_frame.message)
        if not road_tensor_dict or not sim_tensor_dict:
            raise RuntimeError("TensorDict is empty in one or both selected frames")
        road_features = tensor_dict_to_features(road_tensor_dict)
        sim_features = tensor_dict_to_features(sim_tensor_dict)

        print(f"road frame: {road_frame.time_s:.6f}")
        print(f"sim frame : {sim_frame.time_s:.6f}")
        print("\nSignificant Input Differences (>0.01):")
        for name in sorted(road_features):
            diff = np.max(
                np.abs(
                    road_features[name].astype(float)
                    - sim_features[name].astype(float)
                )
            )
            if diff > 0.01:
                print(f"  {name:<30} | Max Diff: {diff:.4f}")

        print("\n[2] Running Inference for this frame...")
        road_outputs = self.infer(road_features)
        sim_outputs = self.infer(sim_features)
        print(
            f"{'Output Name':<30} | {'Road Val':<15} | "
            f"{'Sim Val':<15} | {'Diff':<10}"
        )
        for name, road_value in road_outputs.items():
            road_score = road_value.flatten()[0]
            sim_score = sim_outputs[name].flatten()[0]
            print(
                f"{name:<30} | {road_score:<15.4f} | {sim_score:<15.4f} | "
                f"{abs(road_score - sim_score):<10.4f}"
            )

        print("\n[3] Exporting NPZ files...")
        np.savez(road_output, **road_features)
        np.savez(sim_output, **sim_features)
        print(f"Saved {road_output} and {sim_output}")

    def process_full_bag(self, road_path, sim_path):
        from tqdm import tqdm

        print("\n[4] Full Bag Inference Comparison")

        def get_inference_series(path):
            outputs = []
            description = f"Inference {os.path.basename(path)}"
            for frame in tqdm(iter_frames(path), desc=description):
                tensor_dict = get_tensor_dict(frame.message)
                if not tensor_dict:
                    outputs.append(None)
                    continue
                outputs.append(self.infer(tensor_dict_to_features(tensor_dict)))
            return outputs

        road_outputs = get_inference_series(road_path)
        sim_outputs = get_inference_series(sim_path)

        print("\nFull Sequence Summary (stuck_score):")
        for index, (road_output, sim_output) in enumerate(
            zip(road_outputs, sim_outputs)
        ):
            if road_output and sim_output:
                road_score = float(road_output["stuck_score"].reshape(-1)[0])
                sim_score = float(sim_output["stuck_score"].reshape(-1)[0])
                print(
                    f"Frame {index}: Road={road_score:.4f}, Sim={sim_score:.4f}, "
                    f"Diff={abs(road_score - sim_score):.4f}"
                )
            elif road_output or sim_output:
                print(f"Frame {index}: Mismatch (One side is empty)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--road", default="road.bag")
    parser.add_argument("--sim", default="sim.bag")
    parser.add_argument("--ts", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--offset", type=int, default=-1)
    parser.add_argument("--road-output", default="road_frame.npz")
    parser.add_argument("--sim-output", default="sim_frame.npz")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--intra-op-threads", type=int, default=4)
    args = parser.parse_args()

    analyzer = VoyagerAnalyzer(args.model, args.intra_op_threads)
    analyzer.analyze_single_frame(
        args.road,
        args.sim,
        args.ts,
        args.offset,
        args.road_output,
        args.sim_output,
    )
    if args.full:
        analyzer.process_full_bag(args.road, args.sim)


if __name__ == "__main__":
    main()
