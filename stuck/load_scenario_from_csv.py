import logging
import json
import os

import pandas as pd

from collections import defaultdict

# =====================
# 配置
# =====================
NPZ_DIR = (
    "/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/"
    "2025Q4_simplan_tensor_dict-val_label/not_triggered/20260104/"
)

def load_trip_segments_from_full_table_csv(
    csv_path: str,
    apply_warmup: bool = False,
):
    """
    Load trip segments from full scenario table csv
    (saved directly from scenario_query_result.to_csv).

    Returns:
        List of (trip_id, start_ts_ns, end_ts_ns)
    """
    df = pd.read_csv(csv_path)

    if "scenario" not in df.columns:
        raise ValueError("CSV does not contain 'scenario' column")

    trip_segments = []

    for idx, row in df.iterrows():
        try:
            scenario = json.loads(row["scenario"])
            scenario_id = row["id"]

            trip = scenario["tripSegment"]

            trip_id = trip["tripId"]

            start_ms = int(trip["startTimestamp"])
            end_ms = int(trip["endTimestamp"])

            warmup_ms = int(scenario.get("warmupMs", 0)) if apply_warmup else 0

            # ms → ns
            start_ts_ns = (start_ms + warmup_ms) * 1000000
            end_ts_ns = end_ms * 1000000

            if start_ts_ns >= end_ts_ns:
                continue

            trip_segments.append(
                (scenario_id, trip_id, start_ts_ns, end_ts_ns)
            )

        except Exception as e:
            logging.warning(
                f"Skip row {idx} due to parse error: {e}"
            )

    return trip_segments


# 统计时间差
# === correct trigger ===
# 2304
# count = 2304
# min = 20.00s
# max = 40.00s
# mean = 26.95s
# === not triggered ===
# count (segments) = 2552
# unique trip_id   = 2400
# min  = 20.00s
# max  = 40.00s
# mean = 29.34s
def count_input(trip_segments):
    lengths_ns = [
        end - start for _, _, start, end in trip_segments
    ]

    lengths_s = [l / 1e9 for l in lengths_ns]

    trip_ids = [trip_id for _, trip_id, _, _ in trip_segments]

    print(f"count (segments) = {len(lengths_s)}")
    print(f"unique trip_id   = {len(set(trip_ids))}")
    print(f"min  = {min(lengths_s):.2f}s")
    print(f"max  = {max(lengths_s):.2f}s")
    print(f"mean = {sum(lengths_s)/len(lengths_s):.2f}s")


# 统计输出结果的unique id和时间差
# ====== Basic Stats ====== (not triggered)
# Total npz files      : 1418
# Unique trip_id       : 1365
def count_result():
    OUT_CSV = "merged_scenes_stats_ns.csv"

    # =====================
    # 1. 解析文件名（ns）
    # =====================
    rows = []

    for fname in os.listdir(NPZ_DIR):
        if not fname.endswith(".npz"):
            continue

        try:
            # trip_id.start_ns.end_ns.npz
            trip_id, start_ns, end_ns = fname[:-4].split(".")
            start_ns = int(start_ns)
            end_ns = int(end_ns)

            rows.append({
                "trip_id": trip_id,
                "start_ns": start_ns,
                "end_ns": end_ns,
                "duration_ns": end_ns - start_ns,
                "file": fname,
            })
        except Exception:
            continue

    df = pd.DataFrame(rows)

    if df.empty:
        raise RuntimeError("No valid npz files found")

    # =====================
    # 2. 基础统计（ns）
    # =====================
    print("====== Basic Stats ======")
    print(f"Total npz files      : {len(df)}")
    print(f"Unique trip_id       : {df['trip_id'].nunique()}")

    print(
        "Duration (ns) summary:\n",
        df["duration_ns"].describe(),
    )

    print(
        "\nDuration (s) summary:\n",
        (df["duration_ns"] / 1e9).describe(),
    )

    # =====================
    # 3. 排序
    # =====================
    df = df.sort_values(["trip_id", "start_ns"]).reset_index(drop=True)

    # =====================
    # 4. 判断是否新场景
    # =====================
    df["prev_trip"] = df["trip_id"].shift(1)
    df["prev_end"] = df["end_ns"].shift(1)

    df["new_scene"] = (
            (df["trip_id"] != df["prev_trip"]) |
            (df["start_ns"] != df["prev_end"])
    )

    # =====================
    # 5. scene_id
    # =====================
    df["scene_id"] = df["new_scene"].cumsum()

    # =====================
    # 6. 拼接后的真实场景
    # =====================
    scene_df = (
        df.groupby("scene_id")
        .agg(
            trip_id=("trip_id", "first"),
            start_ns=("start_ns", "min"),
            end_ns=("end_ns", "max"),
            segment_cnt=("scene_id", "size"),
        )
        .reset_index()
    )

    scene_df["duration_ns"] = scene_df["end_ns"] - scene_df["start_ns"]
    scene_df["duration_s"] = scene_df["duration_ns"] / 1e9

    # =====================
    # 7. 统计结果
    # =====================
    print("\n====== Merged Scene Stats ======")
    print(f"Merged scenes count  : {len(scene_df)}")

    print("\nScene duration (s):")
    print(scene_df["duration_s"].describe())

    print("\nSegments per scene:")
    print(scene_df["segment_cnt"].value_counts().sort_index())


