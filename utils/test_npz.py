from collections import defaultdict
import json
import os
from tqdm import tqdm
import os
import glob
import yaml

import numpy as np


def print_dict(d):
    print("-" * 100)
    for k, v in d.items():
        if k == "label":
            print(f"type of {k}: {type(v)}, shape: {v.shape}, dtype: {v.dtype}")
        if v.ndim == 0 or v.ndim == 1 and v.shape[0] <= 100:
            print(f"{k}: {v}, shape: {v.shape}, dtype: {v.dtype}")
        else:
            print(f"{k}.shape: {v.shape}, ndim: {v.ndim}, dtype: {v.dtype}")


def test_npz():
    # # x1: Original data labeled, train
    # x1 = dict(
    #     np.load(
    #         "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-labeled-nearby/"
    #         "20250928/train/17229_20250917_140426.1758089285848000000.1758089302838000000.npz",
    #         allow_pickle=True,
    #     )
    # )

    # # x2: Original data labeled, test
    # x2 = dict(
    #     np.load(
    #         "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-labeled-nearby/"
    #         "20250928/test/17229_20250918_094931.1758160161523000000.1758160205723000000.npz",
    #         allow_pickle=True,
    #     )
    # )

    # # x3: Original data neg, train
    # x3 = dict(
    #     np.load(
    #         "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-neg-nearby/"
    #         "20250928/train/10240_20250917_081627.1758069145496000000.1758069177506000000.npz",
    #         allow_pickle=True,
    #     )
    # )

    # # x4: Original data neg, test
    # x4 = dict(
    #     np.load(
    #         "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-neg-nearby/"
    #         "20250928/test/17230_20250917_135616.1758089125843000000.1758089195843000000.npz",
    #         allow_pickle=True,
    #     )
    # )

    # ------ data after 1012 --------
    # y1: New data labeled, train
    y1 = dict(
        np.load(
            "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-labeled-nearby/"
            "20251019/train/17218_20251009_131116.1759986819298000000.1759986857578000000.npz",
            allow_pickle=True,
        )
    )

    # y2: New data labeled, test
    y2 = dict(
        np.load(
            "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-labeled-nearby/"
            "20251019/test/17212_20251008_175606.1759918278643000000.1759918300143000000.npz",
            allow_pickle=True,
        )
    )

    # y3: New data neg, train
    y3 = dict(
        np.load(
            "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-neg-nearby/"
            "20251019/train/10240_20251009_100216.1759975411217000000.1759975436617000000.npz",
            allow_pickle=True,
        )
    )

    # y4: New data neg, test
    y4 = dict(
        np.load(
            "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-neg-nearby/"
            "20251019/test/17230_20251009_165251.1760000675743000000.1760000745743000000.npz",
            allow_pickle=True,
        )
    )

    # print_dict(x1)
    # print_dict(x2)
    # print_dict(x3)
    # print_dict(x4)
    print_dict(y1)
    print_dict(y2)
    print_dict(y3)
    print_dict(y4)


def count_label():
    new_data_dir_1019 = "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-neg-nearby/20251019"
    split = "train"
    file_list = os.listdir(os.path.join(new_data_dir_1019, split))
    num_files = len(file_list)
    train_label_count = 0
    train_neg_count = 0
    label_count = 0
    relabel_from_0_to_1 = 0
    relabel_from_1_to_0 = 0
    for file in tqdm(file_list):
        if file.endswith(".npz"):
            data = dict(
                np.load(
                    os.path.join(new_data_dir_1019, split, file),
                    allow_pickle=True,
                )
            )
            tqdm.write(
                f"{file}: label {data['label']}, train_label {data['train_label']}, ra info {data['ra_info']}"
            )
            if data["train_label"].item() == "1":
                train_label_count += 1
            else:
                train_neg_count += 1
            if data["label"].item() == 1:
                label_count += 1
            if data["train_label"].item() == "0" and data["label"].item() == 1:
                relabel_from_1_to_0 += 1
            if data["train_label"].item() == "1" and data["label"].item() == 0:
                relabel_from_0_to_1 += 1

    print(f"num_files: {num_files}")
    print(
        f"train_label_count: {train_label_count}, {train_label_count / num_files}"
    )
    print(f"train_neg_count: {train_neg_count}, {train_neg_count / num_files}")
    print(f"label_count: {label_count}, {label_count / num_files}")
    print(
        f"relabel_from_1_to_0: {relabel_from_1_to_0}, {relabel_from_1_to_0 / num_files}"
    )
    print(
        f"relabel_from_0_to_1: {relabel_from_0_to_1}, {relabel_from_0_to_1 / num_files}"
    )


