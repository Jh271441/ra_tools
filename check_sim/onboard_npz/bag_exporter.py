"""Pure-Python exporter from Voyager road/sim ROS1 bags to Enhanced Onboard Road NPZs.

Zero external Python ROS/protobuf dependencies required:
  - Reads ROSBAG V2.0 files directly (chunked or unindexed, ``none`` / ``bz2`` / optional ``lz4``).
  - Unwraps Voyager ``proto_msg`` 4-byte little-endian framing automatically.
  - Parses exact Onboard protobuf wire fields from:
      * ``/planning/remote_assist_debug`` (or ``/planning/planning_debug`` fallback) — 10Hz detector
      * ``/planning/remote_assist_model_debug`` — uncropped ``TensorDict`` dumps (all 33/40/49 keys)
      * ``/planning/seed`` — asynchronous ``AssistStuckModelOutput`` delivery schedule
      * ``/planner/state`` — pre-bag detector & likelihood queue state
      * ``/planning/assist_request`` — ground-truth emitted ``AssistChannelConnectRequest``s
  - Produces a single compact ``.npz`` (~1.5–2.5 MB/case) + ``.EXPORT.json`` receipt with zero simulation.
"""

from __future__ import annotations

import bz2
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import struct
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from .schema import (
    ALREADY_IN_ASSIST_STATUSES,
    DEFAULT_FN_REASON_TASK_CODE,
    EARLY_RETURN_STATUSES,
    ENHANCED_NPZ_SCHEMA,
    TIER_LAYER2_ROAD_10HZ,
    AssistModelProcessReason,
    TaskCode,
    UnstuckStatus,
)


ROAD_EXPORT_TOPICS: Tuple[str, ...] = (
    "/planning/remote_assist_debug",
    "/planning/planning_debug",
    "/planning/remote_assist_model_debug",
    "/planning/seed",
    "/planner/state",
    "/planning/assist_request",
)

LIGHTWEIGHT_DOWNLOAD_TOPICS: Tuple[str, ...] = (
    "/planning/remote_assist_debug",
    "/planning/remote_assist_model_debug",
    "/planning/seed",
    "/planner/state",
    "/planning/assist_request",
)

RESERVED_NPZ_KEYS = frozenset({
    "npz_schema",
    "npz_tier",
    "issue_id",
    "trip_id",
    "source_kind",
    "source_bag_sha256",
    "start_time",
    "end_time",
    "formal_window_ms",
    "formal_initial_state_json",
    "tensor_dict_timestamp",
    "producer_publication_timestamp_ns",
    "producer_sequence",
    "cycle_timestamp_ms",
    "cycle_sequence",
    "consumed_frame_index",
    "recorded_main_score",
    "recorded_strict_score",
    "entry_gate_status",
    "ego_moving_fast",
    "already_in_assist_status",
    "non_voluntary_unstuck_reason",
    "has_voluntary_unstuck_modes",
    "is_voluntary_unstuck_fail",
    "stationary_cycle_count",
    "stuck_threshold",
    "is_vlm_block",
    "core_planner_status",
    "flag_or_omni_status",
    "special_stuck_task_code",
    "scheduler_session_blocked",
    "fp_reasons_json",
    "fn_non_model_reasons_json",
    "initial_state_json",
    "gt_unstuck_status",
    "gt_is_stuck_by_model",
    "gt_is_strict_stuck_by_model",
    "gt_rule_decision",
    "gt_process_reason",
    "gt_timer_elapsed_ms",
    "gt_continuous_fn_cnt",
    "gt_queue_len",
    "gt_queue_top3",
    "gt_connect_request_ts",
    "gt_connect_request_id",
    "gt_connect_request_type",
})


# ---------------------------------------------------------------------------
# Pure-Python ROSBAG V2.0 reader & Protobuf wire parser
# ---------------------------------------------------------------------------


class _IncompleteBagRecord(Exception):
    pass


def _read_exact(stream, size: int) -> bytes:
    raw = stream.read(size)
    if len(raw) != size:
        raise _IncompleteBagRecord
    return raw


