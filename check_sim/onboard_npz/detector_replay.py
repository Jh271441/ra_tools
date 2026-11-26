"""Two-layer Onboard Stuck DNN & 10Hz Scene Detector offline replication engine.

- **Layer 2 (``layer2_road_10hz`` — Enhanced Road NPZ)**:
  Replays the exact 10Hz ``AssistStuckSceneDetector`` + ``AssistStuckEstimator`` +
  ``StuckSceneReasonerManager`` + ``ReasonerArbitrator`` C++ state machine over uncropped
  road ``TensorDict`` frames and 10Hz Speed-cycle signals:
    * ``mode="onboard_full"``: 100% Onboard road-test behavior (FP queue-update suppression,
      FP/FN arbitration, ``FN_SELECTION`` FP discount, 300-cycle ``AssistRequestState`` hold,
      voluntary unstuck gate, uncertain strict-head delay, VLM block).
    * ``mode="model_only"``: Disables non-model FP & FN rules while keeping the exact 10Hz
      autonomous/stationary entry gates, asynchronous ``consumed_frame_index`` delivery, and
      ``AssistStuckEstimator`` queue/freshness trigger logic.
    * ``mode="custom"``: Selective FP/FN rule masks and threshold overrides for ablations.

- **Layer 1 (``layer1_cropped_npz`` — Existing Dataset NPZs)**:
  Automatically used when 10Hz cycle arrays are absent (e.g. ``native6035`` / ``1030_1104`` /
  ``2026Q4_weekly_tensor_dict``). Runs zero-preprocessing ``OnboardModelRunner`` on all stored
  frames and evaluates the exact ``AssistStuckEstimator`` queue (``12000ms`` expire, ``10`` max
  size, ``1500ms`` freshness, ``3`` consecutive ``>= threshold``).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Deque, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .model_runner import FrameScoreBatch, OnboardModelRunner
from .schema import (
    ALREADY_IN_ASSIST_STATUSES,
    ENHANCED_NPZ_SCHEMA,
    IN_ASSIST_ALLOWED_FN_REASONS,
    SELECTION_DISCOUNTED_FP_REASONS,
    TIER_LAYER1_CROPPED,
    TIER_LAYER2_ROAD_10HZ,
    AssistModelProcessReason,
    ConnectRequestType,
    NonVoluntaryUnstuckReason,
    OnboardDetectorConfig,
    RequestUpdateType,
    RuleDecision,
    TaskCode,
    UnstuckStatus,
    enum_name,
)


IMMEDIATE_FN_REASONS: FrozenSet[int] = frozenset({
    AssistModelProcessReason.FN_RA_CZ,
    AssistModelProcessReason.FN_RA_CZ_TRAFFIC_LIGHT,
    AssistModelProcessReason.REQUEST_FROM_ROUTING,
    AssistModelProcessReason.FN_FORCING_RECALL,
    AssistModelProcessReason.FN_FINAL_FORCING_RECALL,
    AssistModelProcessReason.FN_ABNORMAL_TRAFFIC_LIGHT,
})


@dataclass
class ParityReport:
    passed: bool
    total_cycles: int
    unstuck_status_matches: int
    by_model_matches: int
    rule_decision_matches: int
    queue_len_matches: int
    queue_top3_matches: int
    max_score_abs_diff: float
    gt_model_request_cycles: List[int]
    replayed_model_request_cycles: List[int]
    mismatches: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "total_cycles": self.total_cycles,
            "unstuck_status_matches": f"{self.unstuck_status_matches}/{self.total_cycles}",
            "by_model_matches": f"{self.by_model_matches}/{self.total_cycles}",
            "rule_decision_matches": f"{self.rule_decision_matches}/{self.total_cycles}",
            "queue_len_matches": f"{self.queue_len_matches}/{self.total_cycles}",
            "queue_top3_matches": f"{self.queue_top3_matches}/{self.total_cycles}",
            "max_score_abs_diff": self.max_score_abs_diff,
            "gt_model_request_cycles": self.gt_model_request_cycles,
            "replayed_model_request_cycles": self.replayed_model_request_cycles,
            "mismatch_count": len(self.mismatches),
            "first_mismatches": self.mismatches[:10],
        }


@dataclass
class ReplayResult:
    case_id: str
    npz_path: str
    npz_tier: str
    mode: str
    backend: str
    model_path: Optional[str]
    model_sha256: Optional[str]
    num_tensor_frames: int
    num_cycles: int
    triggered_request: bool
    triggered_by_model: bool
    first_request_cycle: Optional[int]
    first_request_timestamp_ms: Optional[int]
    first_model_detect_cycle: Optional[int]
    first_model_detect_timestamp_ms: Optional[int]
    max_main_score: Optional[float]
    max_strict_score: Optional[float]
    frame_main_scores: List[Optional[float]]
    triggered_in_formal_window: bool = False
    triggered_by_model_in_formal_window: bool = False
    cycle_unstuck_status: Optional[ np.ndarray ] = None
    cycle_is_stuck_by_model: Optional[ np.ndarray ] = None
    cycle_rule_decision: Optional[ np.ndarray ] = None
    cycle_queue_len: Optional[ np.ndarray ] = None
    cycle_queue_top3: Optional[ np.ndarray ] = None
    cycle_consumed_main_score: Optional[ np.ndarray ] = None
    emitted_requests: List[Dict[str, Any]] = field(default_factory=list)
    parity: Optional[ParityReport] = None

    def to_summary_dict(self, *, include_frame_scores: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "case_id": self.case_id,
            "npz_path": self.npz_path,
            "npz_tier": self.npz_tier,
            "mode": self.mode,
            "backend": self.backend,
            "model_path": self.model_path,
            "model_sha256": self.model_sha256,
            "num_tensor_frames": self.num_tensor_frames,
            "num_cycles": self.num_cycles,
            "triggered_request": self.triggered_request,
            "triggered_in_formal_window": self.triggered_in_formal_window,
            "triggered_by_model": self.triggered_by_model,
            "triggered_by_model_in_formal_window": self.triggered_by_model_in_formal_window,
            "first_request_cycle": self.first_request_cycle,
            "first_request_timestamp_ms": self.first_request_timestamp_ms,
            "first_model_detect_cycle": self.first_model_detect_cycle,
            "first_model_detect_timestamp_ms": self.first_model_detect_timestamp_ms,
            "max_main_score": self.max_main_score,
            "max_strict_score": self.max_strict_score,
            "emitted_requests": self.emitted_requests,
        }
        if self.cycle_unstuck_status is not None:
            counts: Dict[str, int] = {}
            vals, cnts = np.unique(self.cycle_unstuck_status, return_counts=True)
            for v, c in zip(vals.tolist(), cnts.tolist()):
                counts[enum_name(UnstuckStatus, v)] = int(c)
            out["unstuck_status_counts"] = counts
        if include_frame_scores:
            out["frame_main_scores"] = self.frame_main_scores
        if self.parity is not None:
            out["parity"] = self.parity.to_dict()
        return out


# ---------------------------------------------------------------------------
# Exact C++ Queue Helpers (assist_stuck_estimator.cpp L49-134)
# ---------------------------------------------------------------------------


def _update_prediction_queue(
    queue: Deque[Tuple[int, float]],
    now_ms: int,
    score: Optional[float],
    expire_ms: int,
    max_size: int,
) -> None:
    while queue and (now_ms - queue[-1][0]) > expire_ms:
        queue.pop()
    if score is not None and not np.isnan(score):
        queue.appendleft((int(now_ms), float(score)))
    while len(queue) > max_size:
        queue.pop()


def _is_valid_model_predictions(
    queue: Deque[Tuple[int, float]],
    now_ms: int,
    positive_threshold: float,
    n_times_positive: int,
    continuous_threshold_ms: int,
) -> bool:
    if len(queue) < n_times_positive:
        return False
    if (now_ms - queue[0][0]) > continuous_threshold_ms:
        return False
    for idx in range(n_times_positive):
        if queue[idx][1] < positive_threshold:
            return False
    return True


def _normalize_timestamps_ms(raw_ts: np.ndarray) -> np.ndarray:
    ts = np.asarray(raw_ts, dtype=np.int64).reshape(-1)
    if ts.size and np.max(np.abs(ts)) > 10**15:
        # Convert nanoseconds to milliseconds
        return ts // 1_000_000
    return ts


def is_enhanced_road_npz(npz_data: Mapping[str, Any]) -> bool:
    return "cycle_timestamp_ms" in npz_data and "consumed_frame_index" in npz_data


# ---------------------------------------------------------------------------
# Layer 1: Cropped / Legacy Dataset NPZ Fast Mode
# ---------------------------------------------------------------------------


def evaluate_cropped_npz(
    npz_data: Mapping[str, np.ndarray],
    score_batch: FrameScoreBatch,
    *,
    case_id: str,
    npz_path: str,
    config: OnboardDetectorConfig = OnboardDetectorConfig(),
    threshold_override: Optional[float] = None,
) -> ReplayResult:
    """Evaluate Onboard ``AssistStuckEstimator`` queue & recall criteria on cropped NPZ frames."""
    main_scores = score_batch.main_scores
    strict_scores = score_batch.strict_scores
    n_frames = int(main_scores.shape[0])

    if "tensor_dict_timestamp" in npz_data:
        ts_ms = _normalize_timestamps_ms(npz_data["tensor_dict_timestamp"])
        if ts_ms.shape[0] != n_frames:
            ts_ms = np.arange(n_frames, dtype=np.int64) * 1000
    else:
        ts_ms = np.arange(n_frames, dtype=np.int64) * 1000

    # Preserve non-decreasing order if timestamps are monotonic; sort only if scrambled
    order = list(range(n_frames))
    if n_frames > 1 and np.any(np.diff(ts_ms) < 0):
        order = sorted(range(n_frames), key=lambda i: int(ts_ms[i]))

    thresh = float(threshold_override) if threshold_override is not None else config.default_stuck_threshold
    main_q: Deque[Tuple[int, float]] = deque()
    strict_q: Deque[Tuple[int, float]] = deque()

    first_detect_idx: Optional[int] = None
    first_detect_ts: Optional[int] = None
    emitted_requests: List[Dict[str, Any]] = []

    for step_idx, frame_idx in enumerate(order):
        now = int(ts_ms[frame_idx])
        sc = None if np.isnan(main_scores[frame_idx]) else float(main_scores[frame_idx])
        ssc = (
            None
            if (strict_scores is None or np.isnan(strict_scores[frame_idx]))
            else float(strict_scores[frame_idx])
        )
        _update_prediction_queue(
            main_q,
            now,
            sc,
            config.stuck_likelihood_queue_expire_dur_in_ms,
            config.stuck_likelihood_queue_size,
        )
        _update_prediction_queue(
            strict_q,
            now,
            ssc,
            config.stuck_likelihood_queue_expire_dur_in_ms,
            config.stuck_likelihood_queue_size,
        )
        if sc is not None and _is_valid_model_predictions(
            main_q,
            now,
            thresh,
            config.n_times_positive_for_recall,
            config.stuck_likelihood_continuous_threshold_ms,
        ):
            if first_detect_idx is None:
                first_detect_idx = int(frame_idx)
                first_detect_ts = now
                emitted_requests.append({
                    "frame_index": int(frame_idx),
                    "step_index": int(step_idx),
                    "timestamp_ms": now,
                    "main_score": sc,
                    "queue_top3": [round(main_q[k][1], 6) for k in range(min(3, len(main_q)))],
                })

    finite_main = main_scores[np.isfinite(main_scores)]
    finite_strict = (
        strict_scores[np.isfinite(strict_scores)]
        if strict_scores is not None
        else np.asarray([], dtype=np.float64)
    )
    return ReplayResult(
        case_id=case_id,
        npz_path=npz_path,
        npz_tier=TIER_LAYER1_CROPPED,
        mode="cropped_model_only",
        backend=score_batch.backend,
        model_path=score_batch.model_path,
        model_sha256=score_batch.model_sha256,
        num_tensor_frames=n_frames,
        num_cycles=n_frames,
        triggered_request=first_detect_idx is not None,
        triggered_by_model=first_detect_idx is not None,
        triggered_in_formal_window=first_detect_idx is not None,
        triggered_by_model_in_formal_window=first_detect_idx is not None,
        first_request_cycle=first_detect_idx,
        first_request_timestamp_ms=first_detect_ts,
        first_model_detect_cycle=first_detect_idx,
        first_model_detect_timestamp_ms=first_detect_ts,
        max_main_score=float(np.max(finite_main)) if finite_main.size else None,
        max_strict_score=float(np.max(finite_strict)) if finite_strict.size else None,
        frame_main_scores=[None if np.isnan(x) else float(x) for x in main_scores.tolist()],
        emitted_requests=emitted_requests,
    )


# ---------------------------------------------------------------------------
# Layer 2: Enhanced Road NPZ 10Hz Onboard State-Machine Replicator
# ---------------------------------------------------------------------------


def replay_enhanced_road_npz(
    npz_data: Mapping[str, np.ndarray],
    score_batch: Optional[FrameScoreBatch],
    *,
    case_id: str,
    npz_path: str,
    mode: str = "onboard_full",
    config: OnboardDetectorConfig = OnboardDetectorConfig(),
    threshold_override: Optional[float] = None,
    enabled_fp_reasons: Optional[FrozenSet[int]] = None,
    enabled_fn_reasons: Optional[FrozenSet[int]] = None,
    enable_voluntary_unstuck: Optional[bool] = None,
    enable_uncertain_delay: Optional[bool] = None,
    enable_vlm_block: Optional[bool] = None,
    counterfactual_assist_mode: str = "auto",
    verify_parity: bool = False,
) -> ReplayResult:
    """Exact 10Hz port of ``AssistStuckSceneDetector::DetectStuckScene``.

    ``counterfactual_assist_mode`` controls how recorded road ``already_in_assist`` states
    (opened by the historical road model / operator) are handled BEFORE the candidate model
    itself emits a scheduled RA request while the car is still stationary (``entry_gate == 0``):
      - ``"none"``: strictly inherit recorded road ``already_in_assist`` (default when
        ``verify_parity=True`` or ``mode == "onboard_strict_road"``).
      - ``"light_only"`` (Variant A): unmask only ``ALREADY_IN_LIGHT_ASSIST`` (channel open,
        before any waypoint/reversing path is active) until candidate emits a request.
      - ``"all"`` (Variant B): unmask all ``ALREADY_IN_ASSIST`` sub-states (``LIGHT``,
        ``WAYPOINT``, ``REVERSING``) while the car remains physically stationary
        (``entry_gate == 0``, ``speed < 0.1 m/s``) until candidate emits a request (default
        for ``mode == "onboard_full"`` when ``verify_parity=False``).
    """
    valid_modes = ("onboard_full", "onboard_strict_road", "onboard_light_counterfactual", "model_only", "custom")
    if mode not in valid_modes:
        raise ValueError(f"Unsupported Layer 2 replay mode {mode!r}; expected one of {valid_modes}")
    if counterfactual_assist_mode not in ("auto", "none", "light_only", "all"):
        raise ValueError(f"Unsupported counterfactual_assist_mode {counterfactual_assist_mode!r}")

    if counterfactual_assist_mode == "auto":
        if verify_parity or mode == "onboard_strict_road" or score_batch is None and mode == "onboard_strict_road":
            eff_cf_assist = "none"
        elif mode == "onboard_light_counterfactual":
            eff_cf_assist = "light_only"
        elif mode == "onboard_full" and score_batch is not None:
            eff_cf_assist = "all"
        elif mode == "onboard_full" and score_batch is None and not verify_parity:
            eff_cf_assist = "all"
        else:
            eff_cf_assist = "none"
    else:
        eff_cf_assist = counterfactual_assist_mode

    cycle_ts = np.asarray(npz_data["cycle_timestamp_ms"], dtype=np.int64)
    cycle_seq = np.asarray(npz_data["cycle_sequence"], dtype=np.int64)
    consumed_idx = np.asarray(npz_data["consumed_frame_index"], dtype=np.int32)
    rec_main = np.asarray(npz_data["recorded_main_score"], dtype=np.float64)
    rec_strict = np.asarray(npz_data["recorded_strict_score"], dtype=np.float64)
    entry_gate = np.asarray(npz_data["entry_gate_status"], dtype=np.int32)
    ego_moving_fast = np.asarray(npz_data["ego_moving_fast"], dtype=np.bool_)
    in_assist_arr = np.asarray(npz_data["already_in_assist_status"], dtype=np.int32)
    has_vol_modes = np.asarray(npz_data["has_voluntary_unstuck_modes"], dtype=np.bool_)
    is_vol_fail = np.asarray(npz_data["is_voluntary_unstuck_fail"], dtype=np.bool_)
    stat_cnt_arr = np.asarray(npz_data["stationary_cycle_count"], dtype=np.int64)
    thresh_arr = np.asarray(npz_data["stuck_threshold"], dtype=np.float64)
    vlm_block_arr = np.asarray(npz_data["is_vlm_block"], dtype=np.bool_)
    core_status_arr = np.asarray(npz_data["core_planner_status"], dtype=np.int32)
    flag_omni_arr = np.asarray(npz_data["flag_or_omni_status"], dtype=np.int32)

    fp_per_cycle: List[List[int]] = json.loads(str(npz_data["fp_reasons_json"].item()))
    fn_non_model_per_cycle: List[List[List[int]]] = json.loads(str(npz_data["fn_non_model_reasons_json"].item()))
    init_state: Dict[str, Any] = json.loads(str(npz_data["initial_state_json"].item()))

    n_cycles = int(cycle_ts.shape[0])
    n_frames = int(np.asarray(npz_data["tensor_dict_timestamp"]).shape[0])
    sched_blocked = (
        np.asarray(npz_data["scheduler_session_blocked"], dtype=np.bool_)
        if "scheduler_session_blocked" in npz_data
        else np.zeros(n_cycles, dtype=np.bool_)
    )
    formal_window = (
        np.asarray(npz_data["formal_window_ms"], dtype=np.int64).reshape(-1)
        if "formal_window_ms" in npz_data
        else np.asarray([-1, -1], dtype=np.int64)
    )

    use_voluntary = (
        (mode != "model_only") if enable_voluntary_unstuck is None else bool(enable_voluntary_unstuck)
    )
    use_uncertain_delay = (
        config.enable_uncertain_delay if enable_uncertain_delay is None else bool(enable_uncertain_delay)
    )
    use_vlm_block = (
        (config.enable_vlm_block if mode != "model_only" else False)
        if enable_vlm_block is None
        else bool(enable_vlm_block)
    )

    # Initialize state machine from reconstructed pre-cycle-0 state
    main_q: Deque[Tuple[int, float]] = deque(
        (int(item[0]), float(item[1])) for item in init_state.get("initial_main_queue", [])
    )
    strict_q: Deque[Tuple[int, float]] = deque(
        (int(item[0]), float(item[1])) for item in init_state.get("initial_strict_queue", [])
    )
    if mode == "model_only":
        # Still keep initial model likelihood queue from road history; clear non-model task states
        task_states: Dict[int, Dict[str, int]] = {
            int(k): dict(v)
            for k, v in init_state.get("initial_task_code_to_state", {}).items()
            if int(v.get("process_reason", 0)) in (0, int(AssistModelProcessReason.ASSIST_STUCK_MODEL))
        }
    else:
        task_states = {int(k): dict(v) for k, v in init_state.get("initial_task_code_to_state", {}).items()}

    seq_id = int(init_state.get("initial_seq_id", 0))
    first_stuck_seq_id: Optional[int] = (
        int(init_state["initial_first_stuck_detected_seq_id"])
        if int(init_state.get("initial_first_stuck_detected_seq_id", -1)) >= 0
        else None
    )
    consecutive_fn_cnt = int(init_state.get("initial_continuous_fn_cnt", 0))
    request_id = int(init_state.get("initial_request_id", 0))
    has_sent_assist_request = bool(init_state.get("initial_has_sent_assist_request", False))
    timer_start_ms = int(init_state.get("initial_timer_start_ms", int(cycle_ts[0])))

    def reset_detector_status(now_ms: int) -> None:
        nonlocal has_sent_assist_request, timer_start_ms
        has_sent_assist_request = False
        timer_start_ms = now_ms

    def reset_reasoner_manager() -> None:
        nonlocal consecutive_fn_cnt, seq_id, first_stuck_seq_id
        consecutive_fn_cnt = 0
        seq_id = 0
        first_stuck_seq_id = None
        task_states.clear()

    def cancel_all_tasks() -> None:
        task_states.clear()

    # Output buffers
    out_unstuck = np.zeros(n_cycles, dtype=np.int32)
    out_by_model = np.zeros(n_cycles, dtype=np.bool_)
    out_rule_dec = np.full(n_cycles, -1, dtype=np.int32)
    out_queue_len = np.zeros(n_cycles, dtype=np.int32)
    out_queue_top3 = np.full((n_cycles, 3), np.nan, dtype=np.float64)
    out_consumed_main = np.full(n_cycles, np.nan, dtype=np.float64)
    emitted_requests: List[Dict[str, Any]] = []

    first_req_cycle: Optional[int] = None
    first_req_ts: Optional[int] = None
    first_model_cycle: Optional[int] = None
    first_model_ts: Optional[int] = None
    has_emitted_scheduled_request = False

    for c_idx in range(n_cycles):
        now_ms = int(cycle_ts[c_idx])
        f_idx = int(consumed_idx[c_idx])
        raw_in_assist_status = int(in_assist_arr[c_idx])
        if not has_emitted_scheduled_request and int(entry_gate[c_idx]) == 0:
            if eff_cf_assist == "all":
                already_in_assist_status = 0
            elif eff_cf_assist == "light_only" and raw_in_assist_status == int(UnstuckStatus.ALREADY_IN_LIGHT_ASSIST):
                already_in_assist_status = 0
            else:
                already_in_assist_status = raw_in_assist_status
        else:
            already_in_assist_status = raw_in_assist_status
        already_in_assist = already_in_assist_status in ALREADY_IN_ASSIST_STATUSES

        # 1. Resolve current-cycle model output (UpdateDNNModelOutput)
        cur_main: Optional[float] = None
        cur_strict: Optional[float] = None
        if score_batch is None:
            if not np.isnan(rec_main[c_idx]):
                cur_main = float(rec_main[c_idx])
            if not np.isnan(rec_strict[c_idx]):
                cur_strict = float(rec_strict[c_idx])
        elif f_idx >= 0:
            if not np.isnan(score_batch.main_scores[f_idx]):
                cur_main = float(score_batch.main_scores[f_idx])
            if score_batch.strict_scores is not None and not np.isnan(score_batch.strict_scores[f_idx]):
                cur_strict = float(score_batch.strict_scores[f_idx])

        if cur_main is not None:
            out_consumed_main[c_idx] = cur_main

        # 2. Early-return entry gates before CheckRules()
        gate = int(entry_gate[c_idx])
        if gate != 0:
            if gate == UnstuckStatus.OPS_REFUSED_SCENE:
                reset_detector_status(now_ms)
                reset_reasoner_manager()
            elif gate == UnstuckStatus.MANUAL_DRIVING:
                reset_detector_status(now_ms)
                cancel_all_tasks()
            elif gate == UnstuckStatus.MRC_REACHED:
                reset_detector_status(now_ms)
                cancel_all_tasks()
            elif gate == UnstuckStatus.NOT_STATIONARY:
                if bool(ego_moving_fast[c_idx]):
                    if already_in_assist:
                        reset_reasoner_manager()
                    else:
                        cancel_all_tasks()
                reset_detector_status(now_ms)
            elif gate == UnstuckStatus.NORMAL_EXIT:
                reset_detector_status(now_ms)
                reset_reasoner_manager()
            out_unstuck[c_idx] = gate
            out_queue_len[c_idx] = len(main_q)
            for j in range(min(3, len(main_q))):
                out_queue_top3[c_idx, j] = main_q[j][1]
            continue

        unstuck_status = (
            int(UnstuckStatus.CORE_PLANNER_DETECT)
            if int(core_status_arr[c_idx]) == int(UnstuckStatus.CORE_PLANNER_DETECT)
            else int(UnstuckStatus.UNSTUCK_UNDEFIEND)
        )

        # 3. IsUnderVoluntaryUnstuckMode (exact timer + seed behavior)
        if use_voluntary:
            elapsed_ms = now_ms - timer_start_ms
            is_undetected = (not bool(has_vol_modes[c_idx])) and (
                elapsed_ms > config.voluntary_undetected_stuck_scene_time_threshold_ms
            )
            is_under_voluntary = not (is_undetected or bool(is_vol_fail[c_idx]))
        else:
            is_under_voluntary = False

        # 4. StuckSceneReasonerManager::Reason()
        # 4a. FP group
        if mode == "model_only":
            active_fp: List[int] = []
        elif mode == "custom" and enabled_fp_reasons is not None:
            active_fp = [r for r in fp_per_cycle[c_idx] if r in enabled_fp_reasons]
        else:
            active_fp = list(fp_per_cycle[c_idx])

        has_fp_activation = len(active_fp) > 0
        if not has_fp_activation:
            _update_prediction_queue(
                main_q,
                now_ms,
                cur_main,
                config.stuck_likelihood_queue_expire_dur_in_ms,
                config.stuck_likelihood_queue_size,
            )
            _update_prediction_queue(
                strict_q,
                now_ms,
                cur_strict,
                config.stuck_likelihood_queue_expire_dur_in_ms,
                config.stuck_likelihood_queue_size,
            )

        # 4b. FN group (StuckModelSceneReasoner + non-model FN rules)
        eff_thresh = (
            float(threshold_override) if threshold_override is not None else float(thresh_arr[c_idx])
        )
        fn_outputs: List[Tuple[int, int]] = []
        by_model_this_cycle = False
        if cur_main is not None and _is_valid_model_predictions(
            main_q,
            now_ms,
            eff_thresh,
            config.n_times_positive_for_recall,
            config.stuck_likelihood_continuous_threshold_ms,
        ):
            by_model_this_cycle = True
            fn_outputs.append((int(AssistModelProcessReason.ASSIST_STUCK_MODEL), int(TaskCode.STUCK_OTHER)))
            if first_model_cycle is None:
                first_model_cycle = c_idx
                first_model_ts = now_ms

        if mode != "model_only":
            for r_int, t_code in fn_non_model_per_cycle[c_idx]:
                if mode == "custom" and enabled_fn_reasons is not None and r_int not in enabled_fn_reasons:
                    continue
                fn_outputs.append((int(r_int), int(t_code)))

        # 4c. ReasonerArbitrator::CheckReasonerOutputs()
        seq_id += 1
        fp_set = set(active_fp)
        fn_set = {r for r, _ in fn_outputs}

        num_fp = len(fp_set)
        if AssistModelProcessReason.FN_SELECTION in fn_set:
            for disc_fp in SELECTION_DISCOUNTED_FP_REASONS:
                if disc_fp in fp_set and num_fp > 0:
                    num_fp -= 1

        # ShouldRequestImmediately
        is_map_change = bool(
            fn_set & {AssistModelProcessReason.FN_RA_CZ, AssistModelProcessReason.FN_RA_CZ_TRAFFIC_LIGHT}
        )
        is_routing = AssistModelProcessReason.REQUEST_FROM_ROUTING in fn_set
        is_forcing = bool(
            fn_set & {AssistModelProcessReason.FN_FORCING_RECALL, AssistModelProcessReason.FN_FINAL_FORCING_RECALL}
        )
        is_creep = (
            AssistModelProcessReason.REQUEST_FROM_CREEP in fn_set
            and AssistModelProcessReason.FP_STARTUP not in fp_set
            and AssistModelProcessReason.FP_PULL_OVER not in fp_set
        )
        is_special_req = has_sent_assist_request and (
            AssistModelProcessReason.SPECIAL_STUCK_SCENE in fn_set
        )
        is_abn_tl = AssistModelProcessReason.FN_ABNORMAL_TRAFFIC_LIGHT in fn_set

        should_req_imm = (
            is_map_change or is_routing or is_forcing or is_creep or is_abn_tl or is_special_req
        )
        if should_req_imm:
            rule_decision = int(RuleDecision.kRequestImmediately)
        elif num_fp > 0:
            rule_decision = int(RuleDecision.kAbort)
        elif AssistModelProcessReason.ASSIST_STUCK_MODEL in fn_set:
            rule_decision = int(RuleDecision.kModelDetected)
        elif fn_set and (AssistModelProcessReason.SPECIAL_STUCK_SCENE not in fn_set):
            rule_decision = int(RuleDecision.kHasActivateFN)
        else:
            rule_decision = int(RuleDecision.kNone)

        if rule_decision == RuleDecision.kAbort:
            consecutive_fn_cnt = max(0, consecutive_fn_cnt - 1)
        elif rule_decision == RuleDecision.kHasActivateFN:
            consecutive_fn_cnt += 1
            if (
                int(stat_cnt_arr[c_idx]) > config.fn_trigger_cycle_count
                and consecutive_fn_cnt > 0.7 * config.fn_trigger_cycle_count
            ):
                by_model_this_cycle = False
                rule_decision = int(RuleDecision.kStuckDetected)

        # CheckRequestStates
        effective_outputs: List[Tuple[int, int]] = []
        dominant_update = int(RequestUpdateType.kNone)
        if rule_decision in (
            RuleDecision.kRequestImmediately,
            RuleDecision.kStuckDetected,
            RuleDecision.kModelDetected,
        ):
            update_types = set()
            for r_int, t_code in fn_outputs:
                if t_code == TaskCode.UNKNOWN:
                    continue
                st_info = task_states.get(t_code, {"state": 0, "last_changed_seq_id": 0})
                prev_st = int(st_info.get("state", 0))
                if prev_st != 1:
                    u_type = int(RequestUpdateType.kNewState)
                elif (seq_id - int(st_info.get("last_changed_seq_id", 0))) >= config.model_request_hold_cycle_count:
                    u_type = int(RequestUpdateType.kTimeout)
                else:
                    u_type = int(RequestUpdateType.kNone)
                if u_type != RequestUpdateType.kNone:
                    effective_outputs.append((r_int, t_code))
                    update_types.add(u_type)
            if RequestUpdateType.kNewState in update_types:
                if first_stuck_seq_id is None:
                    first_stuck_seq_id = seq_id
                dominant_update = int(RequestUpdateType.kNewState)
            elif RequestUpdateType.kTimeout in update_types:
                dominant_update = int(RequestUpdateType.kTimeout)

        # Uncertain delay check
        should_delay_uncertain = False
        if AssistModelProcessReason.ASSIST_STUCK_MODEL in fn_set:
            if int(stat_cnt_arr[c_idx]) <= config.delay_posting_request_cycle_cnt:
                strict_valid = _is_valid_model_predictions(
                    strict_q,
                    now_ms,
                    eff_thresh,
                    config.n_times_positive_for_recall,
                    config.stuck_likelihood_continuous_threshold_ms,
                )
                if not strict_valid:
                    should_delay_uncertain = True

        # 5. Post-rule branching (assist_stuck_scene_detector.cpp L711-784)
        if rule_decision == RuleDecision.kAbort:
            final_status = int(UnstuckStatus.MODEL_FP)
        elif int(flag_omni_arr[c_idx]) != 0:
            final_status = int(flag_omni_arr[c_idx])
        else:
            posted_model_request = False
            if dominant_update != RequestUpdateType.kNone:
                if dominant_update == RequestUpdateType.kCancel:
                    final_status = int(UnstuckStatus.CANCEL_REQUEST)
                    posted_model_request = True
                else:
                    if dominant_update == RequestUpdateType.kNewState:
                        request_id += 1
                    if first_stuck_seq_id is not None and seq_id == first_stuck_seq_id:
                        timer_start_ms = now_ms

                    vlm_blocked = use_vlm_block and bool(vlm_block_arr[c_idx])
                    if not vlm_blocked:
                        if already_in_assist:
                            should_post = bool(fn_set & IN_ASSIST_ALLOWED_FN_REASONS)
                        elif rule_decision != RuleDecision.kRequestImmediately and is_under_voluntary:
                            should_post = False
                        elif should_delay_uncertain and use_uncertain_delay:
                            should_post = False
                        else:
                            should_post = True

                        if should_post:
                            for r_int, t_code in effective_outputs:
                                prev_req_id = task_states.get(t_code, {}).get("request_id", 0)
                                task_states[t_code] = {
                                    "task_code": t_code,
                                    "state": 1,
                                    "last_changed_seq_id": seq_id,
                                    "last_changed_timestamp": now_ms,
                                    "process_reason": r_int,
                                    "request_id": (
                                        request_id
                                        if dominant_update == RequestUpdateType.kNewState
                                        else prev_req_id
                                    ),
                                }
                            has_sent_assist_request = True
                            posted_model_request = True
                            final_status = int(UnstuckStatus.MODEL_REQUEST)
                            eff_reason_set = {r for r, _ in effective_outputs}
                            if AssistModelProcessReason.REQUEST_FROM_CREEP in eff_reason_set:
                                req_type_code = int(ConnectRequestType.kCorePlannerRequest)
                            elif AssistModelProcessReason.FN_RA_CZ_TRAFFIC_LIGHT in eff_reason_set:
                                req_type_code = int(ConnectRequestType.kCZTrafficLightRequest)
                            elif AssistModelProcessReason.FN_ABNORMAL_TRAFFIC_LIGHT in eff_reason_set:
                                req_type_code = int(ConnectRequestType.kAbnormalTrafficLight)
                            elif AssistModelProcessReason.REQUEST_FROM_TIDAL_FLOW_LANE in eff_reason_set:
                                req_type_code = int(ConnectRequestType.kTidalFlowLane)
                            elif AssistModelProcessReason.FN_EOL in eff_reason_set:
                                req_type_code = int(ConnectRequestType.kEndOfLaneSequence)
                            else:
                                req_type_code = int(ConnectRequestType.kStuckModelRequest)

                            scheduled_by_session = not bool(sched_blocked[c_idx])
                            in_formal = (
                                True
                                if (formal_window.size < 2 or formal_window[0] < 0)
                                else bool(formal_window[0] <= now_ms <= formal_window[1])
                            )
                            emitted_requests.append({
                                "cycle_index": c_idx,
                                "sequence": int(cycle_seq[c_idx]),
                                "timestamp_ms": now_ms,
                                "request_id": request_id,
                                "request_type": enum_name(ConnectRequestType, req_type_code),
                                "scheduled": scheduled_by_session,
                                "in_formal_window": in_formal,
                                "rule_decision": enum_name(RuleDecision, rule_decision),
                                "triggered_by_model": (
                                    AssistModelProcessReason.ASSIST_STUCK_MODEL in eff_reason_set
                                ),
                                "reasons": [enum_name(AssistModelProcessReason, r) for r, _ in effective_outputs],
                                "main_score": cur_main,
                            })
                            if scheduled_by_session:
                                has_emitted_scheduled_request = True
                                if first_req_cycle is None:
                                    first_req_cycle = c_idx
                                    first_req_ts = now_ms

            if not posted_model_request:
                if already_in_assist:
                    timer_start_ms = now_ms
                    final_status = already_in_assist_status
                elif is_under_voluntary:
                    final_status = int(UnstuckStatus.WAITTING_CORE_PLANNER_UNSTUCK)
                elif rule_decision == RuleDecision.kHasActivateFN:
                    final_status = int(UnstuckStatus.RULE_FN_DETECT)
                else:
                    final_status = unstuck_status

        out_unstuck[c_idx] = final_status
        out_by_model[c_idx] = by_model_this_cycle
        out_rule_dec[c_idx] = rule_decision
        out_queue_len[c_idx] = len(main_q)
        for j in range(min(3, len(main_q))):
            out_queue_top3[c_idx, j] = main_q[j][1]

    if score_batch is not None:
        raw_scores = score_batch.main_scores
        raw_strict = score_batch.strict_scores
        backend_name = score_batch.backend
        model_path_str = score_batch.model_path
        model_sha = score_batch.model_sha256
    else:
        raw_scores = np.full(n_frames, np.nan, dtype=np.float64)
        for c_idx in range(n_cycles):
            fi = int(consumed_idx[c_idx])
            if fi >= 0 and not np.isnan(rec_main[c_idx]):
                raw_scores[fi] = rec_main[c_idx]
        raw_strict = None
        backend_name = "recorded"
        model_path_str = None
        model_sha = None

    finite_main = out_consumed_main[np.isfinite(out_consumed_main)]
    finite_strict = (
        raw_strict[np.isfinite(raw_strict)]
        if raw_strict is not None
        else rec_strict[np.isfinite(rec_strict)]
    )
    scheduled_reqs = [r for r in emitted_requests if r.get("scheduled", True)]
    formal_scheduled_reqs = [r for r in scheduled_reqs if r.get("in_formal_window", True)]
    triggered_by_model = any(bool(r.get("triggered_by_model")) for r in scheduled_reqs)
    triggered_by_model_formal = any(bool(r.get("triggered_by_model")) for r in formal_scheduled_reqs)

    result = ReplayResult(
        case_id=case_id,
        npz_path=npz_path,
        npz_tier=TIER_LAYER2_ROAD_10HZ,
        mode=mode,
        backend=backend_name,
        model_path=model_path_str,
        model_sha256=model_sha,
        num_tensor_frames=n_frames,
        num_cycles=n_cycles,
        triggered_request=len(scheduled_reqs) > 0,
        triggered_by_model=triggered_by_model,
        triggered_in_formal_window=len(formal_scheduled_reqs) > 0,
        triggered_by_model_in_formal_window=triggered_by_model_formal,
        first_request_cycle=first_req_cycle,
        first_request_timestamp_ms=first_req_ts,
        first_model_detect_cycle=first_model_cycle,
        first_model_detect_timestamp_ms=first_model_ts,
        max_main_score=float(np.max(finite_main)) if finite_main.size else None,
        max_strict_score=float(np.max(finite_strict)) if finite_strict.size else None,
        frame_main_scores=[None if np.isnan(x) else float(x) for x in raw_scores.tolist()],
        cycle_unstuck_status=out_unstuck,
        cycle_is_stuck_by_model=out_by_model,
        cycle_rule_decision=out_rule_dec,
        cycle_queue_len=out_queue_len,
        cycle_queue_top3=out_queue_top3,
        cycle_consumed_main_score=out_consumed_main,
        emitted_requests=emitted_requests,
    )
    if verify_parity:
        result.parity = compute_onboard_parity(result, npz_data)
    return result


def compute_onboard_parity(
    result: ReplayResult,
    npz_data: Mapping[str, np.ndarray],
    *,
    score_atol: Optional[float] = None,
) -> ParityReport:
    """Compare every 10Hz cycle of ``result`` against ground-truth Onboard ``EgoStuckDebug``."""
    eff_atol = (1e-5 if result.backend == "recorded" else 5e-3) if score_atol is None else float(score_atol)
    gt_unstuck = np.asarray(npz_data["gt_unstuck_status"], dtype=np.int32)
    gt_by_model = np.asarray(npz_data["gt_is_stuck_by_model"], dtype=np.bool_)
    gt_rule_dec = np.asarray(npz_data["gt_rule_decision"], dtype=np.int32)
    gt_q_len = np.asarray(npz_data["gt_queue_len"], dtype=np.int32)
    gt_q_top3 = np.asarray(npz_data["gt_queue_top3"], dtype=np.float64)
    rec_main = np.asarray(npz_data["recorded_main_score"], dtype=np.float64)
    cycle_seq = np.asarray(npz_data["cycle_sequence"], dtype=np.int64)
    cycle_ts = np.asarray(npz_data["cycle_timestamp_ms"], dtype=np.int64)

    assert result.cycle_unstuck_status is not None
    assert result.cycle_is_stuck_by_model is not None
    assert result.cycle_rule_decision is not None
    assert result.cycle_queue_len is not None
    assert result.cycle_queue_top3 is not None
    assert result.cycle_consumed_main_score is not None

    n = int(gt_unstuck.shape[0])
    u_ok = int(np.sum(result.cycle_unstuck_status == gt_unstuck))
    m_ok = int(np.sum(result.cycle_is_stuck_by_model == gt_by_model))
    r_ok = int(np.sum(result.cycle_rule_decision == gt_rule_dec))
    ql_ok = int(np.sum(result.cycle_queue_len == gt_q_len))

    top3_match_mask = np.ones(n, dtype=np.bool_)
    for j in range(3):
        a = result.cycle_queue_top3[:, j]
        b = gt_q_top3[:, j]
        both_nan = np.isnan(a) & np.isnan(b)
        close = np.isfinite(a) & np.isfinite(b) & (np.abs(a - b) <= eff_atol)
        top3_match_mask &= both_nan | close
    qt_ok = int(np.sum(top3_match_mask))

    both_scores = np.isfinite(result.cycle_consumed_main_score) & np.isfinite(rec_main)
    max_diff = (
        float(np.max(np.abs(result.cycle_consumed_main_score[both_scores] - rec_main[both_scores])))
        if np.any(both_scores)
        else 0.0
    )

    mismatches: List[Dict[str, Any]] = []
    for i in range(n):
        if (
            result.cycle_unstuck_status[i] != gt_unstuck[i]
            or result.cycle_is_stuck_by_model[i] != gt_by_model[i]
            or result.cycle_rule_decision[i] != gt_rule_dec[i]
            or result.cycle_queue_len[i] != gt_q_len[i]
            or not top3_match_mask[i]
        ):
            mismatches.append({
                "cycle_index": i,
                "sequence": int(cycle_seq[i]),
                "timestamp_ms": int(cycle_ts[i]),
                "gt_unstuck": enum_name(UnstuckStatus, int(gt_unstuck[i])),
                "replayed_unstuck": enum_name(UnstuckStatus, int(result.cycle_unstuck_status[i])),
                "gt_by_model": bool(gt_by_model[i]),
                "replayed_by_model": bool(result.cycle_is_stuck_by_model[i]),
                "gt_rule_decision": int(gt_rule_dec[i]),
                "replayed_rule_decision": int(result.cycle_rule_decision[i]),
                "gt_queue_len": int(gt_q_len[i]),
                "replayed_queue_len": int(result.cycle_queue_len[i]),
            })

    gt_req_cycles = np.where(gt_unstuck == int(UnstuckStatus.MODEL_REQUEST))[0].astype(int).tolist()
    rep_req_cycles = (
        np.where(result.cycle_unstuck_status == int(UnstuckStatus.MODEL_REQUEST))[0].astype(int).tolist()
    )

    passed = (
        u_ok == n
        and m_ok == n
        and r_ok == n
        and ql_ok == n
        and qt_ok == n
        and max_diff <= eff_atol
    )
    return ParityReport(
        passed=passed,
        total_cycles=n,
        unstuck_status_matches=u_ok,
        by_model_matches=m_ok,
        rule_decision_matches=r_ok,
        queue_len_matches=ql_ok,
        queue_top3_matches=qt_ok,
        max_score_abs_diff=max_diff,
        gt_model_request_cycles=gt_req_cycles,
        replayed_model_request_cycles=rep_req_cycles,
        mismatches=mismatches,
    )


# ---------------------------------------------------------------------------
# Unified Auto-Dispatch Entry Point
# ---------------------------------------------------------------------------


def infer_npz_file(
    npz_path: os.PathLike | str,
    runner: OnboardModelRunner,
    *,
    mode: str = "auto",
    config: OnboardDetectorConfig = OnboardDetectorConfig(),
    threshold_override: Optional[float] = None,
    verify_parity: bool = False,
    infer_all_frames: bool = False,
) -> ReplayResult:
    """Load an NPZ (Layer 1 cropped or Layer 2 road-enhanced) and replicate Onboard inference."""
    path = Path(npz_path).expanduser().resolve()
    with np.load(path, allow_pickle=False) as raw_npz:
        data = {k: raw_npz[k] for k in raw_npz.files}

    case_id = (
        str(data["issue_id"].item())
        if "issue_id" in data and data["issue_id"].ndim == 0
        else path.stem
    )

    if is_enhanced_road_npz(data):
        resolved_mode = "onboard_full" if mode == "auto" else mode
        if runner.backend_name == "recorded":
            score_batch = None
        else:
            consumed = np.asarray(data["consumed_frame_index"], dtype=np.int32)
            target_frames = None if infer_all_frames else consumed[consumed >= 0].tolist()
            score_batch = runner.infer_npz(data, only_frame_indices=target_frames)
        return replay_enhanced_road_npz(
            data,
            score_batch,
            case_id=case_id,
            npz_path=str(path),
            mode=resolved_mode,
            config=config,
            threshold_override=threshold_override,
            verify_parity=verify_parity,
        )

    if mode not in ("auto", "cropped_model_only", "model_only"):
        raise ValueError(
            f"NPZ {path} is a Layer 1 cropped dataset NPZ (no 10Hz cycle arrays); "
            f"cannot run mode={mode!r}. Export an Enhanced Road NPZ with 'export-bag' for full rules."
        )
    score_batch = runner.infer_npz(data)
    return evaluate_cropped_npz(
        data,
        score_batch,
        case_id=case_id,
        npz_path=str(path),
        config=config,
        threshold_override=threshold_override,
    )
