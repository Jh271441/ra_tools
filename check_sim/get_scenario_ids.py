#!/usr/bin/env python3
"""
从 Trail 仿真结果（Orion job）中查询 scenario_id 列表。

用法：
  python3 check_sim/get_scenario_ids.py --job 40390125
  python3 check_sim/get_scenario_ids.py --filter "Base.dpe_assist_channel_triggered.value < 1" --job 40390125
  python3 check_sim/get_scenario_ids.py --job 40390125 --job-feature 40390703
  python3 check_sim/get_scenario_ids.py --job 40390125 --metrics dpe_assist_channel_triggered dpe_stuck_detect
  python3 check_sim/get_scenario_ids.py --job 40390125 --size 500 --out ids.txt
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ra_api.sim_result_api import SimResultClient


def main():
    parser = argparse.ArgumentParser(description="从 Trail Orion job 查询 scenario_id 列表")
    parser.add_argument("--job",         required=True, type=int, help="Base job_id（必填）")
    parser.add_argument("--job-feature", type=int,      help="Feature job_id（用于 Base vs Feature 对比）")
    parser.add_argument("--filter",      default=None,  help=(
        "过滤表达式，从 Trail 页面 filterQuery 复制，例如：\n"
        "  \"Base.dpe_assist_channel_triggered.value < 1\""
    ))
    parser.add_argument("--metrics", nargs="*",
                        default=["dpe_assist_channel_triggered"],
                        help="查询的指标（默认 dpe_assist_channel_triggered）")
    parser.add_argument("--size",    type=int, default=500, help="最多返回条数（默认 500）")
    parser.add_argument("--all-pages", action="store_true", help="自动翻页拉取全部结果")
    parser.add_argument("--out",     default=None, help="将 scenario_id 列表写入文件（每行一个）")
    parser.add_argument("--show-df", action="store_true", help="同时打印完整 DataFrame")
    args = parser.parse_args()

    client = SimResultClient()

    if args.all_pages:
        df = client.query_all_pages(
            job_id_base=args.job,
            job_id_feature=args.job_feature,
            metrics=args.metrics,
            filter_expr=args.filter,
        )
    else:
        df = client.query_report(
            job_id_base=args.job,
            job_id_feature=args.job_feature,
            metrics=args.metrics,
            filter_expr=args.filter,
            size=args.size,
        )

    if df.empty:
        print("未查询到任何结果")
        return

    ids = df["scenario_id"].dropna().astype(int).tolist()

    print(f"共 {len(ids)} 个 scenario_id（job={args.job}" +
          (f", feature={args.job_feature}" if args.job_feature else "") +
          (f", filter='{args.filter}'" if args.filter else "") + ")：")
    for sid in ids:
        print(sid)

    if args.show_df:
        print()
        print(df.to_string(index=False))

    if args.out:
        with open(args.out, "w") as f:
            f.write("\n".join(str(i) for i in ids) + "\n")
        print(f"\n已写入 {args.out}")


if __name__ == "__main__":
    main()