def _parse_bag_header(raw: bytes) -> Dict[bytes, bytes]:
    offset = 0
    fields: Dict[bytes, bytes] = {}
    n = len(raw)
    while offset < n:
        if offset + 4 > n:
            raise ValueError("Truncated ROS1 bag record header")
        (size,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        if not 0 < size <= n - offset:
            raise ValueError("Invalid ROS1 bag header field size")
        key, value = raw[offset : offset + size].split(b"=", 1)
        fields[key] = value
        offset += size
    return fields


def _iter_bag_records(stream, end: int):
    while stream.tell() < end:
        (header_size,) = struct.unpack("<I", _read_exact(stream, 4))
        if header_size + 4 > end - stream.tell() or not 0 < header_size <= 4 * 1024 * 1024:
            raise _IncompleteBagRecord
        fields = _parse_bag_header(_read_exact(stream, header_size))
        (data_size,) = struct.unpack("<I", _read_exact(stream, 4))
        finish = stream.tell() + data_size
        if finish > end:
            raise _IncompleteBagRecord
        yield fields, data_size, finish
        stream.seek(finish)


def _decompress_chunk(compression: bytes, raw: bytes, expected_size: int) -> bytes:
    if compression == b"none":
        return raw
    if compression == b"bz2":
        data = bz2.decompress(raw)
        if expected_size and len(data) != expected_size:
            raise ValueError(f"BZ2 chunk size mismatch: {len(data)} != {expected_size}")
        return data
    if compression == b"lz4":
        try:
            import lz4.frame  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Bag uses lz4 chunks; install 'lz4' Python package to read it.") from exc
        data = lz4.frame.decompress(raw)
        if expected_size and len(data) != expected_size:
            raise ValueError(f"LZ4 chunk size mismatch: {len(data)} != {expected_size}")
        return data
    raise ValueError(f"Unsupported ROS1 bag chunk compression: {compression!r}")


def iter_rosbag_messages(
    bag_path: Path,
    topics: Iterable[str],
) -> Iterator[Tuple[str, int, bytes]]:
    """Yield ``(topic, pub_timestamp_ns, raw_message_bytes)`` from any ROSBAG V2.0 file."""
    wanted = set(topics)
    end = bag_path.stat().st_size
    connections: Dict[int, str] = {}

    def handle_record(rec_stream, fields: Dict[bytes, bytes], size: int):
        op = fields.get(b"op")
        if op == b"\x07":  # Connection record
            (conn_id,) = struct.unpack("<I", fields[b"conn"])
            topic = fields[b"topic"].decode("utf-8")
            connections[conn_id] = topic
        elif op == b"\x02":  # Message data record
            (conn_id,) = struct.unpack("<I", fields[b"conn"])
            topic = connections.get(conn_id)
            if topic in wanted:
                sec, nsec = struct.unpack("<II", fields[b"time"])
                yield topic, sec * 1_000_000_000 + nsec, _read_exact(rec_stream, size)

    with bag_path.open("rb") as stream:
        magic = stream.readline(32)
        if magic != b"#ROSBAG V2.0\n":
            raise ValueError(f"Unsupported bag header in {bag_path}: {magic!r}")
        try:
            for fields, size, finish in _iter_bag_records(stream, end):
                op = fields.get(b"op")
                if op == b"\x05":  # Chunk record
                    compression = fields.get(b"compression", b"none")
                    (expected,) = struct.unpack("<I", fields.get(b"size", b"\x00\x00\x00\x00"))
                    if compression == b"none" and size == expected == 0:
                        continue
                    if size == 0:
                        break
                    if compression == b"none":
                        for inner_f, inner_sz, _ in _iter_bag_records(stream, finish):
                            yield from handle_record(stream, inner_f, inner_sz)
                    else:
                        decomp = _decompress_chunk(compression, _read_exact(stream, size), expected)
                        buf = BytesIO(decomp)
                        for inner_f, inner_sz, _ in _iter_bag_records(buf, len(decomp)):
                            yield from handle_record(buf, inner_f, inner_sz)
                else:
                    yield from handle_record(stream, fields, size)
        except _IncompleteBagRecord:
            pass


def unwrap_ros_proto(raw: bytes | memoryview) -> memoryview:
    mv = memoryview(raw)
    if len(mv) >= 4 and struct.unpack_from("<I", mv, 0)[0] == len(mv) - 4:
        return mv[4:]
    return mv


def _varint(buf: memoryview, pos: int) -> Tuple[int, int]:
    val = 0
    shift = 0
    n = len(buf)
    while pos < n:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7
        if shift > 70:
            raise ValueError("Invalid protobuf varint")
    raise ValueError("Truncated protobuf varint")


def parse_proto_fields(buf: bytes | memoryview) -> Dict[int, List[Tuple[int, Any]]]:
    mv = memoryview(buf)
    pos = 0
    n = len(mv)
    out: Dict[int, List[Tuple[int, Any]]] = {}
    while pos < n:
        tag, pos = _varint(mv, pos)
        fn = tag >> 3
        wt = tag & 7
        if fn <= 0:
            raise ValueError("Invalid protobuf field number 0")
        if wt == 0:
            val, pos = _varint(mv, pos)
        elif wt == 1:
            if pos + 8 > n:
                raise ValueError("Truncated fixed64 field")
            val = mv[pos : pos + 8]
            pos += 8
        elif wt == 2:
            ln, pos = _varint(mv, pos)
            if pos + ln > n:
                raise ValueError("Truncated length-delimited field")
            val = mv[pos : pos + ln]
            pos += ln
        elif wt == 5:
            if pos + 4 > n:
                raise ValueError("Truncated fixed32 field")
            val = mv[pos : pos + 4]
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wt}")
        out.setdefault(fn, []).append((wt, val))
    return out


def _as_int64(val: int) -> int:
    return val - (1 << 64) if val & (1 << 63) else val


def _scalar_int(fields: Dict[int, List[Tuple[int, Any]]], fn: int, default: int = 0) -> int:
    if fn not in fields:
        return default
    wt, v = fields[fn][-1]
    if wt != 0:
        raise ValueError(f"Expected varint at field {fn}, got wire {wt}")
    return _as_int64(v)


def _scalar_float(fields: Dict[int, List[Tuple[int, Any]]], fn: int) -> Optional[float]:
    if fn not in fields:
        return None
    wt, v = fields[fn][-1]
    if wt == 5:
        return float(struct.unpack("<f", v)[0])
    if wt == 1:
        return float(struct.unpack("<d", v)[0])
    raise ValueError(f"Expected float/double at field {fn}, got wire {wt}")


def _repeated_ints(fields: Dict[int, List[Tuple[int, Any]]], fn: int) -> List[int]:
    out: List[int] = []
    for wt, v in fields.get(fn, ()):
        if wt == 0:
            out.append(_as_int64(v))
        elif wt == 2:
            pos = 0
            mv = memoryview(v)
            while pos < len(mv):
                iv, pos = _varint(mv, pos)
                out.append(_as_int64(iv))
    return out


def _repeated_doubles(fields: Dict[int, List[Tuple[int, Any]]], fn: int) -> List[float]:
    out: List[float] = []
    for wt, v in fields.get(fn, ()):
        if wt == 1:
            out.append(float(struct.unpack("<d", v)[0]))
        elif wt == 5:
            out.append(float(struct.unpack("<f", v)[0]))
        elif wt == 2:
            out.extend(float(x[0]) for x in struct.iter_unpack("<d", v))
    return out


def _decode_ra_tensor(blob: memoryview) -> Tuple[Tuple[int, ...], np.ndarray]:
    """Decode ``voy_protos.RATensor`` (1=dims, 2=int32 data, 3=float32 data)."""
    f = parse_proto_fields(blob)
    shape = tuple(_repeated_ints(f, 1))
    if not shape or any(d <= 0 for d in shape):
        raise ValueError(f"Invalid RATensor shape: {shape}")
    count = math.prod(shape)
    ints = _repeated_ints(f, 2)
    floats_raw = bytearray()
    for wt, v in f.get(3, ()):
        if wt in (2, 5):
            floats_raw.extend(v)
    if floats_raw and not ints:
        if len(floats_raw) != count * 4:
            raise ValueError(f"Float RATensor byte length {len(floats_raw)} != {count * 4}")
        arr = np.frombuffer(bytes(floats_raw), dtype="<f4").reshape(shape).copy()
        if not np.isfinite(arr).all():
            raise ValueError("Non-finite float in RATensor")
        return shape, arr
    if ints and not floats_raw:
        if len(ints) != count:
            raise ValueError(f"Int32 RATensor count {len(ints)} != {count}")
        i32 = [(v & 0xFFFFFFFF) - (0x100000000 if v & 0x80000000 else 0) for v in ints]
        arr = np.asarray(i32, dtype="<i4").reshape(shape)
        return shape, arr
    raise ValueError("Ambiguous or empty RATensor payload")


