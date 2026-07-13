import argparse

if __package__:
    from .features import FEATURE_GROUPS, SUBFEATURES
    from .model_io import create_session, run_inference
    from .tensor_io import load_npz
else:
    from features import FEATURE_GROUPS, SUBFEATURES
    from model_io import create_session, run_inference
    from tensor_io import load_npz


def replace_features(base, override, names):
    mixed = dict(base)
    for name in names:
        mixed[name] = override[name]
    return mixed


def run_feature_variants(session, road, sim, groups, feature_names):
    road_out = run_inference(session, road)
    sim_out = run_inference(session, sim)
    group_outputs = {
        group_name: run_inference(session, replace_features(road, sim, names))
        for group_name, names in groups.items()
    }
    feature_outputs = {
        feature_name: run_inference(
            session, replace_features(road, sim, [feature_name])
        )
        for feature_name in feature_names
    }
    return road_out, sim_out, group_outputs, feature_outputs


def analyze_output(
    output_name, road_out, sim_out, group_outputs, feature_outputs
):
    road_score = float(road_out[output_name].reshape(-1)[0])
    sim_score = float(sim_out[output_name].reshape(-1)[0])
    total_diff = sim_score - road_score

    group_rows = []
    for group_name, outputs in group_outputs.items():
        score = float(outputs[output_name].reshape(-1)[0])
        group_rows.append((group_name, score, score - road_score, sim_score - score))
    group_rows.sort(key=lambda row: abs(row[2]), reverse=True)

    feature_rows = []
    for feature_name, outputs in feature_outputs.items():
        score = float(outputs[output_name].reshape(-1)[0])
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
    parser.add_argument("--intra-op-threads", type=int, default=4)
    args = parser.parse_args()

    road = load_npz(args.road)
    sim = load_npz(args.sim)
    for model_path in args.models:
        session = create_session(model_path, args.intra_op_threads)
        print(f"\nMODEL {model_path}")
        road_out, sim_out, group_outputs, feature_outputs = run_feature_variants(
            session,
            road,
            sim,
            FEATURE_GROUPS,
            SUBFEATURES,
        )
        for output_name in road_out:
            road_score, sim_score, total_diff, group_rows, feature_rows = analyze_output(
                output_name,
                road_out,
                sim_out,
                group_outputs,
                feature_outputs,
            )
            print(f"\nOutput: {output_name}")
            print(f"  road score : {road_score:.6f}")
            print(f"  sim  score : {sim_score:.6f}")
            print(f"  total diff : {total_diff:+.6f}")
            print_rows("Top group sensitivities", group_rows, args.group_limit)
            print_rows("Top single-feature sensitivities", feature_rows, args.feature_limit)


if __name__ == "__main__":
    main()
