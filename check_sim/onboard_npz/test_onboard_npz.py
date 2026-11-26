"""Unit and regression tests for check_sim.onboard_npz (Layer 1 + Layer 2 + ROS1 bag exporter)."""

from __future__ import annotations

import json
from pathlib import Path
import struct
from typing import Dict, List, Tuple

import numpy as np
import pytest

from check_sim.onboard_npz import (
    ENHANCED_NPZ_SCHEMA,
    TIER_LAYER1_CROPPED,
    TIER_LAYER2_ROAD_10HZ,
    AssistModelProcessReason,
    FrameScoreBatch,
    OnboardDetectorConfig,
    OnboardModelRunner,
    RuleDecision,
    UnstuckStatus,
    evaluate_cropped_npz,
    export_road_bag_to_npz,
    infer_npz_file,
    replay_enhanced_road_npz,
)


# ---------------------------------------------------------------------------
# Minimal Protobuf + ROSBAG V2.0 builders for deterministic self-contained tests
# ---------------------------------------------------------------------------


def _varint_bytes(val: int) -> bytes:
    if val < 0:
        val += 1 << 64
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_varint(fn: int, val: int) -> bytes:
    return _varint_bytes((fn << 3) | 0) + _varint_bytes(val)


def _pb_f32(fn: int, val: float) -> bytes:
    return _varint_bytes((fn << 3) | 5) + struct.pack("<f", val)


def _pb_f64(fn: int, val: float) -> bytes:
    return _varint_bytes((fn << 3) | 1) + struct.pack("<d", val)


def _pb_bytes(fn: int, payload: bytes) -> bytes:
    return _varint_bytes((fn << 3) | 2) + _varint_bytes(len(payload)) + payload


def _ros_proto_wrap(pb_payload: bytes) -> bytes:
    return struct.pack("<I", len(pb_payload)) + pb_payload


def _encode_ra_tensor(shape: Tuple[int, ...], arr: np.ndarray) -> bytes:
    msg = bytearray()
    for d in shape:
        msg += _pb_varint(1, d)
    if arr.dtype == np.float32:
        msg += _pb_bytes(3, arr.astype("<f4").tobytes())
    else:
        for v in arr.reshape(-1).tolist():
            msg += _pb_varint(2, int(v))
    return bytes(msg)


def _write_minimal_rosbag(path: Path, records: List[Tuple[str, int, bytes]]) -> None:
    def bag_hdr(fields: Dict[bytes, bytes]) -> bytes:
        parts = []
        for k, v in fields.items():
            kv = k + b"=" + v
            parts.append(struct.pack("<I", len(kv)) + kv)
        body = b"".join(parts)
        return struct.pack("<I", len(body)) + body

    topics = sorted({t for t, _, _ in records})
    conn_map = {t: idx + 1 for idx, t in enumerate(topics)}
    chunk_buf = bytearray()
    for t, cid in conn_map.items():
        h = bag_hdr({b"op": b"\x07", b"conn": struct.pack("<I", cid), b"topic": t.encode()})
        d = bag_hdr({b"topic": t.encode(), b"type": b"proto_msg/Test", b"md5sum": b"*"})
        chunk_buf += h + struct.pack("<I", len(d)) + d

    for t, pub_ns, raw in records:
        sec = pub_ns // 1_000_000_000
        nsec = pub_ns % 1_000_000_000
        h = bag_hdr({
            b"op": b"\x02",
            b"conn": struct.pack("<I", conn_map[t]),
            b"time": struct.pack("<II", sec, nsec),
        })
        chunk_buf += h + struct.pack("<I", len(raw)) + raw

    with path.open("wb") as fp:
        fp.write(b"#ROSBAG V2.0\n")
        ch = bag_hdr({
            b"op": b"\x05",
            b"compression": b"bz2",
            b"size": struct.pack("<I", len(chunk_buf)),
        })
        comp = bz2.compress(bytes(chunk_buf))
        fp.write(ch + struct.pack("<I", len(comp)) + comp)