# ---------------------------------------------------------------------------
# Message-level parsers
# ---------------------------------------------------------------------------


def _decode_tensor_dict_entries(entries: Sequence[Tuple[int, memoryview]]) -> Optional[Dict[str, np.ndarray]]:
    if not entries:
        return None
    tensors: Dict[str, np.ndarray] = {}
    for _, entry_blob in entries:
        ef = parse_proto_fields(entry_blob)
        name = bytes(ef[1][-1][1]).decode("utf-8")
        if name in RESERVED_NPZ_KEYS:
            raise ValueError(f"TensorDict name collides with reserved NPZ key: {name}")
        _, arr = _decode_ra_tensor(ef[2][-1][1])
        tensors[name] = arr
    return tensors or None


def _parse_model_debug_msg(pub_ns: int, raw: bytes) -> Optional[Dict[str, Any]]:
    top = parse_proto_fields(unwrap_ros_proto(raw))
    ts_ms = _scalar_int(top, 1, 0)
    seq = _scalar_int(top, 2, 0)
    if 8 not in top:
        return None
    f8 = parse_proto_fields(top[8][-1][1])
    tensors = _decode_tensor_dict_entries(f8.get(1, ()))
    if not tensors:
        return None
    return {
        "pub_ns": pub_ns,
        "timestamp_ms": ts_ms,
        "sequence": seq,
        "tensors": tensors,
    }


def _parse_seed_msg(
    pub_ns: int,
    raw: bytes,
    *,
    seen_seed_td_timestamps: Optional[set[int]] = None,
) -> Dict[str, Any]:
    top = parse_proto_fields(unwrap_ros_proto(raw))
    ts_ms = _scalar_int(top, 1, 0)
    seq = _scalar_int(top, 13, 0)
    prev_ts: Optional[int] = None
    main_score: Optional[float] = None
    strict_score: Optional[float] = None
    session_blocks_connect = False
    seed_td_frame: Optional[Dict[str, Any]] = None
    if 9 in top:
        bseed = parse_proto_fields(top[9][-1][1])
        if 8 in bseed:
            sched_seed = parse_proto_fields(bseed[8][-1][1])
            if 1 in sched_seed:
                sess = parse_proto_fields(sched_seed[1][-1][1])
                is_opened = bool(_scalar_int(sess, 1, 0))
                req_fields = parse_proto_fields(sess[3][-1][1]) if 3 in sess else {}
                session_blocks_connect = bool(is_opened and (9 not in req_fields))
        if 22 in bseed:
            aseed = parse_proto_fields(bseed[22][-1][1])
            if 9 in aseed:
                mout = parse_proto_fields(aseed[9][-1][1])
                if 1 in mout:
                    prev_ts = _scalar_int(mout, 1, 0)
                main_score = _scalar_float(mout, 2)
                strict_score = _scalar_float(mout, 6)
                # Legacy Release <= 20261009 stored map<string, RATensor> tensor_dict = 4
                # inside AssistStuckModelOutput before migrating to RemoteAssistModelDebug.field 8.
                if 4 in mout and seen_seed_td_timestamps is not None:
                    td_ts = int(prev_ts) if prev_ts is not None else int(ts_ms)
                    if td_ts not in seen_seed_td_timestamps:
                        tensors = _decode_tensor_dict_entries(mout[4])
                        if tensors is not None:
                            seen_seed_td_timestamps.add(td_ts)
                            seed_td_frame = {
                                "pub_ns": pub_ns,
                                "timestamp_ms": td_ts,
                                "sequence": seq,
                                "tensors": tensors,
                            }
    return {
        "pub_ns": pub_ns,
        "timestamp_ms": ts_ms,
        "sequence": seq,
        "prev_ts": prev_ts,
        "main_score": main_score,
        "strict_score": strict_score,
        "session_blocks_connect": session_blocks_connect,
        "seed_td_frame": seed_td_frame,
    }


def _parse_request_state(blob: memoryview) -> Dict[str, Any]:
    rs = parse_proto_fields(blob)
    seq_id = _scalar_int(rs, 1, 0)
    first_seq = _scalar_int(rs, 3, -1) if 3 in rs else -1
    tasks: Dict[str, Dict[str, int]] = {}
    for _, entry_blob in rs.get(2, ()):
        ef = parse_proto_fields(entry_blob)
        k = _scalar_int(ef, 1, 0)
        vf = parse_proto_fields(ef[2][-1][1]) if 2 in ef else {}
        tasks[str(k)] = {
            "task_code": _scalar_int(vf, 1, k),
            "state": _scalar_int(vf, 2, 0),
            "last_changed_seq_id": _scalar_int(vf, 3, 0),
            "last_changed_timestamp": _scalar_int(vf, 4, 0),
            "update_type": _scalar_int(vf, 5, 0),
            "process_reason": _scalar_int(vf, 6, 0),
            "request_id": _scalar_int(vf, 7, 0),
        }
    return {"seq_id": seq_id, "first_stuck_detected_seq_id": first_seq, "tasks": tasks}


