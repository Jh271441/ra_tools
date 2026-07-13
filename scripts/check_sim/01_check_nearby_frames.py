#!/usr/bin/env python3

import argparse

from planning_seed_reader import get_nearby_frames, get_tensor_dict


def format_tensor_dict(tensor_dict):
    if tensor_dict is None:
        return "N/A"
    try:
        size = len(tensor_dict)
        return f"Size({size})" if size else "Empty (0)"
    except TypeError:
        return "Unknown Structure"


def main():
    parser = argparse.ArgumentParser(
        description="Inspect PlanningSeed frames around a timestamp"
    )
    parser.add_argument("--road", default="road.bag")
    parser.add_argument("--sim", default="sim.bag")
    parser.add_argument(
        "--ts", type=int, required=True, help="target timestamp in milliseconds"
    )
    parser.add_argument(
        "--count", type=int, default=1, help="frames before and after the nearest frame"
    )
    args = parser.parse_args()

    road_results = get_nearby_frames(args.road, args.ts, args.count)
    sim_results = get_nearby_frames(args.sim, args.ts, args.count)
    if not road_results or not sim_results:
        raise RuntimeError("No /planning/seed frames found in one or both bags")

    print(f"正在搜索 /planning/seed 在 {args.ts} ms 及其前后帧...\n")
    print(
        f"{'帧偏移':<8} | {'Road 时间戳':<20} | {'Road TD':<15} | "
        f"{'Sim 时间戳':<20} | {'Sim TD':<15}"
    )
    print("-" * 90)

    offsets = sorted(
        {item["index_offset"] for item in road_results + sim_results}
    )
    for offset in offsets:
        road = next(
            (item for item in road_results if item["index_offset"] == offset), None
        )
        sim = next(
            (item for item in sim_results if item["index_offset"] == offset), None
        )
        road_time = f"{road['time']:.6f}" if road else "N/A"
        sim_time = f"{sim['time']:.6f}" if sim else "N/A"
        road_td = format_tensor_dict(get_tensor_dict(road["msg"])) if road else "N/A"
        sim_td = format_tensor_dict(get_tensor_dict(sim["msg"])) if sim else "N/A"
        label = "目标帧" if offset == 0 else f"{offset:+} 帧"
        print(
            f"{label:<8} | {road_time:<20} | {road_td:<15} | "
            f"{sim_time:<20} | {sim_td:<15}"
        )



if __name__ == "__main__":
    main()