import bz2  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_layer1_cropped_npz_queue_expiration_and_freshness() -> None:
    # Frame 0 & 1 are >12s before Frame 2..4; Frame 2..4 are 500ms apart and >= 0.5 -> triggers at Frame 4
    npz_data = {
        "issue_id": np.array("cn_layer1_case"),
        "tensor_dict_timestamp": np.array([1_000, 2_000, 20_000, 20_500, 21_000], dtype=np.int64),
        "ego": np.zeros((5, 80, 9), dtype=np.float32),
    }
    batch = FrameScoreBatch(
        main_scores=np.array([0.9, 0.9, 0.61, 0.62, 0.63], dtype=np.float64),
        strict_scores=None,
        backend="mock",
        device="cpu",
        model_path=None,
        model_sha256=None,
        input_names=("ego",),
        output_names=("stuck_score",),
    )
    res = evaluate_cropped_npz(npz_data, batch, case_id="cn_layer1_case", npz_path="/tmp/mock.npz")
    assert res.npz_tier == TIER_LAYER1_CROPPED
    assert res.triggered_request is True
    assert res.first_request_cycle == 4
    assert res.first_request_timestamp_ms == 21_000


def test_layer1_cropped_npz_stale_front_does_not_trigger() -> None:
    # 3 positives, so each step is >12s apart -> earlier predictions expire before 3 accumulate
    npz_data = {
        "tensor_dict_timestamp": np.array([1_000, 14_000, 27_000], dtype=np.int64),
    }
    batch = FrameScoreBatch(
        main_scores=np.array([0.8, 0.8, 0.8], dtype=np.float64),
        strict_scores=None,
        backend="mock",
        device="cpu",
        model_path=None,
        model_sha256=None,
        input_names=(),
        output_names=("stuck_score",),
    )
    res = evaluate_cropped_npz(npz_data, batch, case_id="cn_stale", npz_path="/tmp/stale.npz")
    assert res.triggered_request is False