def merge_continuous_segments(segments):
    """
    segments: list of (start_ns, end_ns) sorted by start_ns
    返回 list of merged segments, 连续（end==start）会合并
    """
    if not segments:
        return []

    segments = sorted(segments, key=lambda x: x[0])
    merged = [segments[0]]

    for start, end in segments[1:]:
        last_start, last_end = merged[-1]
        # 如果首尾相接，合并
        if last_end == start:
            merged[-1] = (last_start, end)
            print(f"merge {last_start} {last_end} {start} {end}")
        else:
            merged.append((start, end))
    return merged


def trip_segments_to_dict(trip_segments):
    trip_dict = defaultdict(list)
    for _, trip_id, start_ns, end_ns in trip_segments:
        trip_dict[trip_id].append((start_ns, end_ns))

    # 合并连续
    for trip_id in trip_dict:
        trip_dict[trip_id] = merge_continuous_segments(trip_dict[trip_id])

    return dict(trip_dict)


def ofs_files_to_dict(ofs_dir):
    trip_dict = defaultdict(list)
    for f in os.listdir(ofs_dir):
        if not f.endswith(".npz"):
            continue
        try:
            name, start_ns, end_ns, _ = f.split(".")
            start_ns = int(start_ns)
            end_ns = int(end_ns)
            trip_dict[name].append((start_ns, end_ns))
        except Exception as e:
            print(f"skip {f}: {e}")

    # 合并连续
    for trip_id in trip_dict:
        trip_dict[trip_id] = merge_continuous_segments(trip_dict[trip_id])

    return dict(trip_dict)


def duration_stats_from_segments(segments, unit="s"):
    """
    segments: list of (trip_id, start_ns, end_ns)
    unit: "ns" or "s"
    返回 DataFrame: duration, count
    """
    rows = []
    for _, trip_id, start_ns, end_ns in segments:
        dur_ns = end_ns - start_ns
        if dur_ns <= 0:
            continue
        rows.append(dur_ns)

    df = pd.DataFrame({"duration_ns": rows})

    if unit == "s":
        df["duration"] = (df["duration_ns"] / 1e9).round(2)
    else:
        df["duration"] = df["duration_ns"]

    stat = (
        df["duration"]
        .value_counts()
        .sort_index()
        .reset_index()
        .rename(columns={"index": "duration", "duration": "segment_cnt"})
    )

    return stat


def compare_input_output(trip_segments, ofs_dir):
    input_dict = trip_segments_to_dict(trip_segments)
    input_merged_segments = []
    for trip_id, segs in input_dict.items():
        for start_ns, end_ns in segs:
            input_merged_segments.append((trip_id, start_ns, end_ns))
    input_duration_stat = duration_stats_from_segments(
        input_merged_segments, unit="s"
    )
    print("====== Input Duration Stats ======")
    print(input_duration_stat)

    output_dict = ofs_files_to_dict(ofs_dir)

    output_merged_segments = []
    for trip_id, segs in output_dict.items():
        for start_ns, end_ns in segs:
            output_merged_segments.append((trip_id, start_ns, end_ns))

    output_duration_stat = duration_stats_from_segments(
        output_merged_segments, unit="s"
    )

    print("====== Output Duration Stats ======")
    print(output_duration_stat)

    # 统计input和output的overlap
    count = 0
    equal_count = 0
    for trip_id in input_dict:
        # if count >= 100:
        #     break
        in_start = input_dict[trip_id][0][0]
        in_end = input_dict[trip_id][-1][1]
        out_start = output_dict.get(trip_id, [(None, None)])[0][0]
        out_end = output_dict.get(trip_id, [(None, None)])[0][1]
        if out_start and out_end:
            # print(f"{trip_id}: input [{in_start}, {in_end}], output [{out_start}, {out_end}]")
            if in_start == out_start and in_end == out_end:
                equal_count += 1
            count += 1
    print(f"count = {count}")
    print(f"equal_count = {equal_count}")


def save_trip_segments(trip_segments, output_path):
    # 转成 DataFrame
    df = pd.DataFrame(trip_segments, columns=["scenario_id", "trip_id", "start_ns", "end_ns"])

    # 保存为 CSV
    df.to_csv(output_path, index=False)

    print(f"Saved {len(df)} segments to {output_path}")


def test_segments_map(trip_segments):
    # 1. Create a pure list of (trip_id, start, end) for the processor
    trip_segments_pure = [(t, s, e) for _, t, s, e in trip_segments]
    # 2. Create a lookup map for scenario_id
    segment_map = {(t, s, e): sc_id for sc_id, t, s, e in trip_segments}
    for trip_segment in trip_segments_pure:
        sc_id = segment_map.get(trip_segment)
        print(f"trip_segment: {trip_segment}, sc_id: {sc_id}")

if __name__ == "__main__":
    full_csv_path = os.path.join(os.path.dirname(__file__), "data/sim_plan_scenario_normal_stop_20260201.csv")
    output_path = os.path.join(os.path.dirname(__file__), "data/sim_plan_scenario_normal_stop_20260201_scenario_trip_segments.csv")
    trip_segments = load_trip_segments_from_full_table_csv(
        csv_path=full_csv_path,
    )
    # 去重之后 2552->2488
    print(len(set(trip_segments)))
    test_segments_map(trip_segments)
    save_trip_segments(trip_segments, output_path)
    count_input(trip_segments)
    # count_result()
    # compare_input_output(trip_segments, NPZ_DIR)
