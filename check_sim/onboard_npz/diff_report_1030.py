"""Frozen Release 1030 full-population offline NPZ evaluation & paired Base-vs-Feature Diff engine.

Follows the exact governance of ``ra-stuck-model`` & ``compare_final_requests.py``:
  - Frozen 1,563 physical issues (``1,561`` executable scenarios; ``cn37721357`` & ``cn37790313``
    have no scenario and remain ``None`` / ``unknown``, never silently coerced to ``False``).
  - ``1,415`` review-eligible business issues, ``784`` full recall denominator (``label != '误触发'``).
  - Reports all 4 standard business cohorts separately:
      1. ``all_business`` (1,415)
      2. ``traffic_EOL`` (400)
      3. ``non_traffic_business`` (1,015)
      4. ``NPZ_business_common`` (974)
  - Independently SQL-verifies both standard P/R formulas via ``sqlite3`` in-memory:
      * ``unified_binary`` (``TP = requested AND label != '误触发'`` — matches ``VERIFIED.json`` &
        ``EXISTING_1030_COMPARE`` where Q2 Sim = 53.57% / 79.44% and CR 7028995 E21 Sim Job 50509481
        = 85.30% / 68.29%)
      * ``strict_good_p`` (``P_num = requested AND label IN GOOD``, ``R_num = requested AND label != '误触发'``)
  - Computes paired Base-vs-Feature transition matrices and case-by-case cross-checks against
    historical Orion 1030 simulation results.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .detector_replay import evaluate_cropped_npz, is_enhanced_road_npz, replay_enhanced_road_npz
from .model_runner import OnboardModelRunner
from .schema import OnboardDetectorConfig


GOOD_LABELS = frozenset({"成功", "失败", "无需协助", "限制使用"})

DEFAULT_ALL1563_REQUESTS = Path(
    "reports/sim1030_model_metrics_report_20261115/all1563_model_requests.private.jsonl"
)
DEFAULT_COHORT_JSON = Path(
    "reports/sim1030_bottleneck_analysis_20261116_v3/COHORT_AND_TRANSITIONS.json"
)
DEFAULT_ORION_COMPARE_JSON = Path(
    "reports/stuck_q4_e_mid_e13_replay_20261122_v1/EXISTING_1030_COMPARE_1795316107149650000.json"
)


# ---------------------------------------------------------------------------
# Persistent worker pool for fast multi-core IFX / ONNX inference
# ---------------------------------------------------------------------------

_WORKER_RUNNER: Optional[OnboardModelRunner] = None
_WORKER_CFG: Optional[OnboardDetectorConfig] = None
_WORKER_MODES: Tuple[str, ...] = ("onboard_full",)
_WORKER_THRESHOLD: Optional[float] = None
_WORKER_VERIFY_PARITY: bool = False


def _init_eval_worker(
    model_path: str,
    device: str,
    bridge_so: Optional[str],
    modes: Tuple[str, ...],
    enable_uncertain_delay: bool,
    threshold_override: Optional[float],
    verify_parity: bool,
) -> None:
    global _WORKER_RUNNER, _WORKER_CFG, _WORKER_MODES, _WORKER_THRESHOLD, _WORKER_VERIFY_PARITY
    _WORKER_RUNNER = OnboardModelRunner(
        model_path,
        device=device,
        bridge_so=Path(bridge_so) if bridge_so else None,
    )
    _WORKER_CFG = OnboardDetectorConfig(enable_uncertain_delay=enable_uncertain_delay)
    _WORKER_MODES = modes
    _WORKER_THRESHOLD = threshold_override
    _WORKER_VERIFY_PARITY = verify_parity


def _eval_one_npz_in_worker(npz_path_str: str) -> Dict[str, Any]:
    assert _WORKER_RUNNER is not None and _WORKER_CFG is not None
    path = Path(npz_path_str)
    with np.load(path, allow_pickle=False) as raw_npz:
        data = {k: raw_npz[k] for k in raw_npz.files}

    case_id = (
        str(data["issue_id"].item())
        if "issue_id" in data and data["issue_id"].ndim == 0
        else path.stem
    )
    enhanced = is_enhanced_road_npz(data)
    if _WORKER_RUNNER.backend_name == "recorded":
        score_batch = None
    elif enhanced:
        consumed = np.asarray(data["consumed_frame_index"], dtype=np.int32)
        target_frames = sorted({int(i) for i in consumed.tolist() if int(i) >= 0})
        score_batch = _WORKER_RUNNER.infer_npz(data, only_frame_indices=target_frames)
    else:
        score_batch = _WORKER_RUNNER.infer_npz(data)

    mode_summaries: Dict[str, Dict[str, Any]] = {}
    for m in _WORKER_MODES:
        if enhanced and m in ("onboard_full", "onboard_strict_road", "onboard_light_counterfactual", "model_only"):
            res = replay_enhanced_road_npz(
                data,
                score_batch,
                case_id=case_id,
                npz_path=str(path),
                mode=m,
                config=_WORKER_CFG,
                threshold_override=_WORKER_THRESHOLD,
                verify_parity=(_WORKER_VERIFY_PARITY and m == "onboard_strict_road"),
            )
        else:
            if score_batch is None:
                raise RuntimeError("cropped_model_only requires a model file, not 'recorded'")
            res = evaluate_cropped_npz(
                data,
                score_batch,
                case_id=case_id,
                npz_path=str(path),
                config=_WORKER_CFG,
                threshold_override=_WORKER_THRESHOLD,
            )
        summary = res.to_summary_dict(include_frame_scores=False)
        mode_summaries[m] = summary

    # Also capture road ground-truth connect requests in formal window if present
    gt_formal_req: Optional[bool] = None
    if "gt_connect_request_ts" in data:
        gt_ts = np.asarray(data["gt_connect_request_ts"], dtype=np.int64)
        fw = (
            np.asarray(data["formal_window_ms"], dtype=np.int64)
            if "formal_window_ms" in data
            else np.asarray([-1, -1], dtype=np.int64)
        )
        if fw.size == 2 and fw[0] >= 0:
            gt_formal_req = bool(np.any((gt_ts >= fw[0]) & (gt_ts <= fw[1])))
        else:
            gt_formal_req = bool(gt_ts.size > 0)

    return {
        "case_id": case_id,
        "npz_path": str(path),
        "num_tensor_frames": int(np.asarray(data.get("tensor_dict_timestamp", [])).shape[0]),
        "num_cycles": int(np.asarray(data.get("cycle_timestamp_ms", [])).shape[0]) if enhanced else 0,
        "gt_road_request_in_formal_window": gt_formal_req,
        "modes": mode_summaries,
    }


def evaluate_model_on_npz_pool(
    npz_paths: Sequence[Path],
    model_spec: str,
    *,
    label: str,
    modes: Sequence[str] = ("onboard_full", "model_only"),
    device: str = "cpu",
    bridge_so: Optional[Path] = None,
    workers: int = 8,
    enable_uncertain_delay: bool = False,
    threshold_override: Optional[float] = None,
    verify_parity: bool = False,
) -> Dict[str, Any]:
    """Run multi-process parallel inference + 10Hz state-machine replay across ``npz_paths``."""
    t0 = time.perf_counter()
    # Pre-build native IFX bridge once in parent before forking workers
    if model_spec != "recorded" and (".ifxmodel" in Path(model_spec).name.lower()):
        from .model_runner import ensure_ifx_bridge_library

        resolved_so = ensure_ifx_bridge_library(bridge_so)
    else:
        resolved_so = bridge_so

    # Read model metadata once
    model_sha256: Optional[str] = None
    if model_spec != "recorded":
        mp = Path(model_spec).expanduser().resolve()
        h = hashlib.sha256()
        with mp.open("rb") as fp:
            for chunk in iter(lambda: fp.read(4 * 1024 * 1024), b""):
                h.update(chunk)
        model_sha256 = h.hexdigest()
        model_path_resolved = str(mp)
    else:
        model_path_resolved = "recorded"

    eff_workers = 1 if device == "cuda" else max(1, min(int(workers), len(npz_paths)))
    path_strs = [str(p) for p in npz_paths]
    mode_tuple = tuple(modes)

    if eff_workers == 1:
        _init_eval_worker(
            model_path_resolved,
            device,
            str(resolved_so) if resolved_so else None,
            mode_tuple,
            enable_uncertain_delay,
            threshold_override,
            verify_parity,
        )
        try:
            case_rows = [_eval_one_npz_in_worker(p) for p in path_strs]
        finally:
            if _WORKER_RUNNER is not None:
                _WORKER_RUNNER.close()
    else:
        with ProcessPoolExecutor(
            max_workers=eff_workers,
            initializer=_init_eval_worker,
            initargs=(
                model_path_resolved,
                device,
                str(resolved_so) if resolved_so else None,
                mode_tuple,
                enable_uncertain_delay,
                threshold_override,
                verify_parity,
            ),
        ) as pool:
            case_rows = list(pool.map(_eval_one_npz_in_worker, path_strs, chunksize=8))

    case_rows.sort(key=lambda r: r["case_id"])
    elapsed = round(time.perf_counter() - t0, 3)
    backend = (
        next(iter(case_rows[0]["modes"].values()))["backend"]
        if case_rows and case_rows[0]["modes"]
        else ("recorded" if model_spec == "recorded" else "unknown")
    )
    return {
        "label": label,
        "model_path": model_path_resolved,
        "model_sha256": model_sha256,
        "backend": backend,
        "device": device,
        "workers": eff_workers,
        "elapsed_sec": elapsed,
        "cases_evaluated": len(case_rows),
        "cases": case_rows,
    }


# ---------------------------------------------------------------------------
# Exact Frozen 1030 TE7 P/R & Paired Transition Calculators (SQL-verified)
# ---------------------------------------------------------------------------


def compute_1030_metrics(
    rows: Sequence[Mapping[str, Any]],
    decisions: Mapping[str, Optional[bool]],
) -> Dict[str, Any]:
    """Compute both Unified Binary P/R and Strict GOOD-only P/R with SQL cross-check."""
    known = [r for r in rows if decisions.get(r["issue_id"]) is not None]
    requested = [r for r in known if decisions.get(r["issue_id"]) is True]
    unknown = [r for r in rows if decisions.get(r["issue_id"]) is None]

    # 1. Unified binary: Positive == (label != '误触发')
    tp_bin = sum(r["label"] != "误触发" for r in requested)
    fp_bin = sum(r["label"] == "误触发" for r in requested)
    fn_bin = sum(r["label"] != "误触发" and not decisions[r["issue_id"]] for r in known)
    tn_bin = sum(r["label"] == "误触发" and not decisions[r["issue_id"]] for r in known)
    p_den = len(requested)
    r_known_den = sum(r["label"] != "误触发" for r in known)
    r_full_den = sum(r["label"] != "误触发" for r in rows)

    # 2. Strict GOOD-only P numerator: label in GOOD_LABELS
    p_good_num = sum(r["label"] in GOOD_LABELS for r in requested)
    lit_correct_req = sum(r["label"] == "正确触发" for r in requested)

    unk_pos = sum(r["label"] != "误触发" for r in unknown)
    unk_neg = sum(r["label"] == "误触发" for r in unknown)
    unk_good = sum(r["label"] in GOOD_LABELS for r in unknown)
    unk_not_good = sum(r["label"] not in GOOD_LABELS for r in unknown)

    # Independent SQL verification
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE outcomes(label TEXT, requested INTEGER)")
    db.executemany(
        "INSERT INTO outcomes VALUES(?, ?)",
        [(r["label"], None if decisions.get(r["issue_id"]) is None else int(bool(decisions[r["issue_id"]]))) for r in rows],
    )
    sql_counts = db.execute(
        """SELECT
            COALESCE(SUM(requested=1 AND label!='误触发'), 0),
            COALESCE(SUM(requested=1 AND label='误触发'), 0),
            COALESCE(SUM(requested=0 AND label!='误触发'), 0),
            COALESCE(SUM(requested=0 AND label='误触发'), 0),
            COALESCE(SUM(requested=1 AND label IN ('成功','失败','无需协助','限制使用')), 0),
            COALESCE(SUM(requested=1), 0),
            COALESCE(SUM(requested IS NOT NULL AND label!='误触发'), 0)
        FROM outcomes"""
    ).fetchone()
    db.close()
    assert list(sql_counts) == [tp_bin, fp_bin, fn_bin, tn_bin, p_good_num, p_den, r_known_den]

    ratio = lambda n, d: (n / d) if d else None
    p_bin = ratio(tp_bin, p_den)
    r_known = ratio(tp_bin, r_known_den)
    f1_bin = (2 * p_bin * r_known / (p_bin + r_known)) if (p_bin and r_known) else None

    return {
        "issues": len(rows),
        "known": len(known),
        "unknown": len(unknown),
        "unknown_issue_ids": sorted(r["issue_id"] for r in unknown),
        "unified_binary": {
            "TP": tp_bin,
            "FP": fp_bin,
            "FN": fn_bin,
            "TN": tn_bin,
            "P_numerator": tp_bin,
            "P_denominator": p_den,
            "R_numerator": tp_bin,
            "R_known_denominator": r_known_den,
            "R_full_denominator": r_full_den,
            "P": p_bin,
            "R_known": r_known,
            "F1_known": f1_bin,
            "P_full_bounds": [ratio(tp_bin, p_den + unk_neg), ratio(tp_bin + unk_pos, p_den + unk_pos)],
            "R_full_bounds": [ratio(tp_bin, r_full_den), ratio(tp_bin + unk_pos, r_full_den)],
        },
        "strict_good_p": {
            "P_numerator": p_good_num,
            "P_denominator": p_den,
            "R_numerator": tp_bin,
            "R_known_denominator": r_known_den,
            "R_full_denominator": r_full_den,
            "P": ratio(p_good_num, p_den),
            "R_known": r_known,
            "P_full_bounds": [
                ratio(p_good_num, p_den + unk_not_good),
                ratio(p_good_num + unk_good, p_den + unk_good),
            ],
            "R_full_bounds": [ratio(tp_bin, r_full_den), ratio(tp_bin + unk_pos, r_full_den)],
            "literal_correct_trigger_requests": lit_correct_req,
            "literal_false_trigger_requests": fp_bin,
        },
        "independently_SQL_checked": True,
    }


def compute_paired_diff(
    rows: Sequence[Mapping[str, Any]],
    base_dec: Mapping[str, Optional[bool]],
    feat_dec: Mapping[str, Optional[bool]],
) -> Dict[str, Any]:
    """Compute exact paired Base -> Feature transitions across common known issues."""
    paired = [
        r
        for r in rows
        if base_dec.get(r["issue_id"]) is not None and feat_dec.get(r["issue_id"]) is not None
    ]
    before = compute_1030_metrics(paired, base_dec)
    after = compute_1030_metrics(paired, feat_dec)

    tp_restored = [
        r for r in paired if r["label"] != "误触发" and not base_dec[r["issue_id"]] and feat_dec[r["issue_id"]]
    ]
    tp_lost = [
        r for r in paired if r["label"] != "误触发" and base_dec[r["issue_id"]] and not feat_dec[r["issue_id"]]
    ]
    fp_added = [
        r for r in paired if r["label"] == "误触发" and not base_dec[r["issue_id"]] and feat_dec[r["issue_id"]]
    ]
    fp_removed = [
        r for r in paired if r["label"] == "误触发" and base_dec[r["issue_id"]] and not feat_dec[r["issue_id"]]
    ]

    fine_groups: Dict[str, Dict[str, Any]] = {}
    for grp_name, pred in (
        ("GOOD", lambda r: r["label"] in GOOD_LABELS),
        ("literal_correct", lambda r: r["label"] == "正确触发"),
        ("false_label", lambda r: r["label"] == "误触发"),
    ):
        for a, b in ((False, True), (True, False)):
            ids = sorted(
                r["issue_id"]
                for r in paired
                if pred(r) and bool(base_dec[r["issue_id"]]) is a and bool(feat_dec[r["issue_id"]]) is b
            )
            fine_groups[f"{grp_name}:{int(a)}->{int(b)}"] = {"count": len(ids), "issue_ids": ids}

    total_changed = len(tp_restored) + len(tp_lost) + len(fp_added) + len(fp_removed)
    assert total_changed == sum(bool(base_dec[r["issue_id"]]) != bool(feat_dec[r["issue_id"]]) for r in paired)

    return {
        "population": len(rows),
        "paired_known": len(paired),
        "same_decisions": len(paired) - total_changed,
        "changed_decisions": total_changed,
        "transitions": {
            "tp_restored": {
                "count": len(tp_restored),
                "labels": dict(Counter(r["label"] for r in tp_restored)),
                "issue_ids": sorted(r["issue_id"] for r in tp_restored),
            },
            "tp_lost": {
                "count": len(tp_lost),
                "labels": dict(Counter(r["label"] for r in tp_lost)),
                "issue_ids": sorted(r["issue_id"] for r in tp_lost),
            },
            "fp_added": {
                "count": len(fp_added),
                "labels": dict(Counter(r["label"] for r in fp_added)),
                "issue_ids": sorted(r["issue_id"] for r in fp_added),
            },
            "fp_removed": {
                "count": len(fp_removed),
                "labels": dict(Counter(r["label"] for r in fp_removed)),
                "issue_ids": sorted(r["issue_id"] for r in fp_removed),
            },
        },
        "fine_grained_changes": fine_groups,
        "before": before,
        "after": after,
        "delta_unified_P": (
            (after["unified_binary"]["P"] - before["unified_binary"]["P"])
            if (after["unified_binary"]["P"] is not None and before["unified_binary"]["P"] is not None)
            else None
        ),
        "delta_R_known": (
            (after["unified_binary"]["R_known"] - before["unified_binary"]["R_known"])
            if (after["unified_binary"]["R_known"] is not None and before["unified_binary"]["R_known"] is not None)
            else None
        ),
        "delta_strict_good_P": (
            (after["strict_good_p"]["P"] - before["strict_good_p"]["P"])
            if (after["strict_good_p"]["P"] is not None and before["strict_good_p"]["P"] is not None)
            else None
        ),
    }


def _extract_decision_map(
    all_issue_ids: Sequence[str],
    arm_eval: Mapping[str, Any],
    *,
    mode: str = "onboard_full",
    use_formal_window: bool = True,
) -> Dict[str, Optional[bool]]:
    out: Dict[str, Optional[bool]] = {iid: None for iid in all_issue_ids}
    key = "triggered_in_formal_window" if use_formal_window else "triggered_request"
    for row in arm_eval["cases"]:
        iid = row["case_id"]
        if iid in out and mode in row["modes"]:
            m_dict = row["modes"][mode]
            out[iid] = bool(m_dict.get(key, m_dict["triggered_request"]))
    return out


def run_1030_evaluation_and_diff(
    npz_dir: Path,
    out_dir: Path,
    *,
    base_model: str,
    feature_model: str,
    include_recorded: bool = True,
    extra_models: Sequence[Tuple[str, str]] = (),
    all1563_jsonl: Path = DEFAULT_ALL1563_REQUESTS,
    cohort_json: Path = DEFAULT_COHORT_JSON,
    orion_compare_json: Optional[Path] = DEFAULT_ORION_COMPARE_JSON,
    device: str = "cpu",
    workers: int = 8,
    modes: Sequence[str] = ("onboard_full", "onboard_strict_road", "model_only"),
) -> Dict[str, Any]:
    """Run full 1030 evaluation for Base & Feature models and write JSON/MD/CSV artifacts."""
    npz_dir = Path(npz_dir).expanduser().resolve()
    if (npz_dir / "npz").is_dir():
        npz_dir = npz_dir / "npz"
    npz_paths = sorted(npz_dir.glob("*.npz"))
    if not npz_paths:
        raise FileNotFoundError(f"No .npz files found under {npz_dir}")

    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows = [
        json.loads(line)
        for line in Path(all1563_jsonl).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {r["issue_id"]: r for r in all_rows}
    all_issue_ids = [r["issue_id"] for r in all_rows]
    review_rows = [r for r in all_rows if r["review_eligible"]]

    cohort_data = json.loads(Path(cohort_json).read_text(encoding="utf-8"))
    cohort_sets = {
        "all_business": {r["issue_id"] for r in review_rows},
        "traffic_EOL": set(cohort_data["groups"]["traffic_EOL"]["issue_ids"]),
        "non_traffic_business": {r["issue_id"] for r in review_rows}
        - set(cohort_data["groups"]["traffic_EOL"]["issue_ids"]),
        "NPZ_business_common": set(cohort_data["groups"]["NPZ_business_common"]["issue_ids"]),
    }

    arms_to_run: List[Tuple[str, str, bool]] = []
    if include_recorded:
        arms_to_run.append(("road_recorded", "recorded", True))
    arms_to_run.append(("base_v89", base_model, True))
    arms_to_run.append(("feature_cr7028995_v122", feature_model, False))
    for extra_lbl, extra_path in extra_models:
        arms_to_run.append((extra_lbl, extra_path, False))

    arm_evals: Dict[str, Dict[str, Any]] = {}
    for lbl, spec, check_par in arms_to_run:
        arm_modes = ("onboard_strict_road", "onboard_full") if spec == "recorded" else tuple(modes)
        print(f"[eval-1030] Evaluating arm '{lbl}' ({spec}) across {len(npz_paths)} NPZs...", flush=True)
        arm_evals[lbl] = evaluate_model_on_npz_pool(
            npz_paths,
            spec,
            label=lbl,
            modes=arm_modes,
            device=device,
            workers=workers,
            verify_parity=check_par,
        )
        print(f"[eval-1030] Finished '{lbl}' in {arm_evals[lbl]['elapsed_sec']:.2f}s", flush=True)

    # Extract decision maps (formal window [scenario_start_timestamp, scenario_end_timestamp])
    decisions_full: Dict[str, Dict[str, Optional[bool]]] = {}
    decisions_strict_road: Dict[str, Dict[str, Optional[bool]]] = {}
    decisions_model_only: Dict[str, Dict[str, Optional[bool]]] = {}
    for lbl, ev in arm_evals.items():
        if lbl == "road_recorded":
            decisions_full[lbl] = _extract_decision_map(
                all_issue_ids, ev, mode="onboard_strict_road", use_formal_window=True
            )
        else:
            decisions_full[lbl] = _extract_decision_map(
                all_issue_ids, ev, mode="onboard_full", use_formal_window=True
            )
        if any("onboard_strict_road" in r["modes"] for r in ev["cases"]):
            decisions_strict_road[lbl] = _extract_decision_map(
                all_issue_ids, ev, mode="onboard_strict_road", use_formal_window=True
            )
        if any("model_only" in r["modes"] for r in ev["cases"]):
            decisions_model_only[lbl] = _extract_decision_map(
                all_issue_ids, ev, mode="model_only", use_formal_window=True
            )

    # Road /planning/assist_request ground-truth map + historical Orion Base Sim map
    road_gt_map: Dict[str, Optional[bool]] = {iid: None for iid in all_issue_ids}
    first_arm_cases = next(iter(arm_evals.values()))["cases"]
    for c_row in first_arm_cases:
        if c_row["case_id"] in road_gt_map:
            road_gt_map[c_row["case_id"]] = c_row["gt_road_request_in_formal_window"]
    decisions_full["road_bag_assist_request_gt"] = road_gt_map
    decisions_full["orion_sim_base_q2"] = {r["issue_id"]: r["actual_requests"]["base"] for r in all_rows}

    # Compute metrics across all 4 business cohorts for every arm
    cohort_metrics_full: Dict[str, Dict[str, Any]] = {}
    for lbl, dec in decisions_full.items():
        cohort_metrics_full[lbl] = {
            c_name: compute_1030_metrics([r for r in review_rows if r["issue_id"] in c_ids], dec)
            for c_name, c_ids in cohort_sets.items()
        }

    cohort_metrics_strict_road: Dict[str, Dict[str, Any]] = {}
    for lbl, dec in decisions_strict_road.items():
        cohort_metrics_strict_road[lbl] = {
            c_name: compute_1030_metrics([r for r in review_rows if r["issue_id"] in c_ids], dec)
            for c_name, c_ids in cohort_sets.items()
        }

    cohort_metrics_model_only: Dict[str, Dict[str, Any]] = {}
    for lbl, dec in decisions_model_only.items():
        cohort_metrics_model_only[lbl] = {
            c_name: compute_1030_metrics([r for r in review_rows if r["issue_id"] in c_ids], dec)
            for c_name, c_ids in cohort_sets.items()
        }

    # Paired diffs
    paired_base_vs_feature = {
        c_name: compute_paired_diff(
            [r for r in review_rows if r["issue_id"] in c_ids],
            decisions_full["base_v89"],
            decisions_full["feature_cr7028995_v122"],
        )
        for c_name, c_ids in cohort_sets.items()
    }
    paired_base_vs_orion_base = compute_paired_diff(
        review_rows,
        decisions_full["orion_sim_base_q2"],
        decisions_full["base_v89"],
    )
    paired_recorded_vs_road_gt = (
        compute_paired_diff(
            review_rows,
            decisions_full["road_bag_assist_request_gt"],
            decisions_full["road_recorded"],
        )
        if "road_recorded" in decisions_full
        else None
    )

    # Cycle-by-cycle parity summary for road_recorded & base_v89
    parity_summaries: Dict[str, Any] = {}
    for lbl in ("road_recorded", "base_v89"):
        if lbl not in arm_evals:
            continue
        cases = arm_evals[lbl]["cases"]
        tot_cyc = 0
        u_match = 0
        m_match = 0
        r_match = 0
        q_match = 0
        exact_cases = 0
        for c_row in cases:
            par = c_row["modes"].get("onboard_strict_road", c_row["modes"].get("onboard_full", {})).get("parity")
            if par:
                n_c = int(par["total_cycles"])
                tot_cyc += n_c
                u_ok = int(str(par["unstuck_status_matches"]).split("/")[0])
                m_ok = int(str(par["by_model_matches"]).split("/")[0])
                r_ok = int(str(par["rule_decision_matches"]).split("/")[0])
                q_ok = int(str(par["queue_len_matches"]).split("/")[0])
                u_match += u_ok
                m_match += m_ok
                r_match += r_ok
                q_match += q_ok
                if u_ok == n_c and m_ok == n_c and r_ok == n_c and q_ok == n_c:
                    exact_cases += 1
        parity_summaries[lbl] = {
            "cases_checked": len(cases),
            "discrete_state_exact_cases": exact_cases,
            "total_cycles": tot_cyc,
            "unstuck_status_match_rate": round(u_match / max(1, tot_cyc), 6),
            "by_model_match_rate": round(m_match / max(1, tot_cyc), 6),
            "rule_decision_match_rate": round(r_match / max(1, tot_cyc), 6),
            "queue_len_match_rate": round(q_match / max(1, tot_cyc), 6),
            "unstuck_status_matches": f"{u_match}/{tot_cyc}",
            "by_model_matches": f"{m_match}/{tot_cyc}",
            "rule_decision_matches": f"{r_match}/{tot_cyc}",
            "queue_len_matches": f"{q_match}/{tot_cyc}",
        }

    # Historical Orion Job 50509481 (CR 7028995 Patchset 4 E21) reference if present
    orion_e21_ref: Optional[Dict[str, Any]] = None
    if orion_compare_json and Path(orion_compare_json).is_file():
        oc = json.loads(Path(orion_compare_json).read_text(encoding="utf-8"))
        orion_e21_ref = {
            "source_file": str(Path(orion_compare_json).resolve()),
            "e21_job": oc.get("jobs", {}).get("E21"),
            "e21_vs_q2_pair": oc.get("pairs", {}).get("E21", {}).get("Q2"),
        }

    # Write per-case JSONL
    per_case_jsonl = out_dir / "per_case_outcomes.jsonl"
    base_by_case = {r["case_id"]: r for r in arm_evals["base_v89"]["cases"]}
    feat_by_case = {r["case_id"]: r for r in arm_evals["feature_cr7028995_v122"]["cases"]}
    rec_by_case = (
        {r["case_id"]: r for r in arm_evals["road_recorded"]["cases"]}
        if "road_recorded" in arm_evals
        else {}
    )
    with per_case_jsonl.open("w", encoding="utf-8") as fp:
        for r in all_rows:
            iid = r["issue_id"]
            b_row = base_by_case.get(iid)
            f_row = feat_by_case.get(iid)
            rec_row = rec_by_case.get(iid)
            line_obj = {
                "issue_id": iid,
                "label": r["label"],
                "label_source": r["label_source"],
                "review_eligible": r["review_eligible"],
                "in_traffic_EOL": iid in cohort_sets["traffic_EOL"],
                "in_NPZ_business_common": iid in cohort_sets["NPZ_business_common"],
                "orion_sim_base_q2": r["actual_requests"]["base"],
                "road_bag_assist_request_gt": road_gt_map.get(iid),
                "offline_recorded_onboard_full": decisions_full.get("road_recorded", {}).get(iid),
                "offline_base_v89_onboard_full": decisions_full["base_v89"].get(iid),
                "offline_feature_cr7028995_v122_onboard_full": decisions_full["feature_cr7028995_v122"].get(iid),
                "offline_base_v89_strict_road": decisions_strict_road.get("base_v89", {}).get(iid),
                "offline_feature_cr7028995_v122_strict_road": decisions_strict_road.get(
                    "feature_cr7028995_v122", {}
                ).get(iid),
                "offline_base_v89_model_only": decisions_model_only.get("base_v89", {}).get(iid),
                "offline_feature_cr7028995_v122_model_only": decisions_model_only.get(
                    "feature_cr7028995_v122", {}
                ).get(iid),
                "base_max_score": (
                    b_row["modes"]["onboard_full"]["max_main_score"] if b_row else None
                ),
                "feature_max_score": (
                    f_row["modes"]["onboard_full"]["max_main_score"] if f_row else None
                ),
                "num_tensor_frames": b_row["num_tensor_frames"] if b_row else None,
                "num_cycles": b_row["num_cycles"] if b_row else None,
                "recorded_parity_passed": (
                    rec_row["modes"].get("onboard_strict_road", {}).get("parity", {}).get("passed")
                    if rec_row
                    else None
                ),
            }
            fp.write(json.dumps(line_obj, ensure_ascii=False) + "\n")

    # Write changed cases CSV (Base v89 vs Feature CR 7028995 v122 on review_eligible business set)
    changed_csv = out_dir / "changed_cases_base_vs_feature.csv"
    with changed_csv.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "issue_id",
                "label",
                "label_source",
                "cohort",
                "base_v89_request",
                "feature_v122_request",
                "transition_type",
                "base_max_score",
                "feature_max_score",
                "orion_sim_base_q2",
            ],
        )
        writer.writeheader()
        for r in review_rows:
            iid = r["issue_id"]
            b_val = decisions_full["base_v89"].get(iid)
            f_val = decisions_full["feature_cr7028995_v122"].get(iid)
            if b_val is None or f_val is None or b_val == f_val:
                continue
            is_pos = r["label"] != "误触发"
            if is_pos and not b_val and f_val:
                t_type = "tp_restored"
            elif is_pos and b_val and not f_val:
                t_type = "tp_lost"
            elif (not is_pos) and (not b_val) and f_val:
                t_type = "fp_added"
            else:
                t_type = "fp_removed"
            b_row = base_by_case.get(iid)
            f_row = feat_by_case.get(iid)
            writer.writerow({
                "issue_id": iid,
                "label": r["label"],
                "label_source": r["label_source"],
                "cohort": "traffic_EOL" if iid in cohort_sets["traffic_EOL"] else "non_traffic_business",
                "base_v89_request": b_val,
                "feature_v122_request": f_val,
                "transition_type": t_type,
                "base_max_score": b_row["modes"]["onboard_full"]["max_main_score"] if b_row else None,
                "feature_max_score": f_row["modes"]["onboard_full"]["max_main_score"] if f_row else None,
                "orion_sim_base_q2": r["actual_requests"]["base"],
            })

    summary_payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "npz_dir": str(npz_dir),
        "scenarios_evaluated": len(npz_paths),
        "physical_issues": len(all_rows),
        "review_eligible_business_issues": len(review_rows),
        "full_recall_denominator": 784,
        "models": {
            lbl: {
                k: v for k, v in ev.items() if k != "cases"
            }
            for lbl, ev in arm_evals.items()
        },
        "parity_summaries": parity_summaries,
        "cohort_metrics_onboard_full": cohort_metrics_full,
        "cohort_metrics_onboard_strict_road": cohort_metrics_strict_road,
        "cohort_metrics_model_only": cohort_metrics_model_only,
        "paired_diff_base_v89_vs_feature_cr7028995_v122": paired_base_vs_feature,
        "paired_diff_orion_sim_base_vs_offline_base_v89": paired_base_vs_orion_base,
        "paired_diff_road_gt_vs_offline_recorded": paired_recorded_vs_road_gt,
        "orion_sim_cr7028995_e21_job_50509481_reference": orion_e21_ref,
        "artifacts": {
            "per_case_jsonl": str(per_case_jsonl),
            "changed_csv": str(changed_csv),
        },
    }
    summary_json = out_dir / "SUMMARY.json"
    summary_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Render clean Markdown report
    md_lines = _render_markdown_report(summary_payload)
    report_md = out_dir / "REPORT.md"
    report_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    summary_payload["artifacts"]["summary_json"] = str(summary_json)
    summary_payload["artifacts"]["report_md"] = str(report_md)
    return summary_payload


def _fmt_pct(val: Optional[float]) -> str:
    return "-" if val is None else f"{val * 100:.2f}%"


def _render_markdown_report(summary: Mapping[str, Any]) -> List[str]:
    cm = summary["cohort_metrics_onboard_full"]
    diff_all = summary["paired_diff_base_v89_vs_feature_cr7028995_v122"]["all_business"]
    tr = diff_all["transitions"]
    lines = [
        "# Release 1030 Offline Onboard NPZ Full Evaluation & Diff Report (Base `v89` vs CR `7028995` `v122`)",
        "",
        f"- **Scenarios evaluated**: `{summary['scenarios_evaluated']} / 1561` executable (`1563` physical issues; `1415` review-eligible business issues; full recall denominator `784`)",
        f"- **Base model**: `{summary['models']['base_v89']['model_path']}` (`sha256={summary['models']['base_v89']['model_sha256'][:16]}...`, `{summary['models']['base_v89']['elapsed_sec']}s`)",
        f"- **Feature model (CR 7028995)**: `{summary['models']['feature_cr7028995_v122']['model_path']}` (`sha256={summary['models']['feature_cr7028995_v122']['model_sha256'][:16]}...`, `{summary['models']['feature_cr7028995_v122']['elapsed_sec']}s`)",
        "",
        "## 1. All-Business (`1,415` Issues) Full-Chain Comparison (Offline NPZ vs Orion Sim)",
        "",
        "| Arm / Source | Known | TP | FP | FN | TN | Unified P (`TP/Req`) | Known R (`TP/Known+`) | Strict GOOD P |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    arm_order = [
        ("road_bag_assist_request_gt", "Road Bag `/planning/assist_request` GT"),
        ("road_recorded", "Offline NPZ (`recorded` car scores)"),
        ("base_v89", "Offline NPZ Base (`v89` Q2 x86 IFX)"),
        ("orion_sim_base_q2", "Orion Sim Base (`Jobs 50119729+50121701`)"),
        ("feature_cr7028995_v122", "Offline NPZ Feature (`CR 7028995 v122` x86 IFX)"),
    ]
    for key, title in arm_order:
        if key not in cm:
            continue
        m = cm[key]["all_business"]
        ub = m["unified_binary"]
        sg = m["strict_good_p"]
        lines.append(
            f"| {title} | {m['known']} | {ub['TP']} | {ub['FP']} | {ub['FN']} | {ub['TN']} | "
            f"{ub['TP']}/{ub['P_denominator']} (**{_fmt_pct(ub['P'])}**) | "
            f"{ub['R_numerator']}/{ub['R_known_denominator']} (**{_fmt_pct(ub['R_known'])}**) | "
            f"{sg['P_numerator']}/{sg['P_denominator']} ({_fmt_pct(sg['P'])}) |"
        )
    cm_strict = summary.get("cohort_metrics_onboard_strict_road") or {}
    if "feature_cr7028995_v122" in cm_strict:
        ms = cm_strict["feature_cr7028995_v122"]["all_business"]
        ubs = ms["unified_binary"]
        sgs = ms["strict_good_p"]
        lines.append(
            f"| Offline NPZ Feature (`v122`, `onboard_strict_road`) | {ms['known']} | {ubs['TP']} | {ubs['FP']} | "
            f"{ubs['FN']} | {ubs['TN']} | {ubs['TP']}/{ubs['P_denominator']} (**{_fmt_pct(ubs['P'])}**) | "
            f"{ubs['R_numerator']}/{ubs['R_known_denominator']} (**{_fmt_pct(ubs['R_known'])}**) | "
            f"{sgs['P_numerator']}/{sgs['P_denominator']} ({_fmt_pct(sgs['P'])}) |"
        )
    orion_ref = summary.get("orion_sim_cr7028995_e21_job_50509481_reference") or {}
    if orion_ref.get("e21_job"):
        eb = orion_ref["e21_job"]["business"]
        req_n = eb["tp"] + eb["fp"]
        pos_n = eb["tp"] + eb["fn"]
        lines.append(
            f"| Orion Sim Feature (`Job 50509481` CR 7028995 E21) | {eb['known']} | {eb['tp']} | {eb['fp']} | "
            f"{eb['fn']} | {eb['tn']} | {eb['tp']}/{req_n} (**{_fmt_pct(eb['precision'])}**) | "
            f"{eb['tp']}/{pos_n} (**{_fmt_pct(eb['recall'])}**) | - |"
        )

    lines.extend([
        "",
        "## 2. Subgroup Breakdown (`Base v89` vs `Feature CR 7028995 v122`, `onboard_full`)",
        "",
        "| Cohort | Issues | Base `v89` Unified P / Known R | Feature `v122` Unified P / Known R | TP Restored / Lost | FP Added / Removed |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for c_key, c_title in (
        ("all_business", "All Business (`1,415`)"),
        ("traffic_EOL", "Traffic Light / EOL (`400`)"),
        ("non_traffic_business", "Non-Traffic Business (`1,015`)"),
        ("NPZ_business_common", "Legacy Cropped-NPZ Common (`974`)"),
    ):
        bm = cm["base_v89"][c_key]["unified_binary"]
        fm = cm["feature_cr7028995_v122"][c_key]["unified_binary"]
        d = summary["paired_diff_base_v89_vs_feature_cr7028995_v122"][c_key]["transitions"]
        lines.append(
            f"| {c_title} | {cm['base_v89'][c_key]['issues']} | "
            f"{_fmt_pct(bm['P'])} / {_fmt_pct(bm['R_known'])} (`{bm['TP']}/{bm['P_denominator']}`) | "
            f"{_fmt_pct(fm['P'])} / {_fmt_pct(fm['R_known'])} (`{fm['TP']}/{fm['P_denominator']}`) | "
            f"`+{d['tp_restored']['count']} / -{d['tp_lost']['count']}` | "
            f"`+{d['fp_added']['count']} / -{d['fp_removed']['count']}` |"
        )

    lines.extend([
        "",
        "## 3. Paired Transition Summary (`Base v89` -> `Feature CR 7028995 v122`, All Business)",
        "",
        f"- **Paired known issues**: `{diff_all['paired_known']}` (`same={diff_all['same_decisions']}`, `changed={diff_all['changed_decisions']}`)",
        f"- **TP restored (`0 -> 1`)**: `+{tr['tp_restored']['count']}` (`{tr['tp_restored']['labels']}`)",
        f"- **TP lost (`1 -> 0`)**: `-{tr['tp_lost']['count']}` (`{tr['tp_lost']['labels']}`)",
        f"- **FP added (`0 -> 1`)**: `+{tr['fp_added']['count']}`",
        f"- **FP removed (`1 -> 0`)**: `-{tr['fp_removed']['count']}`",
    ])
    return lines