def _make_synthetic_enhanced_npz() -> Dict[str, np.ndarray]:
    """Construct a 6-cycle 10Hz road timeline exercising FP queue suppression + MODEL_REQUEST + hold."""
    # Cycles:
    # 0 (t=10000): FP_QUEUING(15) active, score=0.80 arrives -> MUST NOT enter queue! Unstuck=MODEL_FP(3)
    # 1 (t=10100): no FP, score=0.70 arrives -> queue=[0.70], Unstuck=UNSTUCK_UNDEFIEND(0)
    # 2 (t=10200): no FP, score=0.75 arrives -> queue=[0.75, 0.70], Unstuck=UNSTUCK_UNDEFIEND(0)
    # 3 (t=10300): FP_CROSSWALK(6) + FN_SELECTION(19):
    #              FP group runs BEFORE FN_SELECTION discount -> has_fp_activation=True -> queue NOT updated!
    #              Arbitrator discounts FP_CROSSWALK -> num_fp=0 -> kHasActivateFN -> RULE_FN_DETECT(9)
    # 4 (t=10400): no FP, score=0.80 arrives -> queue=[0.80, 0.75, 0.70] -> 3>=0.5! MODEL_REQUEST(5)!
    # 5 (t=11500, >1000ms after timer restart at 10400): no FP, score=0.85 arrives ->
    #              queue=[0.85, 0.80, 0.75, 0.70] -> by_model=True, held within 300 cycles -> UNSTUCK_UNDEFIEND(0)!
    return {
        "npz_schema": np.array(ENHANCED_NPZ_SCHEMA),
        "npz_tier": np.array(TIER_LAYER2_ROAD_10HZ),
        "issue_id": np.array("cn_synth_10hz"),
        "tensor_dict_timestamp": np.array([10000, 10100, 10200, 10300, 10400, 11500], dtype=np.int64),
        "cycle_timestamp_ms": np.array([10000, 10100, 10200, 10300, 10400, 11500], dtype=np.int64),
        "cycle_sequence": np.array([100, 101, 102, 103, 104, 105], dtype=np.int64),
        "consumed_frame_index": np.array([0, 1, 2, 3, 4, 5], dtype=np.int32),
        "recorded_main_score": np.array([0.80, 0.70, 0.75, 0.90, 0.80, 0.85], dtype=np.float64),
        "recorded_strict_score": np.full(6, np.nan, dtype=np.float64),
        "entry_gate_status": np.zeros(6, dtype=np.int32),
        "ego_moving_fast": np.zeros(6, dtype=np.bool_),
        "already_in_assist_status": np.zeros(6, dtype=np.int32),
        "non_voluntary_unstuck_reason": np.ones(6, dtype=np.int32),  # UndetectedStuckScene -> not voluntary
        "has_voluntary_unstuck_modes": np.zeros(6, dtype=np.bool_),
        "is_voluntary_unstuck_fail": np.zeros(6, dtype=np.bool_),
        "stationary_cycle_count": np.array([20, 21, 22, 23, 24, 25], dtype=np.int64),
        "stuck_threshold": np.full(6, 0.5, dtype=np.float64),
        "is_vlm_block": np.zeros(6, dtype=np.bool_),
        "core_planner_status": np.zeros(6, dtype=np.int32),
        "flag_or_omni_status": np.zeros(6, dtype=np.int32),
        "special_stuck_task_code": np.full(6, 1106, dtype=np.int32),
        "fp_reasons_json": np.array(
            json.dumps([[int(AssistModelProcessReason.FP_QUEUING)], [], [], [int(AssistModelProcessReason.FP_CROSSWALK)], [], []])
        ),
        "fn_non_model_reasons_json": np.array(
            json.dumps([[], [], [], [[int(AssistModelProcessReason.FN_SELECTION), 1100]], [], []])
        ),
        "initial_state_json": np.array(
            json.dumps({
                "initial_main_queue": [],
                "initial_strict_queue": [],
                "initial_seq_id": 10,
                "initial_first_stuck_detected_seq_id": -1,
                "initial_task_code_to_state": {},
                "initial_continuous_fn_cnt": 0,
                "initial_request_id": 0,
                "initial_has_sent_assist_request": False,
                "initial_timer_start_ms": 8000,
            })
        ),
        "gt_unstuck_status": np.array(
            [
                UnstuckStatus.MODEL_FP,
                UnstuckStatus.UNSTUCK_UNDEFIEND,
                UnstuckStatus.UNSTUCK_UNDEFIEND,
                UnstuckStatus.RULE_FN_DETECT,
                UnstuckStatus.MODEL_REQUEST,
                UnstuckStatus.UNSTUCK_UNDEFIEND,
            ],
            dtype=np.int32,
        ),
        "gt_is_stuck_by_model": np.array([False, False, False, False, True, True], dtype=np.bool_),
        "gt_rule_decision": np.array(
            [
                RuleDecision.kAbort,
                RuleDecision.kNone,
                RuleDecision.kNone,
                RuleDecision.kHasActivateFN,
                RuleDecision.kModelDetected,
                RuleDecision.kModelDetected,
            ],
            dtype=np.int32,
        ),
        "gt_queue_len": np.array([0, 1, 2, 2, 3, 4], dtype=np.int32),
        "gt_queue_top3": np.array(
            [
                [np.nan, np.nan, np.nan],
                [0.70, np.nan, np.nan],
                [0.75, 0.70, np.nan],
                [0.75, 0.70, np.nan],
                [0.80, 0.75, 0.70],
                [0.85, 0.80, 0.75],
            ],
            dtype=np.float64,
        ),
    }


def test_layer2_10hz_fp_queue_suppression_and_parity() -> None:
    npz_data = _make_synthetic_enhanced_npz()
    res_full = replay_enhanced_road_npz(
        npz_data,
        None,
        case_id="cn_synth_10hz",
        npz_path="/tmp/synth.npz",
        mode="onboard_full",
        verify_parity=True,
    )
    assert res_full.parity is not None
    assert res_full.parity.passed is True, res_full.parity.mismatches
    assert res_full.first_request_cycle == 4
    assert res_full.triggered_by_model is True

    # In model_only mode (rules disabled), FP suppression at cycle 0 & 3 is disabled -> triggers at cycle 2!
    res_model_only = replay_enhanced_road_npz(
        npz_data,
        None,
        case_id="cn_synth_10hz",
        npz_path="/tmp/synth.npz",
        mode="model_only",
    )
    assert res_model_only.triggered_request is True
    assert res_model_only.first_request_cycle == 2


def test_rosbag_bz2_export_and_cli_roundtrip(tmp_path: Path) -> None:
    bag_path = tmp_path / "synthetic_road.bag"
    records: List[Tuple[str, int, bytes]] = []

    for i in range(3):
        ts_ms = 50_000 + i * 100
        pub_ns = ts_ms * 1_000_000
        # 1. /planning/remote_assist_model_debug
        e1 = _pb_bytes(1, b"ego") + _pb_bytes(2, _encode_ra_tensor((1, 4), np.ones((1, 4), dtype=np.float32) * i))
        e2 = _pb_bytes(1, b"map_type") + _pb_bytes(2, _encode_ra_tensor((1,), np.array([2], dtype=np.int32)))
        md = _pb_varint(1, ts_ms) + _pb_varint(2, 10 + i) + _pb_bytes(8, _pb_bytes(1, e1) + _pb_bytes(1, e2))
        records.append(("/planning/remote_assist_model_debug", pub_ns, _ros_proto_wrap(md)))

        # 2. /planning/seed
        mout = _pb_varint(1, ts_ms) + _pb_f32(2, 0.65)
        aseed = _pb_bytes(9, mout)
        bseed = _pb_bytes(22, aseed)
        seed = _pb_varint(1, ts_ms) + _pb_varint(13, 100 + i) + _pb_bytes(9, bseed)
        records.append(("/planning/seed", pub_ns + 1000, _ros_proto_wrap(seed)))

        # 3. /planning/remote_assist_debug
        is_trig = i == 2
        u_stat = int(UnstuckStatus.MODEL_REQUEST if is_trig else UnstuckStatus.UNSTUCK_UNDEFIEND)
        r_dec = int(RuleDecision.kModelDetected if is_trig else RuleDecision.kNone)
        rdbg = _pb_varint(1, r_dec) + (_pb_varint(27, int(AssistModelProcessReason.ASSIST_STUCK_MODEL)) if is_trig else b"")
        rstate = _pb_varint(1, 1 + i) + (_pb_varint(3, 3) if is_trig else b"")
        q_bytes = b"".join(_pb_f64(32, 0.65) for _ in range(i + 1))
        esd = (
            _pb_varint(5, u_stat)
            + _pb_varint(6, int(is_trig))
            + _pb_varint(8, int(NonVoluntaryUnstuckReason_Undetected := 1))
            + _pb_f64(10, 0.5)
            + _pb_varint(13, 30 + i)
            + _pb_bytes(22, rdbg)
            + q_bytes
            + _pb_f64(34, 0.65)
            + _pb_bytes(36, rstate)
            + _pb_f64(39, 2500.0 + i * 100)
        )
        rad = _pb_varint(1, ts_ms) + _pb_varint(2, 100 + i) + _pb_bytes(7, esd)
        records.append(("/planning/remote_assist_debug", pub_ns + 2000, _ros_proto_wrap(rad)))

    _write_minimal_rosbag(bag_path, records)
    out_npz = tmp_path / "exported_road.npz"
    receipt = export_road_bag_to_npz(bag_path, out_npz, case_id="cn_roundtrip")
    assert receipt["tensor_dict_frames"] == 3
    assert receipt["tensor_dict_keys"] == 2
    assert receipt["unmatched_score_cycles"] == []
    assert out_npz.is_file()

    with OnboardModelRunner("recorded") as runner:
        res = infer_npz_file(out_npz, runner, mode="onboard_full", verify_parity=True)
    assert res.parity is not None and res.parity.passed is True
    assert res.triggered_request is True
    assert res.first_request_cycle == 2


def test_scheduler_session_gating_and_formal_window() -> None:
    npz_data = _make_synthetic_enhanced_npz()
    # Suppose cycle 4 (t=10400) has an open directional RequestSession blocking AssistChannelConnectRequest:
    npz_data["scheduler_session_blocked"] = np.array([False, False, False, False, True, False], dtype=np.bool_)
    npz_data["formal_window_ms"] = np.array([10300, 12000], dtype=np.int64)
    res_blocked = replay_enhanced_road_npz(
        npz_data,
        None,
        case_id="cn_sched_blocked",
        npz_path="/tmp/sched.npz",
        mode="onboard_full",
        verify_parity=True,
    )
    # Detector internal EgoStuckDebug parity still 100% passes (PostRequest happened before scheduler!)
    assert res_blocked.parity is not None and res_blocked.parity.passed is True
    # Outer scheduler suppressed the emitted request on cycle 4!
    assert len(res_blocked.emitted_requests) == 1
    assert res_blocked.emitted_requests[0]["scheduled"] is False
    assert res_blocked.triggered_request is False
    assert res_blocked.triggered_in_formal_window is False

    # Now unblock scheduler, but set formal_window_ms AFTER t=10400 ([10600, 12000])
    npz_data["scheduler_session_blocked"] = np.zeros(6, dtype=np.bool_)
    npz_data["formal_window_ms"] = np.array([10600, 12000], dtype=np.int64)
    res_outside = replay_enhanced_road_npz(
        npz_data,
        None,
        case_id="cn_outside_fw",
        npz_path="/tmp/fw.npz",
        mode="onboard_full",
    )
    assert res_outside.triggered_request is True
    assert res_outside.triggered_in_formal_window is False


def test_zero_tensor_dict_bag_export_and_1030_metrics(tmp_path: Path) -> None:
    from check_sim.onboard_npz import compute_1030_metrics, compute_paired_diff

    # 1. Bag with 0 TensorDict dumps (e.g. CZ_TL / ManualTrigger clip) must export & replay cleanly
    bag_path = tmp_path / "zero_td.bag"
    records: List[Tuple[str, int, bytes]] = []
    for i in range(2):
        ts_ms = 60_000 + i * 100
        pub_ns = ts_ms * 1_000_000
        is_trig = i == 1
        u_stat = int(UnstuckStatus.MODEL_REQUEST if is_trig else UnstuckStatus.UNSTUCK_UNDEFIEND)
        r_dec = int(RuleDecision.kRequestImmediately if is_trig else RuleDecision.kNone)
        rdbg = _pb_varint(1, r_dec) + (
            _pb_varint(27, int(AssistModelProcessReason.FN_RA_CZ_TRAFFIC_LIGHT)) if is_trig else b""
        )
        rstate = _pb_varint(1, 1 + i) + (_pb_varint(3, 2) if is_trig else b"")
        esd = (
            _pb_varint(5, u_stat)
            + _pb_varint(8, 1)
            + _pb_f64(10, 0.5)
            + _pb_varint(13, 10 + i)
            + _pb_bytes(22, rdbg)
            + _pb_bytes(36, rstate)
            + _pb_f64(39, 1500.0)
        )
        rad = _pb_varint(1, ts_ms) + _pb_varint(2, 200 + i) + _pb_bytes(7, esd)
        records.append(("/planning/remote_assist_debug", pub_ns, _ros_proto_wrap(rad)))
    _write_minimal_rosbag(bag_path, records)

    out_npz = tmp_path / "zero_td.npz"
    receipt = export_road_bag_to_npz(
        bag_path,
        out_npz,
        case_id="cn_zero_td",
        formal_window_ms=(60_000, 61_000),
    )
    assert receipt["tensor_dict_frames"] == 0
    with OnboardModelRunner("recorded") as runner:
        res = infer_npz_file(out_npz, runner, mode="onboard_full", verify_parity=True)
    assert res.parity is not None and res.parity.passed is True
    assert res.triggered_in_formal_window is True
    assert res.emitted_requests[0]["request_type"] == "kCZTrafficLightRequest"

    # 2. Verify SQL-checked 1030 TE7 P/R and paired transitions
    rows = [
        {"issue_id": "cn1", "label": "成功"},
        {"issue_id": "cn2", "label": "正确触发"},
        {"issue_id": "cn3", "label": "误触发"},
        {"issue_id": "cn4", "label": "无需协助"},
    ]
    base_dec = {"cn1": True, "cn2": True, "cn3": True, "cn4": None}
    feat_dec = {"cn1": True, "cn2": False, "cn3": False, "cn4": None}
    m_base = compute_1030_metrics(rows, base_dec)
    assert m_base["unified_binary"]["TP"] == 2
    assert m_base["unified_binary"]["FP"] == 1
    assert m_base["strict_good_p"]["P_numerator"] == 1
    assert m_base["unified_binary"]["R_full_denominator"] == 3
    diff = compute_paired_diff(rows, base_dec, feat_dec)
    assert diff["transitions"]["tp_lost"]["count"] == 1
    assert diff["transitions"]["fp_removed"]["count"] == 1


def test_counterfactual_assist_modes_all_vs_light_only_vs_strict() -> None:
    npz_data = _make_synthetic_enhanced_npz()
    # Suppose cycles 2..5 had ALREADY_IN_WAYPOINT_ASSIST(10) on the road car (from an earlier Q2 trigger)
    # while ego remained physically stationary (entry_gate_status == 0):
    npz_data["already_in_assist_status"] = np.array(
        [0, 0, int(UnstuckStatus.ALREADY_IN_WAYPOINT_ASSIST), int(UnstuckStatus.ALREADY_IN_WAYPOINT_ASSIST), int(UnstuckStatus.ALREADY_IN_WAYPOINT_ASSIST), int(UnstuckStatus.ALREADY_IN_WAYPOINT_ASSIST)],
        dtype=np.int32,
    )
    # 1. Strict road mode inherits ALREADY_IN_WAYPOINT_ASSIST -> blocks model trigger on cycle 4!
    res_strict = replay_enhanced_road_npz(
        npz_data,
        None,
        case_id="cn_cf_strict",
        npz_path="/tmp/cf.npz",
        mode="onboard_strict_road",
    )
    assert res_strict.triggered_request is False

    # 2. Variant A (onboard_light_counterfactual) only unmasks LIGHT_ASSIST(6), NOT WAYPOINT_ASSIST(10) -> still False!
    res_light = replay_enhanced_road_npz(
        npz_data,
        None,
        case_id="cn_cf_light",
        npz_path="/tmp/cf.npz",
        mode="onboard_light_counterfactual",
    )
    assert res_light.triggered_request is False

    # 3. Variant B (default onboard_full) unmasks all stationary IN_ASSIST until candidate triggers -> triggers on cycle 4!
    res_full = replay_enhanced_road_npz(
        npz_data,
        None,
        case_id="cn_cf_full",
        npz_path="/tmp/cf.npz",
        mode="onboard_full",
    )
    assert res_full.triggered_request is True
    assert res_full.first_request_cycle == 4


