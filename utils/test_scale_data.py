import numpy as np


def print_dict(d):
    print("-" * 100)
    for k, v in d.items():
        if v.ndim == 0 or v.ndim == 1 and v.shape[0] <= 50:
            print(f"{k}: {v}")
        else:
            print(f"{k}.shape: {v.shape}, ndim: {v.ndim}, dtype: {v.dtype}")


y1 = dict(
    np.load(
        "/Users/didi/utils/ifx_fp32_after_scaling/ifx_test_sample_19.npz",
        allow_pickle=True,
    )
)
print(y1)
