"""Zero-preprocessing Onboard Stuck DNN model runner (.ifxmodel, .onnx, or recorded).

Matches ``AssistDNNFeatureExtractor::TensorDict`` -> ``AssistStuckEstimator::InferWithTensorDict``
(``ScenarioNetInferWithTensor``):
  - No feature normalization, scaling, or slicing on stored ``TensorDict`` tensors.
  - Supports both 33-input (Q2) and 40-input (Q4 / model9) graphs dynamically.
  - Supports both single-head (``stuck_score``) and dual-head (4 outputs including
    ``stuck_score_neg_no_assist``) models identically to Onboard C++.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import subprocess
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np


MAIN_OUTPUT_NAME = "stuck_score"
STRICT_OUTPUT_NAME = "stuck_score_neg_no_assist"
DUAL_HEAD_OUTPUT_COUNT = 4
KNOWN_INT32_INPUTS = frozenset({"ego_Navigation", "ego_valid_len", "map_type"})

DEFAULT_SDK_INCLUDES = (
    Path("/usr/include"),
    Path("/opt/voy-sdk/include"),
)
DEFAULT_SDK_LIB_DIRS = (
    Path("/usr/lib"),
    Path("/lib/x86_64-linux-gnu"),
    Path("/opt/voy-sdk/lib"),
    Path("/opt/voy-sdk/runtime/lib/intel64"),
    Path("/usr/lib/x86_64-linux-gnu/libnvinfer10.9"),
    Path("/usr/local/cuda/lib64"),
)
PRELOAD_SHARED_LIBS = (
    "libtbb.so.2",
    "libopenvino.so.2330",
    "libnvinfer.so.10",
    "libnvinfer_plugin.so.10",
    "libifx.so.2",
    "libifx.so",
)


@dataclass(frozen=True)
class TensorSpec:
    name: str
    shape: Tuple[int, ...]
    dtype: str  # "float32" or "int32"


@dataclass
class FrameScoreBatch:
    main_scores: np.ndarray  # float64[M]
    strict_scores: Optional[np.ndarray]  # float64[M] or None for single-head models
    backend: str
    device: str
    model_path: Optional[str]
    model_sha256: Optional[str]
    input_names: Tuple[str, ...]
    output_names: Tuple[str, ...]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _patch_int64_clip_onnx_bytes(model_path: Path) -> Optional[bytes]:
    """Rewrite int64 Clip(x, min, max) -> Max(Min(x, max), min) in-memory for ORT CPU compatibility."""
    try:
        import onnx
        from onnx import helper
    except ImportError:
        return None
    model = onnx.load(str(model_path))
    new_nodes = []
    changed = False
    for idx, node in enumerate(model.graph.node):
        if node.op_type == "Clip" and len(node.input) >= 2:
            x_in = node.input[0]
            min_in = node.input[1] if len(node.input) > 1 and node.input[1] else ""
            max_in = node.input[2] if len(node.input) > 2 and node.input[2] else ""
            cur = x_in
            if max_in:
                mid = f"{node.name or 'clip'}_{idx}_min_out"
                new_nodes.append(helper.make_node("Min", [cur, max_in], [mid if min_in else node.output[0]]))
                cur = mid
            if min_in:
                new_nodes.append(helper.make_node("Max", [cur, min_in], [node.output[0]]))
            changed = True
        else:
            new_nodes.append(node)
    if not changed:
        return None
    del model.graph.node[:]
    model.graph.node.extend(new_nodes)
    return model.SerializeToString()


def ensure_ifx_bridge_library(
    bridge_path: Optional[Path] = None,
    *,
    sdk_includes: Sequence[Path] = DEFAULT_SDK_INCLUDES,
    sdk_lib_dirs: Sequence[Path] = DEFAULT_SDK_LIB_DIRS,
) -> Path:
    """Locate or auto-compile ``ifx_native_bridge.so`` against Voy-SDK / ``libifx``."""
    env_override = os.environ.get("RA_ONBOARD_IFX_BRIDGE_SO")
    if bridge_path is not None:
        candidate = Path(bridge_path).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"IFX bridge library not found: {candidate}")
        return candidate
    if env_override:
        candidate = Path(env_override).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"RA_ONBOARD_IFX_BRIDGE_SO does not exist: {candidate}")
        return candidate

    src_path = Path(__file__).resolve().parent / "native" / "ifx_native_bridge.cpp"
    if not src_path.is_file():
        raise FileNotFoundError(f"Missing IFX native bridge source: {src_path}")

    src_hash = hashlib.sha256(src_path.read_bytes()).hexdigest()[:12]
    arch = f"{platform.system().lower()}_{platform.machine().lower()}"
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ra_onboard_npz"
    cache_root.mkdir(parents=True, exist_ok=True)
    so_path = cache_root / f"ifx_native_bridge_{arch}_{src_hash}.so"
    if so_path.is_file():
        return so_path

    found_inc = next((inc for inc in sdk_includes if (inc / "ifx" / "ifx.h").is_file()), None)
    if found_inc is None:
        raise RuntimeError(
            f"Cannot compile native IFX bridge on {platform.node()}: missing ifx/ifx.h in "
            f"{[str(p) for p in sdk_includes]}. Run .ifxmodel inference on a Linux host with Voy-SDK "
            "installed, or pass an .onnx model."
        )

    existing_lib_dirs = [str(d) for d in sdk_lib_dirs if d.is_dir()]
    rpath_flags: List[str] = []
    lib_flags: List[str] = []
    for d in existing_lib_dirs:
        lib_flags.append(f"-L{d}")
        rpath_flags.append(f"-Wl,-rpath,{d}")

    tmp_so = so_path.with_suffix(f".tmp.{os.getpid()}.so")
    cmd = [
        os.environ.get("CXX", "g++"),
        "-O2",
        "-std=c++17",
        "-shared",
        "-fPIC",
        f"-I{found_inc}",
        str(src_path),
        *lib_flags,
        "-lifx",
        *rpath_flags,
        "-o",
        str(tmp_so),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        tmp_so.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to compile ifx_native_bridge.so (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    tmp_so.replace(so_path)
    return so_path


class _NativeIfxBackend:
    """Direct ctypes binding to ``ifx::Graph`` / ``ifx::Session``."""

    def __init__(self, model_path: Path, *, cuda: bool = False, bridge_so: Optional[Path] = None):
        self.model_path = model_path.resolve()
        self.cuda = bool(cuda)
        self.so_path = ensure_ifx_bridge_library(bridge_so)
        for soname in PRELOAD_SHARED_LIBS:
            for lib_dir in DEFAULT_SDK_LIB_DIRS:
                cand = lib_dir / soname
                if cand.is_file():
                    try:
                        ctypes.CDLL(str(cand), mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass
                    break
        lib = ctypes.CDLL(str(self.so_path))
        lib.ifx_validation_error.restype = ctypes.c_char_p
        lib.ifx_validation_open.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.ifx_validation_open.restype = ctypes.c_void_p
        lib.ifx_validation_close.argtypes = [ctypes.c_void_p]
        lib.ifx_validation_close.restype = None
        lib.ifx_validation_count.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.ifx_validation_count.restype = ctypes.c_int
        lib.ifx_validation_name.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        lib.ifx_validation_name.restype = ctypes.c_char_p
        lib.ifx_validation_shape.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.ifx_validation_shape.restype = ctypes.c_int
        lib.ifx_validation_infer.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.ifx_validation_infer.restype = ctypes.c_int
        lib.ifx_validation_output_fp32.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.ifx_validation_output_fp32.restype = ctypes.POINTER(ctypes.c_float)
        has_dtype_name = hasattr(lib, "ifx_validation_dtype_name")
        if has_dtype_name:
            lib.ifx_validation_dtype_name.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            lib.ifx_validation_dtype_name.restype = ctypes.c_char_p

        self._lib = lib
        self._handle = lib.ifx_validation_open(str(self.model_path).encode("utf-8"), int(self.cuda))
        if not self._handle:
            err = (lib.ifx_validation_error() or b"unknown error").decode("utf-8", errors="replace")
            raise RuntimeError(f"IFX open failed for {self.model_path}: {err}")

        self.inputs: List[TensorSpec] = self._query_specs(0, has_dtype_name)
        self.outputs: List[TensorSpec] = self._query_specs(1, has_dtype_name)

    def _query_specs(self, is_output: int, has_dtype_name: bool) -> List[TensorSpec]:
        count = self._lib.ifx_validation_count(self._handle, is_output)
        specs: List[TensorSpec] = []
        shape_buf = (ctypes.c_int32 * 8)()
        dtype_code = ctypes.c_int()
        for i in range(count):
            name = self._lib.ifx_validation_name(self._handle, is_output, i).decode("utf-8")
            rank = self._lib.ifx_validation_shape(self._handle, is_output, i, shape_buf, ctypes.byref(dtype_code))
            if rank <= 0:
                err = (self._lib.ifx_validation_error() or b"shape error").decode("utf-8", errors="replace")
                raise RuntimeError(f"IFX shape query failed for {name}: {err}")
            raw_dims = [int(shape_buf[d]) for d in range(rank)]
            if not is_output and raw_dims and raw_dims[0] <= 0:
                raw_dims[0] = 1
            shape = tuple(raw_dims)
            if has_dtype_name:
                dt_str = self._lib.ifx_validation_dtype_name(self._handle, is_output, i).decode("utf-8")
                if dt_str not in ("float32", "int32"):
                    dt_str = "int32" if name in KNOWN_INT32_INPUTS else "float32"
            else:
                dt_str = "int32" if name in KNOWN_INT32_INPUTS else "float32"
            specs.append(TensorSpec(name=name, shape=shape, dtype=dt_str))
        return specs

    def run_single(self, frame_inputs: Sequence[np.ndarray]) -> Dict[str, np.ndarray]:
        in_ptrs = (ctypes.c_void_p * len(self.inputs))()
        keepalive: List[np.ndarray] = []
        for idx, arr in enumerate(frame_inputs):
            contig = np.ascontiguousarray(arr)
            keepalive.append(contig)
            in_ptrs[idx] = contig.ctypes.data_as(ctypes.c_void_p)

        rc = self._lib.ifx_validation_infer(self._handle, in_ptrs)
        if rc != 0:
            err = (self._lib.ifx_validation_error() or b"inference error").decode("utf-8", errors="replace")
            raise RuntimeError(f"IFX doInference failed: {err}")

        out_arrays: Dict[str, np.ndarray] = {}
        n_floats = ctypes.c_int()
        for idx, spec in enumerate(self.outputs):
            ptr = self._lib.ifx_validation_output_fp32(self._handle, idx, ctypes.byref(n_floats))
            if not ptr:
                err = (self._lib.ifx_validation_error() or b"output read error").decode("utf-8", errors="replace")
                raise RuntimeError(f"IFX output read failed for {spec.name}: {err}")
            out_arrays[spec.name] = np.ctypeslib.as_array(ptr, shape=(int(n_floats.value),)).copy()
        return out_arrays

    def close(self) -> None:
        if getattr(self, "_handle", None):
            self._lib.ifx_validation_close(self._handle)
            self._handle = None

    def __del__(self) -> None:
        self.close()


class _OnnxBackend:
    """ONNX Runtime backend adhering to the identical batch-1 TensorDict contract."""

    def __init__(self, model_path: Path, *, cuda: bool = False):
        import onnxruntime as ort

        self.model_path = model_path.resolve()
        self.cuda = bool(cuda)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if cuda else ["CPUExecutionProvider"]
        try:
            self._session = ort.InferenceSession(str(self.model_path), sess_options=opts, providers=providers)
        except Exception as exc:
            if "Clip" in str(exc):
                patched_bytes = _patch_int64_clip_onnx_bytes(self.model_path)
                if patched_bytes is not None:
                    self._session = ort.InferenceSession(patched_bytes, sess_options=opts, providers=providers)
                else:
                    raise RuntimeError(
                        f"ONNX Runtime failed on raw Clip(int64) op in {self.model_path.name}; "
                        "install 'onnx' for automatic in-memory patching, pass an .ort_compat.onnx file, "
                        "or use the native .ifxmodel artifact."
                    ) from exc
            else:
                raise
        self.active_provider = self._session.get_providers()[0]

        self.inputs: List[TensorSpec] = []
        for node in self._session.get_inputs():
            dt = "int32" if "int32" in node.type else ("int64" if "int64" in node.type else "float32")
            shape = tuple(1 if (d is None or isinstance(d, str)) else int(d) for d in node.shape)
            self.inputs.append(TensorSpec(name=node.name, shape=shape, dtype=dt))

        self.outputs: List[TensorSpec] = []
        for node in self._session.get_outputs():
            shape = tuple(1 if (d is None or isinstance(d, str)) else int(d) for d in node.shape)
            self.outputs.append(TensorSpec(name=node.name, shape=shape, dtype="float32"))
        self._output_names = [s.name for s in self.outputs]

    def run_single(self, frame_inputs: Sequence[np.ndarray]) -> Dict[str, np.ndarray]:
        feed = {spec.name: arr for spec, arr in zip(self.inputs, frame_inputs)}
        raw_outs = self._session.run(self._output_names, feed)
        return {name: np.asarray(val, dtype=np.float32) for name, val in zip(self._output_names, raw_outs)}

    def close(self) -> None:
        self._session = None


class OnboardModelRunner:
    """Unified Onboard Stuck ScenarioNet runner (.ifxmodel, .onnx, or recorded scores)."""

    def __init__(
        self,
        model_path: Optional[os.PathLike | str] = None,
        *,
        device: str = "cpu",
        bridge_so: Optional[Path] = None,
    ):
        if device not in ("cpu", "cuda"):
            raise ValueError(f"Unsupported device {device!r}; expected 'cpu' or 'cuda'")
        self.device = device
        if model_path is None or str(model_path) == "recorded":
            self.model_path = None
            self.model_sha256 = None
            self.backend_name = "recorded"
            self._backend = None
            self.inputs: Tuple[TensorSpec, ...] = ()
            self.outputs: Tuple[TensorSpec, ...] = ()
            return

        resolved = Path(model_path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Model file does not exist: {resolved}")
        self.model_path = resolved
        self.model_sha256 = _sha256_file(resolved)
        lower_name = resolved.name.lower()
        use_cuda = device == "cuda"
        if lower_name.endswith(".ifxmodel") or ".ifxmodel_" in lower_name:
            self._backend = _NativeIfxBackend(resolved, cuda=use_cuda, bridge_so=bridge_so)
            self.backend_name = "ifx_cuda" if use_cuda else "ifx_x86"
        elif lower_name.endswith(".onnx") or ".onnx_" in lower_name:
            self._backend = _OnnxBackend(resolved, cuda=use_cuda)
            self.backend_name = f"onnxruntime:{self._backend.active_provider}"
        else:
            raise ValueError(
                f"Unsupported model file {resolved.name!r}; expected .ifxmodel or .onnx"
            )

        self.inputs = tuple(self._backend.inputs)
        self.outputs = tuple(self._backend.outputs)
        out_names = {s.name for s in self.outputs}
        if MAIN_OUTPUT_NAME not in out_names:
            raise ValueError(f"Model {resolved} missing required output {MAIN_OUTPUT_NAME!r}; got {sorted(out_names)}")

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()

    def __enter__(self) -> "OnboardModelRunner":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def infer_npz(
        self,
        npz_data: Mapping[str, np.ndarray],
        *,
        only_frame_indices: Optional[Sequence[int]] = None,
    ) -> FrameScoreBatch:
        """Run zero-preprocessing Onboard ScenarioNet inference over NPZ TensorDict frames.

        If ``only_frame_indices`` is supplied (e.g. only the frames actually consumed by
        ``PlanningSpeedVNode`` in Layer 2), non-selected frames are filled with ``NaN`` so
        frame indexing stays 1-to-1 with the NPZ ``TensorDict`` axis without wasting compute
        on moving-car safety-only frames.
        """
        if self._backend is None:
            raise RuntimeError("Recorded-score runner does not execute TensorDict forward; pass a model file.")

        has_dual_head = (
            len(self.outputs) == DUAL_HEAD_OUTPUT_COUNT
            and any(s.name == STRICT_OUTPUT_NAME for s in self.outputs)
        )
        if "tensor_dict_timestamp" in npz_data and np.asarray(npz_data["tensor_dict_timestamp"]).size == 0:
            return FrameScoreBatch(
                main_scores=np.zeros(0, dtype=np.float64),
                strict_scores=np.zeros(0, dtype=np.float64) if has_dual_head else None,
                backend=self.backend_name,
                device=self.device,
                model_path=str(self.model_path) if self.model_path else None,
                model_sha256=self.model_sha256,
                input_names=tuple(s.name for s in self.inputs),
                output_names=tuple(s.name for s in self.outputs),
            )

        missing = [spec.name for spec in self.inputs if spec.name not in npz_data]
        if missing:
            raise KeyError(f"NPZ is missing {len(missing)} required model inputs: {missing[:8]}")

        prepared: List[np.ndarray] = []
        n_frames: Optional[int] = None
        for spec in self.inputs:
            arr = np.asarray(npz_data[spec.name])
            expected_item_shape = spec.shape[1:]
            # Handle legacy NPZs where a rank-2 [1, D] input was stored as [M, 1, D] vs [M, D]
            if arr.ndim == len(spec.shape) + 1 and arr.shape[1] == 1 and arr.shape[2:] == expected_item_shape:
                arr = arr[:, 0, ...]
            if arr.ndim != len(spec.shape) or arr.shape[1:] != expected_item_shape:
                raise ValueError(
                    f"Input {spec.name!r} shape mismatch: NPZ has {arr.shape}, model expects (M, *{expected_item_shape})"
                )
            if n_frames is None:
                n_frames = int(arr.shape[0])
            elif arr.shape[0] != n_frames:
                raise ValueError(f"Inconsistent frame count for {spec.name!r}: {arr.shape[0]} vs {n_frames}")

            if spec.dtype == "float32":
                if arr.dtype != np.float32:
                    raise TypeError(f"Input {spec.name!r} must be float32 (no cast/norm), got {arr.dtype}")
                if not np.isfinite(arr).all():
                    raise ValueError(f"Input {spec.name!r} contains NaN/Inf values")
            elif spec.dtype in ("int32", "int64"):
                target_dt = np.int32 if spec.dtype == "int32" else np.int64
                if arr.dtype not in (np.int32, np.int64):
                    raise TypeError(f"Input {spec.name!r} must be integer tensor, got {arr.dtype}")
                arr = arr.astype(target_dt, copy=False)
            prepared.append(arr)

        assert n_frames is not None
        main_scores = np.full(n_frames, np.nan, dtype=np.float64)
        strict_scores = np.full(n_frames, np.nan, dtype=np.float64) if has_dual_head else None

        target_indices = (
            range(n_frames)
            if only_frame_indices is None
            else sorted({int(i) for i in only_frame_indices if 0 <= int(i) < n_frames})
        )
        for frame_idx in target_indices:
            single_feed = [arr[frame_idx : frame_idx + 1] for arr in prepared]
            outs = self._backend.run_single(single_feed)
            main_val = float(outs[MAIN_OUTPUT_NAME].reshape(-1)[0])
            if not np.isnan(main_val):
                main_scores[frame_idx] = main_val
            if strict_scores is not None:
                strict_val = float(outs[STRICT_OUTPUT_NAME].reshape(-1)[0])
                if not np.isnan(strict_val):
                    strict_scores[frame_idx] = strict_val

        return FrameScoreBatch(
            main_scores=main_scores,
            strict_scores=strict_scores,
            backend=self.backend_name,
            device=self.device,
            model_path=str(self.model_path) if self.model_path else None,
            model_sha256=self.model_sha256,
            input_names=tuple(s.name for s in self.inputs),
            output_names=tuple(s.name for s in self.outputs),
        )