def _parse_ego_stuck_debug(
    ts_ms: int,
    seq: int,
    pub_ns: int,
    esd_blob: memoryview,
    sched_blob: Optional[memoryview] = None,
) -> Dict[str, Any]:
    esd = parse_proto_fields(esd_blob)
    unstuck_status = _scalar_int(esd, 5, 0)
    by_model = bool(_scalar_int(esd, 6, 0))
    by_strict = bool(_scalar_int(esd, 41, 0))
    proc_reason = _scalar_int(esd, 7, 0)
    non_vol = _scalar_int(esd, 8, 0)
    by_core_planner = bool(_scalar_int(esd, 9, 0))
    thresh = _scalar_float(esd, 10)
    stat_cnt = _scalar_int(esd, 13, 0)
    cont_fn_cnt = _scalar_int(esd, 21, 0)
    lik = _scalar_float(esd, 34)
    strict_lik = _scalar_float(esd, 38)
    timer_ms = _scalar_float(esd, 39) or 0.0
    moving_cnt = _scalar_int(esd, 37, 0)
    vlm_block = bool(_scalar_int(esd, 45, 0))
    queue_vals = _repeated_doubles(esd, 32)

    has_rules_executed = 36 in esd
    rdbg = parse_proto_fields(esd[22][-1][1]) if 22 in esd else {}
    rule_decision = _scalar_int(rdbg, 1, 0) if has_rules_executed else -1
    fp_reasons = _repeated_ints(rdbg, 26)
    fn_reasons = _repeated_ints(rdbg, 27)
    req_state = _parse_request_state(esd[36][-1][1]) if 36 in esd else None

    special_task_code = int(TaskCode.STUCK_EGO_CAUSE_TRAFFIC_JAM)
    if 35 in esd:
        sp = parse_proto_fields(esd[35][-1][1])
        sp_type = _scalar_int(sp, 3, 0)
        if sp_type == 1:
            special_task_code = int(TaskCode.STUCK_EGO_CAUSE_TRAFFIC_JAM)
        elif sp_type == 2:
            special_task_code = int(TaskCode.STUCK_EGO_IN_NO_STOPPING_ZONE)
        elif sp_type == 3:
            special_task_code = int(TaskCode.STUCK_POTENTIAL_TRAFFIC_JAM)

    in_remote_assist = False
    if sched_blob is not None:
        sched = parse_proto_fields(sched_blob)
        if 6 in sched:
            ras = parse_proto_fields(sched[6][-1][1])
            in_remote_assist = bool(_scalar_int(ras, 1, 0))

    if unstuck_status in ALREADY_IN_ASSIST_STATUSES:
        already_in_assist_status = unstuck_status
    elif in_remote_assist:
        already_in_assist_status = int(UnstuckStatus.ALREADY_IN_LIGHT_ASSIST)
    else:
        already_in_assist_status = 0

    entry_gate_status = 0 if has_rules_executed else (
        unstuck_status if unstuck_status in EARLY_RETURN_STATUSES else int(UnstuckStatus.NO_DEBUG_MESSAGE)
    )

    return {
        "pub_ns": pub_ns,
        "timestamp_ms": ts_ms,
        "sequence": seq,
        "unstuck_status": unstuck_status,
        "by_model": by_model,
        "by_strict": by_strict,
        "proc_reason": proc_reason,
        "non_vol": non_vol,
        "by_core_planner": by_core_planner,
        "stuck_threshold": thresh if (thresh is not None and thresh > 0.0) else 0.5,
        "stationary_cycle_count": stat_cnt,
        "continuous_fn_cnt": cont_fn_cnt,
        "lik": lik,
        "strict_lik": strict_lik,
        "timer_ms": timer_ms,
        "moving_cnt": moving_cnt,
        "vlm_block": vlm_block,
        "queue_vals": queue_vals,
        "has_rules_executed": has_rules_executed,
        "entry_gate_status": entry_gate_status,
        "already_in_assist_status": already_in_assist_status,
        "rule_decision": rule_decision,
        "fp_reasons": fp_reasons,
        "fn_reasons": fn_reasons,
        "req_state": req_state,
        "special_task_code": special_task_code,
    }


def _parse_planner_state_msg(pub_ns: int, raw: bytes) -> Optional[Dict[str, Any]]:
    top = parse_proto_fields(unwrap_ros_proto(raw))
    ts_ms = _scalar_int(top, 1, 0)
    seq = _scalar_int(top, 2, 0)
    if 4 not in top:
        return None
    br = parse_proto_fields(top[4][-1][1])
    if 5 not in br:
        return None
    det = parse_proto_fields(br[5][-1][1])
    queue_entries: List[Tuple[int, float, Optional[float]]] = []
    for _, ob in det.get(18, ()):
        of = parse_proto_fields(ob)
        q_ts = _scalar_int(of, 1, 0)
        q_main = _scalar_float(of, 2)
        q_strict = _scalar_float(of, 6)
        if q_main is not None:
            queue_entries.append((q_ts, q_main, q_strict))
    req_state = _parse_request_state(det[20][-1][1]) if 20 in det else None
    return {
        "pub_ns": pub_ns,
        "timestamp_ms": ts_ms,
        "sequence": seq,
        "request_id": _scalar_int(det, 5, 0),
        "continuous_fn_cnt": _scalar_int(det, 7, 0),
        "has_sent_assist_request": bool(_scalar_int(det, 21, 0)),
        "moving_cnt": _scalar_int(det, 22, 0),
        "queue": queue_entries,
        "req_state": req_state,
    }


def _parse_assist_request_msg(pub_ns: int, raw: bytes) -> Optional[Dict[str, Any]]:
    top = parse_proto_fields(unwrap_ros_proto(raw))
    if 9 in top:
        conn = parse_proto_fields(top[9][-1][1])
        return {
            "kind": "connect",
            "pub_ns": pub_ns,
            "timestamp_ms": _scalar_int(top, 4, 0),
            "sequence": _scalar_int(top, 7, 0),
            "request_id": _scalar_int(conn, 1, 0),
            "request_type": _scalar_int(conn, 2, 0),
            "is_already_in_assist_mode": bool(_scalar_int(conn, 10, 0)),
        }
    if 8 in top:
        return {
            "kind": "stuck_scene",
            "pub_ns": pub_ns,
            "timestamp_ms": _scalar_int(top, 4, 0),
            "sequence": _scalar_int(top, 7, 0),
        }
    return None


# ---------------------------------------------------------------------------
# Initial state reconstruction & frame alignment
# ---------------------------------------------------------------------------


