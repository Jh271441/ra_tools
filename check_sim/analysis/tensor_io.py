"""TensorDict and NPZ conversion helpers shared by check_sim commands."""

from pathlib import Path

import numpy as np

try:
    from .features import EXPECTED_SHAPES
except ImportError:
    from features import EXPECTED_SHAPES


def tensor_values(value):
    values = []
    values.extend(getattr(value, "float_vals", []))
    values.extend(getattr(value, "double_vals", []))
    values.extend(getattr(value, "int_vals", []))
    return values


def tensor_to_numpy(value, target_shape):
    float_values = list(getattr(value, "float_vals", []))
    double_values = list(getattr(value, "double_vals", []))
    int_values = list(getattr(value, "int_vals", []))
    values = float_values + double_values + int_values
    dtype = (
        np.int64
        if int_values and not float_values and not double_values
        else np.float32
    )
    array = np.asarray(values, dtype=dtype)
    expected_size = int(np.prod(target_shape))
    if array.size != expected_size:
        raise ValueError(
            f"expected shape {target_shape} ({expected_size} values), got {array.size}"
        )
    return array.reshape(target_shape)


def tensor_dict_to_features(tensor_dict):
    if not tensor_dict:
        raise RuntimeError("TensorDict is empty")

    missing = sorted(set(EXPECTED_SHAPES) - set(tensor_dict))
    if missing:
        raise RuntimeError(f"Missing features: {', '.join(missing)}")
    return {
        name: tensor_to_numpy(tensor_dict[name], shape)
        for name, shape in EXPECTED_SHAPES.items()
    }


def load_npz(path):
    with np.load(Path(path)) as data:
        return {name: data[name] for name in data.files}