def test_npz_2():
    # x1: Original data labeled, train
    # x1 = dict(
    #     np.load(
    #         "/home/luban/ofs/dataset/2025Q3_weekly_tensor_dict-unstuck/"
    #         "20250928/train/ra_unstuck_model.cn22812039_succ_auto_wp.npz",
    #         allow_pickle=True,
    #     )
    # )

    # x2 = dict(
    #     np.load(
    #         "/home/luban/ofs/dataset/2025Q3_weekly_tensor_dict-unstuck/"
    #         "20250928/train/ra_unstuck_model.cn22811817_succ_auto_nwp.npz",
    #         allow_pickle=True,
    #     )
    # )

    # x3 = dict(
    #     np.load(
    #         "/home/luban/ofs/user/jasperchen/2025Q2_weekly_tensor_dict-train_label-labeled_test/"
    #         "20251116/train/17128_20251105_080031.1762301446543000000.1762301501653000000.npz",
    #         allow_pickle=True,
    #     )
    # )

    x4 = dict(
        np.load(
            "/home/luban/ofs/user/jasperchen/2025Q4_simplan_tensor_dict-val_label_3/normal_stop_20260201/"
            "22538655.10365_20260125_070926.1769296258970000000.1769296276970000000.npz",
            allow_pickle=True,
        )
    )

    # y4: New data neg, test
    y4 = dict(
        np.load(
            "/home/luban/ofs/user/jasperchen/2025Q4_simplan_tensor_dict-val_nearby/not_triggered/"
            "17121_20250901_130714.1756703888903000000.1756703913903000000.npz",
            allow_pickle=True,
        )
    )
    print_dict(y4)
    print_dict(x4)


def dump_events_to_json(unstuck_dir, json_path):
    all_npz_files = []
    for root, _, files in os.walk(unstuck_dir):
        for f in files:
            if f.endswith(".npz"):
                all_npz_files.append(os.path.join(root, f))

    event_dict = {}

    for file_path in tqdm(all_npz_files, desc="Extracting ra_event"):
        try:
            npz = np.load(file_path, allow_pickle=True)
        except:
            continue

        # 不包含 ra_event 或 trip_id/start_time/end_time 就跳过
        if (
            "ra_event" not in npz
            or "trip_id" not in npz
            or "start_time" not in npz
            or "end_time" not in npz
        ):
            continue

        # trip_id: 可能是 ndarray(object)，需要转成纯 python 字符串
        trip_id = npz["trip_id"]
        try:
            trip_id = (
                trip_id.tolist() if hasattr(trip_id, "tolist") else str(trip_id)
            )
        except:
            trip_id = str(trip_id)

        # start_time / end_time — 确保是 python int
        try:
            start_time = int(npz["start_time"])
            end_time = int(npz["end_time"])
        except:
            start_time = int(npz["start_time"].item())
            end_time = int(npz["end_time"].item())

        # 用训练数据集会用到的 key 格式
        key = f"{trip_id}.{start_time}.{end_time}"

        # 把 ra_event 转成 json-safe 类型（ndarray → python list）
        raw = npz["ra_event"]
        events = raw.tolist() if hasattr(raw, "tolist") else raw

        event_dict[key] = events

    # 保存 JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(event_dict, f, ensure_ascii=False)