def _reconstruct_initial_state(
    cycles: Sequence[Dict[str, Any]],
    planner_states: Sequence[Dict[str, Any]],
    connect_requests: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    c0 = cycles[0]
    c0_ts = int(c0["timestamp_ms"])

    # 1. Reconstruct initial main queue [(timestamp_ms, score), ...] before cycle 0
    state_ts_pool: List[Tuple[int, float]] = []
    seen_ts = set()
    for st in planner_states:
        for q_ts, q_score, _ in st["queue"]:
            if q_ts < c0_ts and (q_ts, round(q_score, 6)) not in seen_ts:
                seen_ts.add((q_ts, round(q_score, 6)))
                state_ts_pool.append((q_ts, q_score))

    c0_updated_queue = bool(c0["has_rules_executed"] and len(c0["fp_reasons"]) == 0)
    c0_pushed = bool(c0_updated_queue and c0["lik"] is not None)
    post_c0_scores = list(c0["queue_vals"])
    pre_c0_scores = post_c0_scores[1:] if c0_pushed else post_c0_scores

    used_pool = [False] * len(state_ts_pool)
    init_main_queue: List[List[float | int]] = []
    for idx, sc in enumerate(pre_c0_scores):
        matched_ts: Optional[int] = None
        for p_idx, (p_ts, p_sc) in enumerate(state_ts_pool):
            if not used_pool[p_idx] and abs(p_sc - sc) <= 1e-5:
                used_pool[p_idx] = True
                matched_ts = p_ts
                break
        if matched_ts is None:
            # If cycle 0 already ran UpdateModelPredictionHistory, surviving entries were within 12000ms.
            matched_ts = c0_ts - 1000 * (idx + 1) if c0_updated_queue else 0
        init_main_queue.append([int(matched_ts), float(sc)])

    # If cycle 0 ran UpdateModelPredictionHistory, also include any pre-cycle-0 state entries that expired at c0_ts
    if c0_updated_queue:
        for p_idx, (p_ts, p_sc) in enumerate(state_ts_pool):
            if not used_pool[p_idx] and (c0_ts - p_ts) > 12000 and len(init_main_queue) < 10:
                init_main_queue.append([int(p_ts), float(p_sc)])

    # 2. Reconstruct initial request_state &连续 FN counter before cycle 0
    first_rules_idx = next((i for i, c in enumerate(cycles) if c["has_rules_executed"]), None)
    reset_before_first_rules = False
    if first_rules_idx is not None:
        for c in cycles[:first_rules_idx]:
            st_code = c["entry_gate_status"]
            if st_code in (
                UnstuckStatus.OPS_REFUSED_SCENE,
                UnstuckStatus.MANUAL_DRIVING,
                UnstuckStatus.MRC_REACHED,
                UnstuckStatus.NORMAL_EXIT,
            ) or (st_code == UnstuckStatus.NOT_STATIONARY and c["moving_cnt"] >= 5):
                reset_before_first_rules = True

    init_seq_id = 0
    init_first_stuck_seq = -1
    init_tasks: Dict[str, Dict[str, int]] = {}
    if first_rules_idx is not None and not reset_before_first_rules:
        rs = cycles[first_rules_idx]["req_state"]
        if rs is not None:
            init_seq_id = int(rs["seq_id"]) - 1
            # CopyFrom(assist_request_state_) runs BEFORE PostRequest/AcknowledgeIfRequested!
            init_tasks = {
                k: dict(v)
                for k, v in rs["tasks"].items()
                if int(v.get("state", 0)) != 0 or int(v.get("last_changed_seq_id", 0)) != 0
            }
            fs = int(rs["first_stuck_detected_seq_id"])
            if fs >= 0 and fs < int(rs["seq_id"]):
                init_first_stuck_seq = fs

    # Initial continuous_fn_cycle_cnt before cycle 0
    init_cont_fn = 0
    if c0["has_rules_executed"]:
        rdec0 = c0["rule_decision"]
        c0_fn = int(c0["continuous_fn_cnt"])
        if rdec0 == 4:  # kHasActivateFN incremented it
            init_cont_fn = max(0, c0_fn - 1)
        elif rdec0 == 1:  # kAbort decremented it if > 0
            init_cont_fn = c0_fn + 1 if c0_fn > 0 else 0
        else:
            init_cont_fn = c0_fn
    elif planner_states and planner_states[0]["timestamp_ms"] <= c0_ts:
        init_cont_fn = int(planner_states[0]["continuous_fn_cnt"])

    # Initial request_id: if a kNewState connect request fired during the bag, req_id before that was r_id - 1
    init_request_id = 0
    if connect_requests:
        # Each kNewState increments request_id_ before posting
        init_request_id = max(0, int(connect_requests[0]["request_id"]) - 1)
    elif planner_states:
        init_request_id = int(planner_states[0]["request_id"])

    init_has_sent = False
    if planner_states and planner_states[0]["timestamp_ms"] <= c0_ts:
        init_has_sent = bool(planner_states[0]["has_sent_assist_request"])

    init_timer_start_ms = int(round(c0_ts - float(c0["timer_ms"])))

    return {
        "initial_main_queue": init_main_queue,
        "initial_strict_queue": [],
        "initial_seq_id": init_seq_id,
        "initial_first_stuck_detected_seq_id": init_first_stuck_seq,
        "initial_task_code_to_state": init_tasks,
        "initial_continuous_fn_cnt": init_cont_fn,
        "initial_request_id": init_request_id,
        "initial_has_sent_assist_request": init_has_sent,
        "initial_timer_start_ms": init_timer_start_ms,
        "initial_moving_cnt": max(0, int(c0["moving_cnt"]) - 1) if c0["moving_cnt"] > 0 else 0,
    }


# ---------------------------------------------------------------------------
# Public export API
# ---------------------------------------------------------------------------


def _build_voy_bag_env() -> Dict[str, str]:
    env = dict(os.environ)
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in env.get("PATH", "").split(":"):
        env["PATH"] = f"{local_bin}:{env.get('PATH', '')}".rstrip(":")

    extra_ld = [
        "/volume/home/workspace/voyager_deps/sdk/lib",
        "/opt/voy-sdk/lib",
        "/opt/ros/noetic/lib",
    ]
    cur_ld = [p for p in env.get("LD_LIBRARY_PATH", "").split(":") if p]
    for d in extra_ld:
        if os.path.isdir(d) and d not in cur_ld:
            cur_ld.insert(0, d)
    if cur_ld:
        env["LD_LIBRARY_PATH"] = ":".join(cur_ld)

    extra_py = [
        "/volume/home/workspace/voyager_deps/sdk/lib/python3/dist-packages",
        "/opt/ros/noetic/lib/python3/dist-packages",
    ]
    cur_py = [p for p in env.get("PYTHONPATH", "").split(":") if p]
    for d in extra_py:
        if os.path.isdir(d) and d not in cur_py:
            cur_py.insert(0, d)
    if cur_py:
        env["PYTHONPATH"] = ":".join(cur_py)
    return env


def download_road_scenario_bag(
    scenario_id: str,
    out_dir: Path,
    *,
    trip_id: Optional[str] = None,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    topics: Sequence[str] = LIGHTWEIGHT_DOWNLOAD_TOPICS,
) -> Path:
    """Download ONLY the 5 lightweight Onboard Stuck topics via ``voy-bag``."""
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_bag = out_dir / f"{scenario_id}.bag"
    if trip_id and start_ms is not None and end_ms is not None:
        cmd = [
            "voy-bag",
            "download",
            str(target_bag),
            "-t",
            str(trip_id),
            "-s",
            str(int(start_ms)),
            "-e",
            str(int(end_ms)),
            "-T",
            *topics,
        ]
    else:
        cmd = ["voy-bag", "download", str(target_bag), "-i", str(scenario_id), "-T", *topics]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=_build_voy_bag_env())
    if proc.returncode != 0:
        raise RuntimeError(
            f"voy-bag download failed for {scenario_id} (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    if target_bag.is_file():
        return target_bag
    bags = sorted(out_dir.rglob("*.bag"))
    if not bags:
        raise FileNotFoundError(f"voy-bag succeeded for {scenario_id} but no .bag found under {out_dir}")
    return bags[0]


def export_road_bag_to_npz(
    bag_path: os.PathLike | str,
    output_npz: os.PathLike | str,
    *,
    case_id: Optional[str] = None,
    trip_id: str = "",
    source_kind: str = "road",
    formal_window_ms: Optional[Tuple[int, int]] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Export a Voyager road (or sim) bag into a self-contained Enhanced Onboard Road NPZ."""
    bag = Path(bag_path).expanduser().resolve()
    out = Path(output_npz).expanduser().resolve()
    receipt_path = out.with_suffix(".EXPORT.json")
    if not bag.is_file():
        raise FileNotFoundError(f"Bag file not found: {bag}")
    if (out.exists() or receipt_path.exists()) and not overwrite:
        raise FileExistsError(f"Output already exists (pass overwrite=True): {out}")

    inferred_case_id = case_id or bag.parent.name or bag.stem

    bag_sha = hashlib.sha256()
    with bag.open("rb") as fp:
        for chunk in iter(lambda: fp.read(4 * 1024 * 1024), b""):
            bag_sha.update(chunk)
    source_bag_sha256 = bag_sha.hexdigest()

    td_frames: List[Dict[str, Any]] = []
    seed_td_frames: List[Dict[str, Any]] = []
    seen_seed_td_ts: set[int] = set()
    seed_by_seq: Dict[int, Dict[str, Any]] = {}
    ra_dbg_cycles: List[Dict[str, Any]] = []
    plan_dbg_cycles: List[Dict[str, Any]] = []
    planner_states: List[Dict[str, Any]] = []
    connect_requests: List[Dict[str, Any]] = []
    stuck_scene_request_seqs: set[int] = set()
    min_pub_ns: Optional[int] = None
    max_pub_ns: Optional[int] = None

    for topic, pub_ns, raw in iter_rosbag_messages(bag, ROAD_EXPORT_TOPICS):
        min_pub_ns = pub_ns if min_pub_ns is None else min(min_pub_ns, pub_ns)
        max_pub_ns = pub_ns if max_pub_ns is None else max(max_pub_ns, pub_ns)
        if topic == "/planning/remote_assist_model_debug":
            parsed = _parse_model_debug_msg(pub_ns, raw)
            if parsed is not None:
                td_frames.append(parsed)
        elif topic == "/planning/seed":
            s = _parse_seed_msg(pub_ns, raw, seen_seed_td_timestamps=seen_seed_td_ts)
            if s.get("seed_td_frame") is not None:
                seed_td_frames.append(s["seed_td_frame"])
            seed_by_seq[s["sequence"]] = s
        elif topic == "/planning/remote_assist_debug":
            top = parse_proto_fields(unwrap_ros_proto(raw))
            ts_ms = _scalar_int(top, 1, 0)
            seq = _scalar_int(top, 2, 0)
            sched_blob = top[5][-1][1] if 5 in top else None
            if 7 in top:
                ra_dbg_cycles.append(
                    _parse_ego_stuck_debug(ts_ms, seq, pub_ns, top[7][-1][1], sched_blob)
                )
        elif topic == "/planning/planning_debug":
            top = parse_proto_fields(unwrap_ros_proto(raw))
            ts_ms = _scalar_int(top, 1, 0)
            seq = _scalar_int(top, 2, 0)
            if 21 in top:
                br_dbg = parse_proto_fields(top[21][-1][1])
                if 18 in br_dbg:
                    plan_dbg_cycles.append(
                        _parse_ego_stuck_debug(ts_ms, seq, pub_ns, br_dbg[18][-1][1], None)
                    )
        elif topic == "/planner/state":
            st = _parse_planner_state_msg(pub_ns, raw)
            if st is not None:
                planner_states.append(st)
        elif topic == "/planning/assist_request":
            req = _parse_assist_request_msg(pub_ns, raw)
            if req is not None:
                if req.get("kind") == "connect":
                    connect_requests.append(req)
                elif req.get("kind") == "stuck_scene":
                    stuck_scene_request_seqs.add(int(req["sequence"]))

    cycles = ra_dbg_cycles if ra_dbg_cycles else plan_dbg_cycles
    debug_topic_used = (
        "/planning/remote_assist_debug" if ra_dbg_cycles else "/planning/planning_debug"
    )
    if not cycles:
        raise ValueError(f"Bag {bag} contains neither /planning/remote_assist_debug nor /planning/planning_debug")

    if not td_frames and seed_td_frames:
        td_frames = seed_td_frames

    td_frames.sort(key=lambda x: (x["sequence"], x["pub_ns"]))
    cycles.sort(key=lambda x: (x["sequence"], x["pub_ns"]))
    planner_states.sort(key=lambda x: (x["timestamp_ms"], x["pub_ns"]))
    connect_requests.sort(key=lambda x: (x["timestamp_ms"], x["pub_ns"]))

    # Validate uniform TensorDict keys & shapes across all M frames (gracefully allow M == 0)
    if td_frames:
        canonical_keys = sorted(td_frames[0]["tensors"].keys())
        canonical_shapes = {k: td_frames[0]["tensors"][k].shape for k in canonical_keys}
        for idx, frame in enumerate(td_frames):
            if sorted(frame["tensors"].keys()) != canonical_keys:
                raise ValueError(f"TensorDict key mismatch at frame {idx}")
            for k in canonical_keys:
                if frame["tensors"][k].shape != canonical_shapes[k]:
                    raise ValueError(f"TensorDict shape mismatch for {k} at frame {idx}")

        tensor_arrays = {
            k: np.stack([f["tensors"][k] for f in td_frames], axis=0) for k in canonical_keys
        }
        td_timestamps = np.asarray([f["timestamp_ms"] for f in td_frames], dtype=np.int64)
        td_pub_ns = np.asarray([f["pub_ns"] for f in td_frames], dtype=np.int64)
        td_seq = np.asarray([f["sequence"] for f in td_frames], dtype=np.int64)
    else:
        canonical_keys = []
        tensor_arrays = {}
        td_timestamps = np.zeros(0, dtype=np.int64)
        td_pub_ns = np.zeros(0, dtype=np.int64)
        td_seq = np.zeros(0, dtype=np.int64)

    # Link every 10Hz cycle's consumed model output to its exact TensorDict frame index
    n_cycles = len(cycles)
    consumed_frame_index = np.full(n_cycles, -1, dtype=np.int32)
    recorded_main_score = np.full(n_cycles, np.nan, dtype=np.float64)
    recorded_strict_score = np.full(n_cycles, np.nan, dtype=np.float64)
    unmatched_score_cycles: List[int] = []

    for c_idx, cyc in enumerate(cycles):
        seq = cyc["sequence"]
        seed_info = seed_by_seq.get(seq)
        main_sc = cyc["lik"]
        if main_sc is None and seed_info is not None:
            main_sc = seed_info["main_score"]
        strict_sc = cyc["strict_lik"]
        if strict_sc is None and seed_info is not None:
            strict_sc = seed_info["strict_score"]

        if main_sc is not None:
            recorded_main_score[c_idx] = float(main_sc)
            if strict_sc is not None:
                recorded_strict_score[c_idx] = float(strict_sc)

            ref_ts = (
                seed_info["prev_ts"]
                if (seed_info is not None and seed_info["prev_ts"] is not None)
                else cyc["timestamp_ms"]
            )
            best_idx = -1
            best_key = (999999, 999999)
            for f_idx, f_ts in enumerate(td_timestamps):
                delta = int(f_ts) - int(ref_ts)
                if -10 <= delta <= 80:
                    # Prefer 0 <= f_ts - prev_ts <= 5 (exact RemoteAssistModelVNode callback delta)
                    penalty = 0 if 0 <= delta <= 5 else 1
                    cand_key = (penalty, abs(delta))
                    if cand_key < best_key:
                        best_key = cand_key
                        best_idx = f_idx
            if best_idx >= 0:
                consumed_frame_index[c_idx] = best_idx
            else:
                unmatched_score_cycles.append(int(seq))

    # Build per-cycle rule & gate arrays
    fp_reasons_per_cycle: List[List[int]] = []
    fn_non_model_per_cycle: List[List[List[int]]] = []
    has_voluntary_modes = np.zeros(n_cycles, dtype=np.bool_)
    is_voluntary_fail = np.zeros(n_cycles, dtype=np.bool_)

    for c_idx, cyc in enumerate(cycles):
        fp_reasons_per_cycle.append([int(r) for r in cyc["fp_reasons"]])
        fn_items: List[List[int]] = []
        rs_tasks = (cyc["req_state"] or {}).get("tasks", {})
        for r in cyc["fn_reasons"]:
            r_int = int(r)
            if r_int == int(AssistModelProcessReason.ASSIST_STUCK_MODEL):
                continue
            if r_int == int(AssistModelProcessReason.SPECIAL_STUCK_SCENE):
                t_code = int(cyc["special_task_code"])
            else:
                # Check if task_code_to_state recorded a specific task code for this reason
                matched_tc = None
                for tc_str, tinfo in rs_tasks.items():
                    if int(tinfo.get("process_reason", 0)) == r_int:
                        matched_tc = int(tc_str)
                        break
                t_code = (
                    matched_tc
                    if matched_tc is not None
                    else int(DEFAULT_FN_REASON_TASK_CODE.get(r_int, TaskCode.STUCK_OTHER))
                )
            fn_items.append([r_int, t_code])
        fn_non_model_per_cycle.append(fn_items)

        non_vol = int(cyc["non_vol"])
        is_voluntary_fail[c_idx] = non_vol == 2
        if non_vol == 0:
            has_voluntary_modes[c_idx] = float(cyc["timer_ms"]) > 1000.0
        elif non_vol == 1:
            has_voluntary_modes[c_idx] = False
        else:
            # When UnstuckFail (2) ran, IsVoluntaryUndetectedStuckScene was False
            has_voluntary_modes[c_idx] = float(cyc["timer_ms"]) > 1000.0

    initial_state = _reconstruct_initial_state(cycles, planner_states, connect_requests)

    if formal_window_ms is not None:
        fw_start, fw_end = int(formal_window_ms[0]), int(formal_window_ms[1])
        formal_window_arr = np.asarray([fw_start, fw_end], dtype=np.int64)
        formal_start_idx = next(
            (i for i, c in enumerate(cycles) if int(c["timestamp_ms"]) >= fw_start),
            0,
        )
        formal_cycles = cycles[formal_start_idx:] if formal_start_idx < len(cycles) else cycles
        formal_reqs = [
            r for r in connect_requests if int(r["timestamp_ms"]) >= int(formal_cycles[0]["timestamp_ms"])
        ]
        formal_initial_state = _reconstruct_initial_state(formal_cycles, planner_states, formal_reqs)
    else:
        formal_window_arr = np.asarray([-1, -1], dtype=np.int64)
        formal_initial_state = initial_state

    scheduler_session_blocked = np.asarray(
        [
            bool(seed_by_seq.get(int(c["sequence"]), {}).get("session_blocks_connect", False))
            or (int(c["sequence"]) in stuck_scene_request_seqs)
            for c in cycles
        ],
        dtype=np.bool_,
    )

    gt_queue_top3 = np.full((n_cycles, 3), np.nan, dtype=np.float64)
    gt_queue_len = np.zeros(n_cycles, dtype=np.int32)
    for c_idx, cyc in enumerate(cycles):
        qv = cyc["queue_vals"]
        gt_queue_len[c_idx] = len(qv)
        for j in range(min(3, len(qv))):
            gt_queue_top3[c_idx, j] = qv[j]

    core_planner_status = np.asarray(
        [
            int(UnstuckStatus.CORE_PLANNER_DETECT)
            if c["unstuck_status"] == int(UnstuckStatus.CORE_PLANNER_DETECT)
            else 0
            for c in cycles
        ],
        dtype=np.int32,
    )
    flag_or_omni_status = np.asarray(
        [
            int(c["unstuck_status"])
            if c["unstuck_status"] in (int(UnstuckStatus.FLAG_DISABLE), int(UnstuckStatus.OMNI_PERF_DISABLE))
            else 0
            for c in cycles
        ],
        dtype=np.int32,
    )

    payload: Dict[str, Any] = dict(tensor_arrays)
    payload.update(
        npz_schema=np.array(ENHANCED_NPZ_SCHEMA),
        npz_tier=np.array(TIER_LAYER2_ROAD_10HZ),
        issue_id=np.array(inferred_case_id),
        trip_id=np.array(trip_id),
        source_kind=np.array(source_kind),
        source_bag_sha256=np.array(source_bag_sha256),
        start_time=np.array(min_pub_ns or 0, dtype=np.int64),
        end_time=np.array(max_pub_ns or 0, dtype=np.int64),
        formal_window_ms=formal_window_arr,
        formal_initial_state_json=np.array(json.dumps(formal_initial_state, separators=(",", ":"))),
        tensor_dict_timestamp=td_timestamps,
        producer_publication_timestamp_ns=td_pub_ns,
        producer_sequence=td_seq,
        cycle_timestamp_ms=np.asarray([c["timestamp_ms"] for c in cycles], dtype=np.int64),
        cycle_sequence=np.asarray([c["sequence"] for c in cycles], dtype=np.int64),
        consumed_frame_index=consumed_frame_index,
        recorded_main_score=recorded_main_score,
        recorded_strict_score=recorded_strict_score,
        entry_gate_status=np.asarray([c["entry_gate_status"] for c in cycles], dtype=np.int32),
        ego_moving_fast=np.asarray([c["moving_cnt"] >= 5 for c in cycles], dtype=np.bool_),
        already_in_assist_status=np.asarray([c["already_in_assist_status"] for c in cycles], dtype=np.int32),
        non_voluntary_unstuck_reason=np.asarray([c["non_vol"] for c in cycles], dtype=np.int32),
        has_voluntary_unstuck_modes=has_voluntary_modes,
        is_voluntary_unstuck_fail=is_voluntary_fail,
        stationary_cycle_count=np.asarray([c["stationary_cycle_count"] for c in cycles], dtype=np.int64),
        stuck_threshold=np.asarray([c["stuck_threshold"] for c in cycles], dtype=np.float64),
        is_vlm_block=np.asarray([c["vlm_block"] for c in cycles], dtype=np.bool_),
        core_planner_status=core_planner_status,
        flag_or_omni_status=flag_or_omni_status,
        special_stuck_task_code=np.asarray([c["special_task_code"] for c in cycles], dtype=np.int32),
        scheduler_session_blocked=scheduler_session_blocked,
        fp_reasons_json=np.array(json.dumps(fp_reasons_per_cycle, separators=(",", ":"))),
        fn_non_model_reasons_json=np.array(json.dumps(fn_non_model_per_cycle, separators=(",", ":"))),
        initial_state_json=np.array(json.dumps(initial_state, separators=(",", ":"))),
        gt_unstuck_status=np.asarray([c["unstuck_status"] for c in cycles], dtype=np.int32),
        gt_is_stuck_by_model=np.asarray([c["by_model"] for c in cycles], dtype=np.bool_),
        gt_is_strict_stuck_by_model=np.asarray([c["by_strict"] for c in cycles], dtype=np.bool_),
        gt_rule_decision=np.asarray([c["rule_decision"] for c in cycles], dtype=np.int32),
        gt_process_reason=np.asarray([c["proc_reason"] for c in cycles], dtype=np.int32),
        gt_timer_elapsed_ms=np.asarray([c["timer_ms"] for c in cycles], dtype=np.float64),
        gt_continuous_fn_cnt=np.asarray([c["continuous_fn_cnt"] for c in cycles], dtype=np.int32),
        gt_queue_len=gt_queue_len,
        gt_queue_top3=gt_queue_top3,
        gt_connect_request_ts=np.asarray([r["timestamp_ms"] for r in connect_requests], dtype=np.int64),
        gt_connect_request_id=np.asarray([r["request_id"] for r in connect_requests], dtype=np.int64),
        gt_connect_request_type=np.asarray([r["request_type"] for r in connect_requests], dtype=np.int32),
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_npz = out.with_suffix(".tmp.npz")
    with tmp_npz.open("wb") as fp:
        np.savez_compressed(fp, **payload)
    tmp_npz.replace(out)

    npz_bytes = out.stat().st_size
    npz_sha256 = hashlib.sha256(out.read_bytes()).hexdigest()
    receipt = {
        "schema": ENHANCED_NPZ_SCHEMA,
        "case_id": inferred_case_id,
        "trip_id": trip_id,
        "source_kind": source_kind,
        "source_bag_path": str(bag),
        "source_bag_bytes": bag.stat().st_size,
        "source_bag_sha256": source_bag_sha256,
        "debug_topic_used": debug_topic_used,
        "npz_path": str(out),
        "npz_bytes": npz_bytes,
        "npz_sha256": npz_sha256,
        "tensor_dict_frames": len(td_frames),
        "tensor_dict_keys": len(canonical_keys),
        "speed_cycles_10hz": n_cycles,
        "consumed_score_cycles": int(np.sum(consumed_frame_index >= 0)),
        "unmatched_score_cycles": unmatched_score_cycles,
        "gt_model_request_cycles": int(np.sum(payload["gt_unstuck_status"] == int(UnstuckStatus.MODEL_REQUEST))),
        "gt_connect_requests": len(connect_requests),
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt
