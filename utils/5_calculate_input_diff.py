import os
import numpy as np

from tqdm import tqdm


def print_dict(d):
    rows = []

    for k, v in d.items():
        arr_fp32 = np.array(v, dtype=np.float32)

        # Small vector/scalar print raw
        if arr_fp32.ndim == 0 or (arr_fp32.ndim == 1 and arr_fp32.shape[0] <= 50):
            # rows.append((k, None))  # store raw
            continue

        # FP32 min/max
        min_fp32 = float(arr_fp32.min())
        max_fp32 = float(arr_fp32.max())

        # Quantize min/max
        min_fp16 = float(np.float16(min_fp32).astype(np.float32))
        max_fp16 = float(np.float16(max_fp32).astype(np.float32))

        min_val_error = abs(min_fp32 - min_fp16)
        max_val_error = abs(max_fp32 - max_fp16)

        # Full-array quantization for abs-error bounds
        arr_fp16 = arr_fp32.astype(np.float16).astype(np.float32)
        abs_err = np.abs(arr_fp32 - arr_fp16)
        min_abs_error = float(abs_err.min())
        max_abs_error = float(abs_err.max())

        rows.append((
            k,
            arr_fp32.shape, arr_fp32.ndim, str(arr_fp32.dtype),
            min_fp32, min_fp16, min_val_error,
            max_fp32, max_fp16, max_val_error,
            min_abs_error, max_abs_error
        ))

    # Sort by impact on model output — max_val_error descending
    rows.sort(key=lambda x: (0 if x[11] is None else -x[11]))

    # Print
    print("=" * 180)
    print(
        f"{'Name':30s} {'Shape':25s} {'ndim':>4s} {'dtype':>10s} "
        f"{'min(FP32)':>12s} {'min(FP16)':>12s} {'min_val_err':>14s} "
        f"{'max(FP32)':>12s} {'max(FP16)':>12s} {'max_val_err':>14s} "
        f"{'min_abs_err':>14s} {'max_abs_err':>14s}"
    )
    print("-" * 180)

    for row in rows:
        k = row[0]
        if row[1] is None:
            print(f"{k:30s}: {d[k]}")
        else:
            (_, shape, ndim, dtype,
             min_fp32, min_fp16, min_val_err,
             max_fp32, max_fp16, max_val_err,
             min_abs_error, max_abs_error) = row

            print(
                f"{k:30s} {str(shape):25s} {ndim:4d} {dtype:>10s} "
                f"{min_fp32:12.4f} {min_fp16:12.4f} {min_val_err:14.4f} "
                f"{max_fp32:12.4f} {max_fp16:12.4f} {max_val_err:14.4f} "
                f"{min_abs_error:14.4f} {max_abs_error:14.4f}"
            )

    print("=" * 180)



def load_one_sample():
    x = dict(
        np.load(
            "/Users/didi/workspace/python/data/2883349300000001.npz",
            allow_pickle=True,
        )
    )
    print_dict(x)


def scan_npz_folder(folder):
    stats = {}  # k -> {"min_fp32":..., "max_fp32":..., "max_abs_err":...}

    files = [f for f in os.listdir(folder) if f.endswith(".npz")]
    if not files:
        print("❌ No npz files found.")
        return

    print(f"📂 Scanning folder: {folder}, {len(files)} files found\n")

    for fname in tqdm(files):
        path = os.path.join(folder, fname)
        data = dict(np.load(path, allow_pickle=True))

        for k, v in data.items():
            arr_fp32 = np.array(v, dtype=np.float32)
            if arr_fp32.ndim == 0:
                continue

            # FP32 min/max 记录
            vmin = float(arr_fp32.min())
            vmax = float(arr_fp32.max())

            if k not in stats:
                stats[k] = {"min_fp32": vmin, "max_fp32": vmax, "max_abs_err": 0.0}
            else:
                stats[k]["min_fp32"] = min(stats[k]["min_fp32"], vmin)
                stats[k]["max_fp32"] = max(stats[k]["max_fp32"], vmax)

            # 逐元素误差扫描
            arr_fp16 = arr_fp32.astype(np.float16).astype(np.float32)
            abs_err = np.abs(arr_fp32 - arr_fp16)
            max_abs_err = float(abs_err.max())
            stats[k]["max_abs_err"] = max(stats[k]["max_abs_err"], max_abs_err)

    # 计算 min/max 边界量化误差
    rows = []
    for k, rec in stats.items():
        min_fp32 = rec["min_fp32"]
        max_fp32 = rec["max_fp32"]

        min_fp16 = float(np.float16(min_fp32).astype(np.float32))
        max_fp16 = float(np.float16(max_fp32).astype(np.float32))

        min_val_err = abs(min_fp32 - min_fp16)
        max_val_err = abs(max_fp32 - max_fp16)

        rows.append((
            k,
            min_fp32, min_fp16, min_val_err,
            max_fp32, max_fp16, max_val_err,
            rec["max_abs_err"],
        ))

    # 按 max_abs_error 降序排序（FP16 风险最大在前）
    rows.sort(key=lambda x: -x[7])

    print("=" * 150)
    print(
        f"{'Name':30s} "
        f"{'min(FP32)':>12s} {'min(FP16)':>12s} {'min_val_err':>14s} "
        f"{'max(FP32)':>12s} {'max(FP16)':>12s} {'max_val_err':>14s} "
        f"{'max_abs_err':>14s}"
    )
    print("-" * 150)

    for row in rows:
        (k,
         min_fp32, min_fp16, min_val_err,
         max_fp32, max_fp16, max_val_err,
         max_abs_err) = row

        print(
            f"{k:30s} "
            f"{min_fp32:12.4f} {min_fp16:12.4f} {min_val_err:14.4f} "
            f"{max_fp32:12.4f} {max_fp16:12.4f} {max_val_err:14.4f} "
            f"{max_abs_err:14.4f}"
        )

    print("=" * 150)


if __name__ == "__main__":
    load_one_sample()
    # scan_npz_folder("/home/luban/workspace/examples/ifx_fp32_nearby_large/")
