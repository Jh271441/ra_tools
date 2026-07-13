import argparse
import numpy as np


def load_lane_features(npz_path):
    data = np.load(npz_path)
    return {
        "geometric": data["nearby_lane_geometric"][0, :, 0, :, :].astype(np.float64),
        "continuous": data["nearby_lane_continuous"][0, :, 0, :].astype(np.float64),
        "discrete": data["nearby_lane_discrete"][0, :, 0, :].astype(np.int64),
        "valid_geometric": data["nearby_lane_valid_geometric"][0, :, 0].astype(np.int64),
        "valid_history": data["nearby_lane_valid_history"][0].astype(np.int64),
    }


def lane_valid_count(features, idx):
    valid = int(features["valid_geometric"][idx])
    max_points = features["geometric"].shape[1]
    return max(0, min(valid, max_points))


def lane_points(features, idx):
    valid = lane_valid_count(features, idx)
    return features["geometric"][idx, :valid]


def resample_polyline(points, target_count=8):
    if len(points) == 0:
        return np.zeros((target_count, 2), dtype=np.float64)
    if len(points) == 1:
        return np.repeat(points, target_count, axis=0)

    deltas = np.diff(points, axis=0)
    seg_lens = np.linalg.norm(deltas, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = cum[-1]
    if total <= 1e-9:
        return np.repeat(points[:1], target_count, axis=0)

    targets = np.linspace(0.0, total, target_count)
    out = np.empty((target_count, 2), dtype=np.float64)
    seg_idx = 0
    for i, t in enumerate(targets):
        while seg_idx + 1 < len(cum) and cum[seg_idx + 1] < t:
            seg_idx += 1
        if seg_idx + 1 >= len(cum):
            out[i] = points[-1]
            continue
        start = points[seg_idx]
        end = points[seg_idx + 1]
        span = cum[seg_idx + 1] - cum[seg_idx]
        alpha = 0.0 if span <= 1e-9 else (t - cum[seg_idx]) / span
        out[i] = start + alpha * (end - start)
    return out


def lane_signature(features, idx):
    pts = lane_points(features, idx)
    valid = lane_valid_count(features, idx)
    history = int(features["valid_history"][idx])
    discrete = features["discrete"][idx]
    continuous = features["continuous"][idx]
    sampled = resample_polyline(pts, target_count=8)
    centroid = pts.mean(axis=0) if len(pts) else np.zeros(2, dtype=np.float64)
    start = pts[0] if len(pts) else np.zeros(2, dtype=np.float64)
    end = pts[-1] if len(pts) else np.zeros(2, dtype=np.float64)
    return {
        "valid": valid,
        "history": history,
        "discrete": discrete,
        "continuous": continuous,
        "sampled": sampled,
        "centroid": centroid,
        "start": start,
        "end": end,
    }


def lane_cost(sig_a, sig_b):
    sampled_cost = np.mean(np.linalg.norm(sig_a["sampled"] - sig_b["sampled"], axis=1))
    reverse_cost = np.mean(np.linalg.norm(sig_a["sampled"] - sig_b["sampled"][::-1], axis=1))
    geom_cost = min(sampled_cost, reverse_cost)
    centroid_cost = np.linalg.norm(sig_a["centroid"] - sig_b["centroid"])
    endpoint_cost = min(
        np.linalg.norm(sig_a["start"] - sig_b["start"]) + np.linalg.norm(sig_a["end"] - sig_b["end"]),
        np.linalg.norm(sig_a["start"] - sig_b["end"]) + np.linalg.norm(sig_a["end"] - sig_b["start"]),
    )
    valid_cost = abs(sig_a["valid"] - sig_b["valid"]) * 0.6
    history_cost = abs(sig_a["history"] - sig_b["history"]) * 0.3
    discrete_cost = np.count_nonzero(sig_a["discrete"] != sig_b["discrete"]) * 1.5
    continuous_cost = np.linalg.norm(sig_a["continuous"] - sig_b["continuous"]) * 2.0
    return geom_cost + 0.3 * centroid_cost + 0.15 * endpoint_cost + valid_cost + history_cost + discrete_cost + continuous_cost


def build_cost_matrix(road, sim):
    road_sigs = [lane_signature(road, i) for i in range(road["geometric"].shape[0])]
    sim_sigs = [lane_signature(sim, i) for i in range(sim["geometric"].shape[0])]
    cost = np.zeros((len(road_sigs), len(sim_sigs)), dtype=np.float64)
    for i, sig_a in enumerate(road_sigs):
        for j, sig_b in enumerate(sim_sigs):
            cost[i, j] = lane_cost(sig_a, sig_b)
    return cost, road_sigs, sim_sigs


def greedy_match(cost_matrix):
    pairs = [(float(cost_matrix[i, j]), i, j) for i in range(cost_matrix.shape[0]) for j in range(cost_matrix.shape[1])]
    pairs.sort(key=lambda x: x[0])
    used_i = set()
    used_j = set()
    match = {}
    for cost, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        match[i] = (j, cost)
        used_i.add(i)
        used_j.add(j)
    return match


def describe_identity_vs_best(cost_matrix, limit=20):
    rows = []
    for i in range(min(cost_matrix.shape[0], cost_matrix.shape[1])):
        identity = float(cost_matrix[i, i])
        best_j = int(np.argmin(cost_matrix[i]))
        best_cost = float(cost_matrix[i, best_j])
        rows.append((identity - best_cost, i, identity, best_j, best_cost))
    rows.sort(reverse=True)
    print("\nMost suspicious slot mismatches:")
    print(f"{'road_idx':>8} {'identity_cost':>14} {'best_sim_idx':>12} {'best_cost':>12} {'improvement':>12}")
    for improvement, i, identity, best_j, best_cost in rows[:limit]:
        print(f"{i:8d} {identity:14.4f} {best_j:12d} {best_cost:12.4f} {improvement:12.4f}")


def summarize_matches(cost_matrix, match, road, sim, limit=20):
    identity_mean = float(np.mean(np.diag(cost_matrix)))
    matched_costs = np.array([c for _, c in match.values()], dtype=np.float64)
    matched_mean = float(np.mean(matched_costs))
    remapped = [(i, j, c) for i, (j, c) in match.items() if i != j]
    remapped.sort(key=lambda x: x[2])

    print("\nGlobal summary:")
    print(f"identity mean cost : {identity_mean:.4f}")
    print(f"best-match mean cost: {matched_mean:.4f}")
    print(f"remapped lanes      : {len(remapped)}/{len(match)}")
    print(f"max matched cost    : {matched_costs.max():.4f}")
    print(f"nonzero matched cost: {int(np.count_nonzero(matched_costs > 1e-9))}/{len(matched_costs)}")

    if np.count_nonzero(matched_costs > 1e-9) == 0:
        print("exact match verdict : all lanes match exactly after reordering")
    else:
        print("exact match verdict : some lanes still differ after reordering")

    print("\nBest remapped pairs:")
    print(f"{'road_idx':>8} {'sim_idx':>8} {'cost':>10} {'road_valid':>12} {'sim_valid':>10} {'road_hist':>10} {'sim_hist':>9}")
    for i, j, c in remapped[:limit]:
        print(
            f"{i:8d} {j:8d} {c:10.4f} "
            f"{lane_valid_count(road, i):12d} {lane_valid_count(sim, j):10d} "
            f"{int(road['valid_history'][i]):10d} {int(sim['valid_history'][j]):9d}"
        )


def print_pair_details(road, sim, match, indices):
    print("\nDetailed lane pairs:")
    for road_idx in indices:
        sim_idx, cost = match[road_idx]
        road_pts = lane_points(road, road_idx)
        sim_pts = lane_points(sim, sim_idx)
        print(
            f"road[{road_idx}] -> sim[{sim_idx}] cost={cost:.4f} "
            f"road_valid={len(road_pts)} sim_valid={len(sim_pts)}"
        )
        print(f"  road discrete: {road['discrete'][road_idx].tolist()}")
        print(f"  sim  discrete: {sim['discrete'][sim_idx].tolist()}")
        print(f"  road cont    : {np.round(road['continuous'][road_idx], 4).tolist()}")
        print(f"  sim  cont    : {np.round(sim['continuous'][sim_idx], 4).tolist()}")
        print(f"  road first3  : {np.round(road_pts[:3], 4).tolist()}")
        print(f"  sim  first3  : {np.round(sim_pts[:3], 4).tolist()}")


def print_mapping_table(match):
    print("\nFull mapping table:")
    print(f"{'road_idx':>8} {'sim_idx':>8} {'cost':>10}")
    for road_idx in sorted(match):
        sim_idx, cost = match[road_idx]
        print(f"{road_idx:8d} {sim_idx:8d} {cost:10.4f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--road", default="road_features.npz")
    parser.add_argument("--sim", default="sim_features.npz")
    parser.add_argument("--detail-count", type=int, default=8)
    parser.add_argument("--show-mapping", action="store_true")
    args = parser.parse_args()

    road = load_lane_features(args.road)
    sim = load_lane_features(args.sim)
    cost_matrix, _, _ = build_cost_matrix(road, sim)
    match = greedy_match(cost_matrix)

    describe_identity_vs_best(cost_matrix, limit=20)
    summarize_matches(cost_matrix, match, road, sim, limit=20)

    detail_indices = [i for i, (j, _) in sorted(match.items(), key=lambda kv: kv[1][1]) if i != j][:args.detail_count]
    if detail_indices:
        print_pair_details(road, sim, match, detail_indices)
    if args.show_mapping:
        print_mapping_table(match)


if __name__ == "__main__":
    main()
