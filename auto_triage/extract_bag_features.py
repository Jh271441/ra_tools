#!/usr/bin/env python3
"""
extract_bag_features.py - 提取时序特征并进行三分类（正确触发/误触发/无需协助）分析。
重点区分：人工干预提速/SWAG提速 vs 自车自行脱困（无需协助）。
"""

import json
import os
import sys
import json
import os
import sys

def mean(lst):
    return sum(lst) / len(lst) if lst else 0.0

def analyze_jsonl(input_file):
    if not os.path.exists(input_file):
        print(f"Error: {input_file} does not exist.")
        return

    correct_count = 0
    misfire_count = 0
    no_assist_count = 0

    total = 0
    recovered_but_intervened = 0
    recovered_and_self_cured = 0

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue

            total += 1
            issue_id = row.get("issue_id")
            gt_label = row.get("gt_label", "") # 正确触发 / 误触发 / 无需协助

            # 1. 解析时序数据
            time_windows = row.get("time_windows", [])
            # 提取车速、档位、让行状态等
            speeds = [w.get("speed", 0.0) for w in time_windows]
            gears = [w.get("gear", "") for w in time_windows]
            yieldings = [w.get("yielding", "无") for w in time_windows]

            # T0时刻是第15个点（前15后5，共21点）
            speed_pre_avg = mean(speeds[:15]) if len(speeds) >= 15 else 0.0
            speed_post_max = max(speeds[15:]) if len(speeds) > 15 else 0.0

            # 2. 解析 RA 事件与干预指令
            ra_event_str = str(row.get("ra_event", ""))

            # 是否有有效人工干预/SWAG干预
            has_follow_path = "kFollowPath" in ra_event_str
            has_waiting_points = "kWaitingPoints" in ra_event_str
            has_swag = "swag" in ra_event_str.lower()
            has_manual_control = any(cmd in ra_event_str for cmd in ["kDirectControl", "方向键", "倒车"])

            has_intervention = has_follow_path or has_swag or has_manual_control

            # 3. 统计速度回升和自愈特征
            speed_recovered = speed_post_max > 1.0  # 后续车速恢复到 1.0 m/s 以上

            is_self_recovery = speed_recovered and (not has_intervention)

            if speed_recovered:
                if has_intervention:
                    recovered_but_intervened += 1
                else:
                    recovered_and_self_cured += 1

            # 打印与 GT 标签的比对逻辑
            if gt_label == "无需协助":
                no_assist_count += 1
            elif gt_label == "正确触发":
                correct_count += 1
            elif gt_label == "误触发":
                misfire_count += 1

    print(f"--- 样本统计 ---")
    print(f"总样本数: {total}")
    print(f"  正确触发 (GT): {correct_count}")
    print(f"  误触发 (GT): {misfire_count}")
    print(f"  无需协助 (GT): {no_assist_count}")
    print(f"--- 速度时序与干预分析 ---")
    print(f"T0后速度恢复(>1m/s)的样本数: {recovered_but_intervened + recovered_and_self_cured}")
    print(f"  其中由于干预导致速度恢复 (Intervened Recovery): {recovered_but_intervened}")
    print(f"  其中无干预自行恢复 (Self-Recovery): {recovered_and_self_cured}")

if __name__ == "__main__":
    # 可以指定评测输出目录
    input_path = "/home/didi/workspace/airflow_dags/logs/full.jsonl"
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
    analyze_jsonl(input_path)