def dump_events_to_json_group_by_trip(unstuck_dir, json_path):
    """
    构建方案 A 的 JSON：
    {
        "trip_id_1": [
            {
                "start_ns": ...,
                "end_ns": ...,
                "event_start_ns": ...,
                "events": [...]
            },
            ...
        ],
        "trip_id_2": [...],
        ...
    }
    """

    all_npz_files = []
    for root, _, files in os.walk(unstuck_dir):
        for f in files:
            if f.endswith(".npz"):
                all_npz_files.append(os.path.join(root, f))

    print(f"Found {len(all_npz_files)} supplemental npz files")

    event_dict = {}

    for file_path in tqdm(all_npz_files, desc="Extracting supplemental events"):
        try:
            npz = dict(np.load(file_path, allow_pickle=True))
        except Exception:
            continue

        # 必须含有以下字段，否则跳过
        required_keys = ["trip_id", "start_time", "end_time", "ra_event"]
        if any(k not in npz for k in required_keys):
            continue

        start_ns = int(npz["start_time"])
        end_ns = int(npz["end_time"])
        trip_id = str(npz["trip_id"])
        ra_events = npz["ra_event"]

        # 提取 ra_event 起始时间戳(ms)
        event_start_ms = None
        for ev in ra_events:
            if isinstance(ev, dict) and ev.get("event") == "start":
                event_start_ms = int(ev["timestamp"])
                break

        if event_start_ms is None:
            # 如果没找到 start 事件，则跳过这个文件
            continue

        if event_start_ms is None:
            continue

        event_start_ns = event_start_ms * 1_000_000

        # 按 trip_id 分组追加
        event_dict.setdefault(trip_id, []).append(
            {
                "start_ns": start_ns,
                "end_ns": end_ns,
                "event_start_ns": event_start_ns,
                "events": ra_events,
            }
        )

    # 写入 JSON
    with open(json_path, "w") as f:
        json.dump(event_dict, f, ensure_ascii=False)

    print(f"Saved event dict to {json_path}")
    return event_dict


def load_events_from_json(json_path):
    if not os.path.exists(json_path):
        # 若没有 json，自动生成一次
        dump_events_to_json(
            "/home/luban/ofs/dataset/2025Q3_weekly_tensor_dict-unstuck/",
            json_path,
        )

    with open(json_path, "r", encoding="utf-8") as f:
        event_dict = json.load(f)
    return event_dict


def check_npz(
    event_dict,
    train_dir="/nfs/dataset-ofs-remote-assist-stuck/dataset/2025Q2_weekly_tensor_dict-train_label-labeled-nearby",
):
    """
    检查训练数据集中的 npz 文件名是否能在 event_dict 中找到对应 key。

    Args:
        event_dict_path: 你的 event_dict.json 路径
        train_dir:       训练数据根目录
    """
    # 2. 遍历所有训练 npz 文件
    train_npz_files = []
    for root, _, files in os.walk(train_dir):
        for f in files:
            if f.endswith(".npz"):
                train_npz_files.append(os.path.join(root, f))

    print(f"共找到训练 npz 文件: {len(train_npz_files)} 个")
    print("开始检查文件名是否出现在 event_dict 中...")

    hit = 0
    miss = 0
    miss_list = []

    # 3. 一一检查
    for fp in tqdm(train_npz_files):
        key = os.path.basename(fp).replace(".npz", "")
        if key in event_dict:
            hit += 1
        else:
            miss += 1
            miss_list.append(key)

    # 4. 打印结果
    print("\n==================== CHECK RESULT ====================")
    print(f"训练集总数       : {len(train_npz_files)}")
    print(f"能匹配 event_dict : {hit}")
    print(f"未匹配 event_dict : {miss}")
    print("=======================================================\n")

    if miss_list:
        print("前 20 个未命中的 key:")
        for k in miss_list[:20]:
            print("  ", k)
    else:
        print("🎉 所有训练 npz 名都成功匹配到 event_dict！")


def check_trip_id_unique(event_dict):
    trip_ids = {}
    duplicates = []

    for key in event_dict.keys():
        # key 格式为：trip_id.start_time.end_time
        parts = key.split(".")
        trip_id = parts[0]

        if trip_id in trip_ids:
            duplicates.append((trip_id, key, trip_ids[trip_id]))
        else:
            trip_ids[trip_id] = key

    print("======================================")
    print(f"总 key 数量: {len(event_dict)}")
    print(f"唯一 trip_id 数量: {len(trip_ids)}")
    print(f"重复 trip_id 数量: {len(duplicates)}")
    print("======================================\n")

    if duplicates:
        print("前 20 个重复项：")
        for t, k1, k2 in duplicates[:20]:
            print(f" trip_id={t}")
            print(f"    key1={k1}")
            print(f"    key2={k2}")
            print()
    else:
        print("🎉 所有 trip_id 都是唯一的！")


def has_yield_label(ra_info):
    """
    根据你的业务逻辑修改判断规则。
    这里假设 ra_info 中:
      ra_info['yield'] == 1 表示有让行标签。
    """
    if isinstance(ra_info, dict):
        return ra_info.get("让行", 0) == 1
    elif hasattr(ra_info, "item"):
        # np.object_ 或嵌套结构
        ra_info = ra_info.item()
        return isinstance(ra_info, str) and "让行" in ra_info
    return False


def scan_npz(root_dir):
    total = 0
    with_yield = 0
    files_with_yield = []

    for root, _, files in os.walk(root_dir):
        for f in files:
            if f.endswith(".npz"):
                total += 1
                path = os.path.join(root, f)

                try:
                    data = np.load(path, allow_pickle=True)
                    if "ra_info" in data:
                        if has_yield_label(data["ra_info"]):
                            with_yield += 1
                            files_with_yield.append(path)
                except Exception as e:
                    print(f"[ERROR] Failed to read {path}: {e}")

    print("=" * 50)
    print(f"扫描目录: {root_dir}")
    print(f"总 npz 数量: {total}")
    print(f"含让行标签数量: {with_yield}")
    print(f"不含让行标签数量: {total - with_yield}")
    print("=" * 50)

    if with_yield > 0:
        print("\n含让行标签的文件：")
        for p in files_with_yield:
            print(p)


def count_npz_files(path):
    """统计一个目录下的 .npz 文件（不递归）"""
    npz_pattern = os.path.join(path, "*.npz")
    files = glob.glob(npz_pattern)
    print(f"[COUNT] {path} → {len(files)} files")
    return len(files)


def process_dataset_config(config):
    results = {
        "train": {"labeled": 0, "neg": 0},
        "val": {"labeled": 0, "neg": 0},
        "test": {"labeled": 0, "neg": 0},
    }

    # 统计每一种 split
    for split in ["train", "val", "test"]:
        print(f"\n========== Processing split: {split} ==========\n")

        for item in config["dataset"][split]:
            name = item["name"]
            paths = item["paths"]
            is_neg = "negative_sample_ratio" in item

            print(f"[ITEM] {name} (neg={is_neg})")

            total_files = 0
            for p in paths:
                print(f"  -> Counting path: {p}")
                n = count_npz_files(p)
                total_files += n

            if is_neg:
                results[split]["neg"] += total_files
            else:
                results[split]["labeled"] += total_files

            print(f"  [DONE] {name}: +{total_files} files\n")

    return results


def compute_ratios(results, neg_ratio):
    """按 neg_ratio 计算实际使用的负样本 + 正负均衡比例"""
    final_stats = {}

    for split in ["train", "val", "test"]:
        labeled = results[split]["labeled"]
        neg_total = results[split]["neg"]

        neg_used = int(neg_total * neg_ratio)

        ratio = labeled / neg_used if neg_used > 0 else 0

        final_stats[split] = {
            "labeled_total": labeled,
            "neg_total": neg_total,
            "neg_used": neg_used,
            "final_ratio (neg_used / labeled)": ratio,
        }

    return final_stats


def get_pos_neg_ratio(yaml_path):
    print(f"Loading config: {yaml_path}")

    neg_sample_ratio = 0.1

    with open(yaml_path, "r") as f:
        config = yaml.safe_load(f)

    results = process_dataset_config(config)
    final_stats = compute_ratios(results, neg_sample_ratio)

    print("\n================= Raw Count =================\n")
    for split in results:
        print(f"{split}: {results[split]}")

    print("\n================= Final Usage =================\n")
    for split, stat in final_stats.items():
        print(f"{split}: {stat}")

    return final_stats


def summarize_all(results):
    """综合所有 splits 的 labeled/neg 总数"""
    total_labeled = sum(results[s]["labeled_total"] for s in results)
    total_neg = sum(results[s]["neg_used"] for s in results)

    print("\n================= Summary Across All Splits =================\n")
    print(f"Total Labeled : {total_labeled}")
    print(f"Total Negative: {total_neg}")
    print(
        f"Overall Ratio (neg/labeled) = {total_labeled / total_neg if total_labeled > 0 else 0:.4f}"
    )

    return total_labeled, total_neg


def parse_filename(filename):
    """解析文件名，提取trip ID和起止时间"""
    # 文件名格式: 17123_20250917_072506.1758065469153000000.1758065486553000000.npz
    parts = filename.split(".")
    if len(parts) < 3:
        print(f"Invalid filename format: {filename}")
        return None

    trip_part = parts[0]  # 17123_20250917_072506
    start_time = parts[1]  # 1758065469153000000
    end_time = parts[2]  # 1758065486553000000

    return {
        "trip_id": trip_part,
        "start_time": start_time,
        "end_time": end_time,
        "full_name": filename,
    }