def test_shuyi_reconcile_metrics_and_causal_cutoff() -> None:
    from check_sim.onboard_npz import compute_shuyi_reconcile_metrics
    from check_sim.onboard_npz.historical_shuyi_eval import extract_trigger_views_for_arm

    pop_rows = [
        # Auto trigger positive ('正确触发' included in unified P numerator!)
        {"issue_id": "cn_a_pos", "ra_type": 2, "label_6level": "正确触发", "formal_start_ms": 1000, "formal_end_ms": 31000, "ra_start_timestamp": 21000},
        # Auto trigger negative ('误触发')
        {"issue_id": "cn_a_neg", "ra_type": 2, "label_6level": "误触发", "formal_start_ms": 1000, "formal_end_ms": 31000, "ra_start_timestamp": 21000},
        # Manual trigger positive where model only triggered AFTER ra_start_timestamp (25000 > 21000)
        {"issue_id": "cn_m_pos", "ra_type": 3, "label_6level": "成功", "formal_start_ms": 1000, "formal_end_ms": 31000, "ra_start_timestamp": 21000},
        # Manual trigger '误触发' -> excluded from ra-sim eligible cohort, tracked in all_valid_with_manual_false
        {"issue_id": "cn_m_neg", "ra_type": 3, "label_6level": "误触发", "formal_start_ms": 1000, "formal_end_ms": 31000, "ra_start_timestamp": 21000},
        # Excluded label ('未接起')
        {"issue_id": "cn_excl", "ra_type": 2, "label_6level": "未接起", "formal_start_ms": 1000, "formal_end_ms": 31000, "ra_start_timestamp": 21000},
    ]
    arm_eval = {
        "cases": [
            {
                "case_id": "cn_a_pos",
                "modes": {
                    "onboard_strict_road": {
                        "triggered_request": True,
                        "triggered_in_formal_window": True,
                        "emitted_requests": [{"timestamp_ms": 20500, "scheduled": True}],
                    },
                    "onboard_full": {
                        "triggered_request": True,
                        "triggered_in_formal_window": True,
                        "emitted_requests": [{"timestamp_ms": 20500, "scheduled": True}],
                    },
                },
            },
            {
                "case_id": "cn_a_neg",
                "modes": {
                    "onboard_strict_road": {
                        "triggered_request": True,
                        "triggered_in_formal_window": True,
                        "emitted_requests": [{"timestamp_ms": 20800, "scheduled": True}],
                    },
                    "onboard_full": {
                        "triggered_request": False,
                        "triggered_in_formal_window": False,
                        "emitted_requests": [],
                    },
                },
            },
            {
                "case_id": "cn_m_pos",
                "modes": {
                    "onboard_strict_road": {
                        "triggered_request": True,
                        "triggered_in_formal_window": True,
                        # Fired at 25000ms > ra_start_timestamp (21000ms) -> post-manual takeover!
                        "emitted_requests": [{"timestamp_ms": 25000, "scheduled": True}],
                    },
                    "onboard_full": {
                        "triggered_request": True,
                        "triggered_in_formal_window": True,
                        "emitted_requests": [{"timestamp_ms": 25000, "scheduled": True}],
                    },
                },
            },
            {
                "case_id": "cn_m_neg",
                "modes": {
                    "onboard_strict_road": {"triggered_request": False, "triggered_in_formal_window": False, "emitted_requests": []},
                    "onboard_full": {"triggered_request": True, "triggered_in_formal_window": True, "emitted_requests": [{"timestamp_ms": 19000, "scheduled": True}]},
                },
            },
        ]
    }
    views = extract_trigger_views_for_arm(pop_rows, arm_eval)
    # cn_m_pos fired at 25000 > 21000 -> False in causal, True in formal!
    assert views["strict_road_causal"]["cn_m_pos"] is False
    assert views["strict_road_formal"]["cn_m_pos"] is True

    m_causal = compute_shuyi_reconcile_metrics(pop_rows, views["strict_road_causal"])
    # Road online: P = 1/2 = 0.5, R = 1/2 = 0.5; strict_road_causal reproduces exact 1/2 P and 1/2 R (100% repro)!
    assert m_causal["road_online"]["P_unified"] == 0.5
    assert m_causal["road_online"]["R"] == 0.5
    assert m_causal["replay_eligible"]["P_unified"] == 0.5
    assert m_causal["replay_eligible"]["R_covered"] == 0.5
    assert m_causal["replay_eligible"]["road_trigger_repro_rate"] == 1.0

    m_full = compute_shuyi_reconcile_metrics(pop_rows, views["onboard_full_formal"])
    # onboard_full removed cn_a_neg FP and recalled cn_m_pos -> TP=2, FP=0 -> P=1.0, R=1.0 (and manual_false_triggered=1)
    assert m_full["replay_eligible"]["P_unified"] == 1.0
    assert m_full["replay_eligible"]["R_covered"] == 1.0
    assert m_full["all_valid_with_manual_false"]["manual_false_triggered"] == 1


def test_legacy_1009_seed_embedded_tensor_dict_export(tmp_path: Path) -> None:
    """Verify Release <= 20261009 bags where tensor_dict lived in AssistStuckModelOutput (field 4)."""
    bag_path = tmp_path / "legacy_1009.bag"
    records: List[Tuple[str, int, bytes]] = []
    for i in range(3):
        ts_ms = 80_000 + i * 100
        pub_ns = ts_ms * 1_000_000
        # Suppose cycles 0 & 1 share prev_ts=80000, cycle 2 has prev_ts=80200 (2 unique TensorDict frames!)
        prev_ts = 80_000 if i < 2 else 80_200
        e1 = _pb_bytes(1, b"ego") + _pb_bytes(2, _encode_ra_tensor((1, 4), np.ones((1, 4), dtype=np.float32) * prev_ts))
        mout = _pb_varint(1, prev_ts) + _pb_f32(2, 0.72) + _pb_bytes(4, e1)
        aseed = _pb_bytes(9, mout)
        bseed = _pb_bytes(22, aseed)
        seed = _pb_varint(1, ts_ms) + _pb_varint(13, 300 + i) + _pb_bytes(9, bseed)
        records.append(("/planning/seed", pub_ns, _ros_proto_wrap(seed)))

        is_trig = i == 2
        u_stat = int(UnstuckStatus.MODEL_REQUEST if is_trig else UnstuckStatus.UNSTUCK_UNDEFIEND)
        r_dec = int(RuleDecision.kModelDetected if is_trig else RuleDecision.kNone)
        rdbg = _pb_varint(1, r_dec) + (_pb_varint(27, int(AssistModelProcessReason.ASSIST_STUCK_MODEL)) if is_trig else b"")
        rstate = _pb_varint(1, 1 + i) + (_pb_varint(3, 3) if is_trig else b"")
        q_bytes = b"".join(_pb_f64(32, 0.72) for _ in range(i + 1))
        esd = (
            _pb_varint(5, u_stat)
            + _pb_varint(6, int(is_trig))
            + _pb_varint(8, 1)
            + _pb_f64(10, 0.5)
            + _pb_varint(13, 30 + i)
            + _pb_bytes(22, rdbg)
            + q_bytes
            + _pb_f64(34, 0.72)
            + _pb_bytes(36, rstate)
            + _pb_f64(39, 2500.0 + i * 100)
        )
        rad = _pb_varint(1, ts_ms) + _pb_varint(2, 300 + i) + _pb_bytes(7, esd)
        records.append(("/planning/remote_assist_debug", pub_ns + 1000, _ros_proto_wrap(rad)))

    _write_minimal_rosbag(bag_path, records)
    out_npz = tmp_path / "legacy_1009.npz"
    receipt = export_road_bag_to_npz(bag_path, out_npz, case_id="cn_1009_legacy")
    # 2 unique prev_ts frames deduplicated cleanly across 3 10Hz cycles!
    assert receipt["tensor_dict_frames"] == 2
    assert receipt["tensor_dict_keys"] == 1
    assert receipt["consumed_score_cycles"] == 3
    assert receipt["unmatched_score_cycles"] == []

    with OnboardModelRunner("recorded") as runner:
        res = infer_npz_file(out_npz, runner, mode="onboard_strict_road", verify_parity=True)
    assert res.parity is not None and res.parity.passed is True
    assert res.triggered_request is True
