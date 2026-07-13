import argparse
import importlib.util
from pathlib import Path

import numpy as np
import onnxruntime as ort


DEFAULT_GROUPS = {
    "old_dnn_features": ["old_dnn_features"],
    "ego": [
        "ego_geometric",
        "ego_heading",
        "ego_continuous",
        "ego_discrete",
        "ego_trajectory",
        "ego_valid_geometric",
        "ego_valid_history",
        "ego_valid_trajectory",
    ],
    "agent": [
        "agent_geometric",
        "agent_heading",
        "agent_continuous",
        "agent_discrete",
        "agent_trajectory",
        "agent_valid_geometric",
        "agent_valid_history",
        "agent_valid_trajectory",
    ],
    "zone": [
        "zone_geometric",
        "zone_discrete",
        "zone_valid_geometric",
        "zone_valid_history",
    ],
    "obj": [
        "obj_geometric",
        "obj_discrete",
        "obj_valid_geometric",
        "obj_valid_history",
    ],
    "tl": [
        "tl_continuous",
        "tl_discrete",
        "tl_valid_history",
    ],
    "nearby_lane": [
        "nearby_lane_geometric",
        "nearby_lane_continuous",
        "nearby_lane_discrete",
        "nearby_lane_valid_geometric",
        "nearby_lane_valid_history",
    ],
}

SUBFEATURES = [
    "old_dnn_features",
    "ego_geometric",
    "ego_heading",
    "ego_continuous",
    "ego_discrete",
    "ego_trajectory",
    "ego_valid_geometric",
    "ego_valid_history",
    "ego_valid_trajectory",
    "agent_geometric",
    "agent_heading",
    "agent_continuous",
    "agent_discrete",
    "agent_trajectory",
    "agent_valid_geometric",
    "agent_valid_history",
    "agent_valid_trajectory",
    "zone_geometric",
    "zone_discrete",
    "zone_valid_geometric",
    "zone_valid_history",
    "obj_geometric",
    "obj_discrete",
    "obj_valid_geometric",
    "obj_valid_history",
    "tl_continuous",
    "tl_discrete",
    "tl_valid_history",
    "nearby_lane_geometric",
    "nearby_lane_continuous",
    "nearby_lane_discrete",
    "nearby_lane_valid_geometric",
    "nearby_lane_valid_history",
]


def load_compare_module():
    module_path = Path(__file__).with_name("04_model_inference_compare.py")
    spec = importlib.util.spec_from_file_location("model_compare", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_session_cache(model_paths, compare_module):
    cache = {}
    for model_path in model_paths:
        patched_model = compare_module.ensure_ort_compatible_model(model_path)
        cache[model_path] = ort.InferenceSession(patched_model, providers=["CPUExecutionProvider"])
    return cache


def load_npz_as_dict(path):
    data = np.load(path)
    return {k: data[k] for k in data.files}


def cast_for_input(arr, input_type):
    if "int32" in input_type:
        return arr.astype(np.int32)
    if "int64" in input_type:
        return arr.astype(np.int64)
    return arr.astype(np.float32)


def run_inference(model_path, features, session_cache):
    sess = session_cache[model_path]
    feed = {}
    for model_input in sess.get_inputs():
        feed[model_input.name] = cast_for_input(features[model_input.name], model_input.type)
    outputs = sess.run(None, feed)
    return {output.name: value for output, value in zip(sess.get_outputs(), outputs)}


def replace_features(base, override, names):
    mixed = dict(base)
    for name in names:
        mixed[name] = override[name]
    return mixed


def analyze_output(model_path, road, sim, groups, feature_names, output_name, compare_module):
    road_out = run_inference(model_path, road, compare_module)
    sim_out = run_inference(model_path, sim, compare_module)
    road_score = float(road_out[output_name].reshape(-1)[0])
    sim_score = float(sim_out[output_name].reshape(-1)[0])
    total_diff = sim_score - road_score

    group_rows = []
    for group_name, names in groups.items():
        mixed = replace_features(road, sim, names)
        score = float(run_inference(model_path, mixed, compare_module)[output_name].reshape(-1)[0])
        group_rows.append((group_name, score, score - road_score, sim_score - score))
    group_rows.sort(key=lambda row: abs(row[2]), reverse=True)

    feature_rows = []
    for feature_name in feature_names:
        mixed = replace_features(road, sim, [feature_name])
        score = float(run_inference(model_path, mixed, compare_module)[output_name].reshape(-1)[0])
        feature_rows.append((feature_name, score, score - road_score, sim_score - score))
    feature_rows.sort(key=lambda row: abs(row[2]), reverse=True)

    return road_score, sim_score, total_diff, group_rows, feature_rows


def print_rows(title, rows, limit):
    print(f"\n{title}:")
    print(f"{'name':28s} {'mixed_score':>12} {'delta_from_road':>18} {'remain_to_sim':>16}")
    for name, score, delta, remain in rows[:limit]:
        print(f"{name:28s} {score:12.6f} {delta:+18.6f} {remain:+16.6f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--road", default="road_features.npz")
    parser.add_argument("--sim", default="sim_features.npz")
    parser.add_argument(
        "--models",
        nargs="+",
        required=True,
    )
    parser.add_argument("--group-limit", type=int, default=10)
    parser.add_argument("--feature-limit", type=int, default=15)
    args = parser.parse_args()

    compare_module = load_compare_module()
    road = load_npz_as_dict(args.road)
    sim = load_npz_as_dict(args.sim)
    session_cache = build_session_cache(args.models, compare_module)

    for model_path in args.models:
        print(f"\nMODEL {model_path}")
        outputs = run_inference(model_path, road, session_cache).keys()
        for output_name in outputs:
            road_score, sim_score, total_diff, group_rows, feature_rows = analyze_output(
                model_path,
                road,
                sim,
                DEFAULT_GROUPS,
                SUBFEATURES,
                output_name,
                session_cache,
            )
            print(f"\nOutput: {output_name}")
            print(f"  road score : {road_score:.6f}")
            print(f"  sim  score : {sim_score:.6f}")
            print(f"  total diff : {total_diff:+.6f}")
            print_rows("Top group sensitivities", group_rows, args.group_limit)
            print_rows("Top single-feature sensitivities", feature_rows, args.feature_limit)


if __name__ == "__main__":
    main()