def get_dataset_file_set(file_path):
    """获取目录中的文件集合并解析每个文件"""
    files = {}
    for f in os.listdir(file_path):
        parsed = parse_filename(f)
        if parsed:
            files[f] = parsed
    return files


def compare_dataset_files():
    dir1 = "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-labeled/20251109/train"
    # dir2 = "/home/luban/ofs/user/jasperchen/2025Q2_weekly_tensor_dict-train_label-labeled_test/20251109/train"
    dir2 = "/home/luban/ofs/dataset/2025Q2_weekly_tensor_dict-train_label-labeled-ra-event/20251109/train"

    print(f"Comparing trip files in {dir1} and {dir2}, len of files: {len(os.listdir(dir1))} and {len(os.listdir(dir2))}")
    print("=" * 80)

    files1 = get_dataset_file_set(dir1)
    files2 = get_dataset_file_set(dir2)

    # 按trip ID分组
    trips1 = defaultdict(list)
    trips2 = defaultdict(list)

    for file_info in files1.values():
        trips1[file_info["trip_id"]].append(file_info)

    for file_info in files2.values():
        trips2[file_info["trip_id"]].append(file_info)

    # 找出所有唯一的trip ID
    print("Trip1 len:", len(trips1))
    print("Trip2 len:", len(trips2))
    all_trip_ids = set(trips1.keys()) | set(trips2.keys())
    intersect = set(trips1.keys()) & set(trips2.keys())

    print(f"Total unique trip IDs: {len(all_trip_ids)}")
    print(f"Trips in dir1: {len(trips1)}")
    print(f"Trips in dir2: {len(trips2)}")
    print(f"Intersection: {len(intersect)}")
    print()

    # 对trip ID统计起止时间是否相同
    start_time_diffs = {}
    end_time_diffs = {}
    start_or_end_same_count = 0
    for trip_id in all_trip_ids:
        trip1 = trips1.get(trip_id)
        trip2 = trips2.get(trip_id)

        if trip1 and trip2:
            start_time_diffs[trip_id] = int(trip1[0]["start_time"]) - int(
                trip2[0]["start_time"]
            )
            end_time_diffs[trip_id] = int(trip1[0]["end_time"]) - int(
                trip2[0]["end_time"]
            )
            if start_time_diffs[trip_id] == 0 or end_time_diffs[trip_id] == 0:
                start_or_end_same_count += 1
    print(f"Start or End Same Count: {start_or_end_same_count}")

    # 打印等于零的数量，并且输出不为零的差值列表
    same_start_time_count = 0
    for trip_id, diff in start_time_diffs.items():
        if diff == 0:
            same_start_time_count += 1
        else:
            print(f"Trip ID: {trip_id}, Start Time Diff: {diff / 1e9}")
    print(f"Same Start Time Count: {same_start_time_count}")

    same_end_time_count = 0
    for trip_id, diff in end_time_diffs.items():
        if diff == 0:
            same_end_time_count += 1
        else:
            print(f"Trip ID: {trip_id}, End Time Diff: {diff / 1e9}")
    print(f"Same End Time Count: {same_end_time_count}")


if __name__ == "__main__":
    # test_npz()
    # scan_npz("/nfs/dataset-ofs-remote-assist-stuck/dataset/2025Q2_weekly_tensor_dict-train_label-labeled")
    # count_label()
    test_npz_2()
    # dump_events_to_json(
    #     "/home/luban/ofs/dataset/2025Q3_weekly_tensor_dict-unstuck/", "event_dict.json"
    # )
    # event_dict = load_events_from_json("event_dict.json")
    # dump_events_to_json_group_by_trip(
    #     "/home/luban/ofs/dataset/2025Q3_weekly_tensor_dict-unstuck/",
    #     "event_dict_group_by_trip.json",
    # )
    # check_npz(
    #     event_dict,
    #     "/nfs/dataset-ofs-remote-assist-stuck/dataset/2025Q2_weekly_tensor_dict-train_label-labeled-nearby",
    # )
    # check_trip_id_unique(event_dict)
    # final_stats = get_pos_neg_ratio(
    #     "/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/stuck_assist_model/configs/scenario_dnn_finetune_original_data.yaml"
    # )
    # print(final_stats)
    # summarize_all(final_stats)
    # compare_dataset_files()
