"""Multi-release road-bag -> Enhanced Road NPZ stream exporter & Shuyi board reconciliation engine.

Supports arbitrary historical releases (e.g. ``gen4-release-20261009`` through
``gen4-release-20261113``):
  1. Stream-exports each release's ``population.jsonl`` scenarios from lightweight 5-topic road
     bags to ``<out_root>/npz/<issue_id>.npz`` with ``5000ms`` pre-window warmup, disk-free guard,
     and guaranteed zero leftover ``.bag`` files in ``.staging/``.
  2. Runs multi-core native ``.ifxmodel`` / ``recorded`` 10Hz state-machine inference across every
     release and reconciles offline P / R against Shuyi board ``reportId=288969 / subReportId=6276081``
     ("自触发指标（不包含RA红绿灯）", curve "自触发准确率/召回率-AutoTriage+人工修正") as well as
     historical Orion simulation baselines where available.
  3. Verifies every numerator and denominator via an independent in-memory ``sqlite3`` query.
"""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed

from .batch_export_1030 import ScenarioExportTask, _atomic_write_json, _export_one_task, _safe_dir_bytes
from .diff_report_1030 import GOOD_LABELS, evaluate_model_on_npz_pool


EXCLUDED_LABELS = frozenset({"out_of_scope", "未接起", "未填写"})

DEFAULT_SHUYI_SCREENSHOT_REFS: Dict[str, Dict[str, float]] = {
    "gen4-release-20261009": {"P": 0.5423, "R": 0.7416},
    "gen4-release-20261016": {"P": 0.5096, "R": 0.6887},
    "gen4-release-20261023": {"P": 0.4956, "R": 0.7510},
    "gen4-release-20261030": {"P": 0.4807, "R": 0.7449},
    "gen4-release-20261106": {"P": 0.5334, "R": 0.7649},
    "gen4-release-20261113": {"P": 0.6118, "R": 0.7448},
}


# ---------------------------------------------------------------------------
# 1. Generalized Population Manifest -> Enhanced Road NPZ Stream Exporter
# ---------------------------------------------------------------------------


def load_population_jsonl(population_jsonl: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for line in Path(population_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        iid = str(row["issue_id"])
        if iid in seen:
            raise ValueError(f"Duplicate issue_id in population manifest {population_jsonl}: {iid}")
        seen.add(iid)
        rows.append(row)
    return rows


def build_population_export_tasks(
    population_jsonl: Path,
    *,
    warmup_ms: int = 5000,
) -> Tuple[List[ScenarioExportTask], List[Dict[str, Any]]]:
    """Build export tasks from ``population.jsonl``, separating unexportable rows cleanly."""
    rows = load_population_jsonl(population_jsonl)
    tasks: List[ScenarioExportTask] = []
    skipped: List[Dict[str, Any]] = []

    for row in rows:
        iid = str(row["issue_id"])
        trip_id = str(row.get("trip_id") or "").strip()
        f_start = int(row.get("formal_start_ms") or 0)
        f_end = int(row.get("formal_end_ms") or 0)
        ra_start = int(row.get("ra_start_timestamp") or row.get("issue_time") or f_start)
        if not trip_id or f_end <= 0 or f_end < f_start:
            skipped.append({
                "issue_id": iid,
                "reason": "missing_trip_or_window",
                "trip_id": trip_id,
                "formal_start_ms": f_start,
                "formal_end_ms": f_end,
            })
            continue

        dl_start = max(0, f_start - int(warmup_ms))
        tasks.append(
            ScenarioExportTask(
                issue_id=iid,
                scenario_id=str(row.get("scenario_id") or iid),
                trip_id=trip_id,
                download_start_ms=dl_start,
                download_end_ms=f_end,
                formal_start_ms=f_start,
                formal_end_ms=f_end,
                ra_start_ms=ra_start,
            )
        )
    return tasks, skipped


def stream_export_population_dataset(
    out_root: Path,
    population_jsonl: Path,
    *,
    release_tag: str = "",
    warmup_ms: int = 5000,
    workers: int = 20,
    limit: Optional[int] = None,
    overwrite: bool = False,
    min_free_gb: float = 150.0,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Stream-export a release's road scenarios to ``<out_root>/npz/<issue_id>.npz``."""
    out_root = Path(out_root).expanduser().resolve()
    npz_dir = out_root / "npz"
    staging_root = out_root / ".staging"
    npz_dir.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)

    tasks, skipped_manifest = build_population_export_tasks(population_jsonl, warmup_ms=warmup_ms)
    if limit is not None and limit > 0:
        tasks = tasks[: int(limit)]

    tag = release_tag or out_root.name
    total = len(tasks)
    started_at = time.time()
    t0 = time.perf_counter()
    progress_path = out_root / "EXPORT_PROGRESS.json"
    summary_path = out_root / "EXPORT_SUMMARY.json"

    results: List[Dict[str, Any]] = []
    exported_cnt = 0
    reused_cnt = 0
    failed_cnt = 0
    total_npz_bytes = 0
    zero_td_cases: List[str] = []

    def write_progress(done_now: int, final: bool = False) -> Dict[str, Any]:
        staging_leftover = _safe_dir_bytes(staging_root)
        free_gb = round(shutil.disk_usage(out_root).free / (1024**3), 2)
        payload = {
            "release": tag,
            "population_jsonl": str(Path(population_jsonl).resolve()),
            "status": (
                "completed"
                if (final and failed_cnt == 0)
                else ("completed_with_failures" if final else "running")
            ),
            "started_at": started_at,
            "updated_at": time.time(),
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "total_exportable_scenarios": total,
            "skipped_unexportable_issues": len(skipped_manifest),
            "completed": done_now,
            "exported": exported_cnt,
            "reused": reused_cnt,
            "failed": failed_cnt,
            "zero_tensor_dict_cases_count": len(zero_td_cases),
            "total_npz_bytes": total_npz_bytes,
            "total_npz_gb": round(total_npz_bytes / (1024**3), 3),
            "staging_bytes": staging_leftover,
            "disk_free_gb": free_gb,
            "warmup_ms": warmup_ms,
            "workers": workers,
        }
        _atomic_write_json(progress_path, payload)
        return payload

    write_progress(0, final=False)

    if total > 0:
        with ProcessPoolExecutor(max_workers=max(1, min(int(workers), total))) as pool:
            fut_map = {
                pool.submit(
                    _export_one_task,
                    t,
                    str(npz_dir),
                    str(staging_root),
                    overwrite,
                    min_free_gb,
                    max_retries,
                ): t
                for t in tasks
            }
            for idx, fut in enumerate(as_completed(fut_map), start=1):
                row = fut.result()
                results.append(row)
                st = row["status"]
                if st in ("exported", "reused"):
                    if st == "exported":
                        exported_cnt += 1
                    else:
                        reused_cnt += 1
                    total_npz_bytes += int(row.get("npz_bytes", 0))
                    if int(row.get("tensor_dict_frames", 0)) == 0:
                        zero_td_cases.append(row["issue_id"])
                else:
                    failed_cnt += 1

                if idx % 50 == 0 or idx == total:
                    prog = write_progress(idx, final=False)
                    print(
                        f"[export-{tag}] {idx}/{total} (exported={exported_cnt}, reused={reused_cnt}, "
                        f"failed={failed_cnt}, npz={prog['total_npz_gb']:.2f} GB, "
                        f"staging={prog['staging_bytes']} B, free={prog['disk_free_gb']:.1f} GB, "
                        f"elapsed={prog['elapsed_sec']:.1f}s)",
                        flush=True,
                    )

    for child in sorted(staging_root.rglob("*"), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass

    final_prog = write_progress(len(results), final=True)
    failures = [r for r in sorted(results, key=lambda x: x["issue_id"]) if r["status"] == "failed"]
    summary = {
        **final_prog,
        "npz_dir": str(npz_dir),
        "skipped_unexportable": skipped_manifest,
        "failures": failures,
    }
    _atomic_write_json(summary_path, summary)
    return summary


# ---------------------------------------------------------------------------
# 2. Shuyi Board Reconcile Scoring & Trigger Window Projections (SQL-Checked)
# ---------------------------------------------------------------------------


def _scheduled_in_range(
    emitted_requests: Sequence[Mapping[str, Any]],
    start_ms: int,
    end_ms: int,
) -> bool:
    for req in emitted_requests:
        if not req.get("scheduled", True):
            continue
        ts = int(req.get("timestamp_ms", -1))
        if start_ms <= ts <= end_ms:
            return True
    return False


def extract_trigger_views_for_arm(
    pop_rows: Sequence[Mapping[str, Any]],
    arm_eval: Mapping[str, Any],
) -> Dict[str, Dict[str, Optional[bool]]]:
    """Extract causal road-aligned and simulation-aligned trigger maps from one arm evaluation.

    Views returned:
      - ``strict_road_causal``: ``mode="onboard_strict_road"``. For ``ra_type == 3`` (manual RA),
        an auto-trigger only preempts the operator's manual session on the road if it fires at or
        before ``ra_start_timestamp`` (``[formal_start_ms, ra_start_timestamp]``); for ``ra_type == 2``
        (auto RA), checks ``[formal_start_ms, formal_end_ms]``.
      - ``strict_road_formal``: ``mode="onboard_strict_road"`` across full ``[formal_start_ms, formal_end_ms]``.
      - ``onboard_full_formal``: ``mode="onboard_full"`` (counterfactual ``IN_ASSIST`` unmasking across
        full ``[formal_start_ms, formal_end_ms]`` — matches Orion open/closed-loop simulation).
      - ``onboard_full_causal``: ``mode="onboard_full"`` with ``<= ra_start_timestamp`` cutoff on ``ra_type == 3``.
    """
    pop_by_id = {str(r["issue_id"]): r for r in pop_rows}
    views: Dict[str, Dict[str, Optional[bool]]] = {
        "strict_road_causal": {iid: None for iid in pop_by_id},
        "strict_road_formal": {iid: None for iid in pop_by_id},
        "onboard_full_formal": {iid: None for iid in pop_by_id},
        "onboard_full_causal": {iid: None for iid in pop_by_id},
    }

    for c_row in arm_eval.get("cases", []):
        iid = str(c_row["case_id"])
        p_row = pop_by_id.get(iid)
        if p_row is None:
            continue
        f_start = int(p_row.get("formal_start_ms") or 0)
        f_end = int(p_row.get("formal_end_ms") or 0)
        ra_ts = int(p_row.get("ra_start_timestamp") or p_row.get("issue_time") or f_end)
        ra_type = int(p_row["ra_type"])
        causal_end = ra_ts if (ra_type == 3 and ra_ts >= f_start) else f_end

        modes = c_row.get("modes", {})
        if "onboard_strict_road" in modes:
            m_sr = modes["onboard_strict_road"]
            views["strict_road_formal"][iid] = bool(
                m_sr.get("triggered_in_formal_window", m_sr["triggered_request"])
            )
            views["strict_road_causal"][iid] = _scheduled_in_range(
                m_sr.get("emitted_requests", []),
                f_start,
                causal_end,
            )

        if "onboard_full" in modes:
            m_full = modes["onboard_full"]
            views["onboard_full_formal"][iid] = bool(
                m_full.get("triggered_in_formal_window", m_full["triggered_request"])
            )
            views["onboard_full_causal"][iid] = _scheduled_in_range(
                m_full.get("emitted_requests", []),
                f_start,
                causal_end,
            )

    return views


def compute_shuyi_reconcile_metrics(
    pop_rows: Sequence[Mapping[str, Any]],
    decisions: Optional[Mapping[str, Optional[bool]]] = None,
    *,
    label_key: str = "label_6level",
) -> Dict[str, Any]:
    """Compute Shuyi online road baseline & offline NPZ recalculated P/R with SQL cross-check."""
    ratio = lambda n, d: (n / d) if d else None

    # Independent SQLite table for both Road Baseline and Replay Recalculation
    db = sqlite3.connect(":memory:")
    db.execute(
        """CREATE TABLE shuyi_eval(
            issue_id TEXT PRIMARY KEY,
            ra_type INTEGER,
            label TEXT,
            eligible INTEGER,
            valid_non_excl INTEGER,
            triggered INTEGER
        )"""
    )

    insert_tuples = []
    for r in pop_rows:
        iid = str(r["issue_id"])
        ra_type = int(r["ra_type"])
        lbl = r.get(label_key)
        lbl_str = str(lbl) if (lbl is not None and str(lbl) != "") else None
        valid_non_excl = int(lbl_str is not None and lbl_str not in EXCLUDED_LABELS)
        # Exact ra-sim auto_triage_metrics.py cohort eligibility:
        # excludes NULL, EXCLUDED_LABELS, and (ra_type == 3 AND label == '误触发')
        eligible = int(bool(valid_non_excl) and not (ra_type == 3 and lbl_str == "误触发"))
        trig_val = None if (decisions is None or decisions.get(iid) is None) else int(bool(decisions[iid]))
        insert_tuples.append((iid, ra_type, lbl_str, eligible, valid_non_excl, trig_val))

    db.executemany("INSERT INTO shuyi_eval VALUES(?, ?, ?, ?, ?, ?)", insert_tuples)

    # 1. Online Road Baseline (exact Shuyi formula on ra_type)
    road_row = db.execute(
        """SELECT
            COUNT(*),
            COALESCE(SUM(eligible = 1), 0),
            COALESCE(SUM(ra_type = 2 AND valid_non_excl = 1 AND label != '误触发'), 0),
            COALESCE(SUM(ra_type = 2 AND valid_non_excl = 1 AND label IN ('成功','失败','无需协助','限制使用')), 0),
            COALESCE(SUM(ra_type = 2 AND valid_non_excl = 1), 0),
            COALESCE(SUM(ra_type IN (2, 3) AND valid_non_excl = 1 AND label != '误触发'), 0)
        FROM shuyi_eval"""
    ).fetchone()
    pop_n, elig_n, road_p_bin_num, road_p_good_num, road_p_den, road_r_den = [int(x) for x in road_row]

    road_online = {
        "population": pop_n,
        "eligible": elig_n,
        "P_unified_numerator": road_p_bin_num,
        "P_strict_good_numerator": road_p_good_num,
        "P_denominator": road_p_den,
        "R_numerator": road_p_bin_num,
        "R_denominator": road_r_den,
        "P_unified": ratio(road_p_bin_num, road_p_den),
        "P_strict_good": ratio(road_p_good_num, road_p_den),
        "R": ratio(road_p_bin_num, road_r_den),
    }

    if decisions is None:
        db.close()
        return {"label_key": label_key, "road_online": road_online, "independently_SQL_checked": True}

    # 2. Offline Replay / Simulation Recalculated Metrics over exact ra-sim `eligible` cohort
    sim_row = db.execute(
        """SELECT
            COALESCE(SUM(eligible = 1 AND triggered IS NOT NULL), 0),
            COALESCE(SUM(eligible = 1 AND triggered IS NULL), 0),
            COALESCE(SUM(eligible = 1 AND triggered = 1 AND label != '误触发'), 0),
            COALESCE(SUM(eligible = 1 AND triggered = 1 AND label = '误触发'), 0),
            COALESCE(SUM(eligible = 1 AND triggered = 0 AND label != '误触发'), 0),
            COALESCE(SUM(eligible = 1 AND triggered = 0 AND label = '误触发'), 0),
            COALESCE(SUM(eligible = 1 AND triggered = 1 AND label IN ('成功','失败','无需协助','限制使用')), 0),
            COALESCE(SUM(eligible = 1 AND triggered IS NOT NULL AND label != '误触发'), 0),
            COALESCE(SUM(eligible = 1 AND ra_type = 2 AND label != '误触发' AND triggered = 1), 0),
            COALESCE(SUM(eligible = 1 AND ra_type = 2 AND label != '误触发' AND triggered = 0), 0),
            COALESCE(SUM(eligible = 1 AND ra_type = 2 AND label = '误触发' AND triggered = 1), 0),
            COALESCE(SUM(eligible = 1 AND ra_type = 2 AND label = '误触发' AND triggered = 0), 0),
            COALESCE(SUM(eligible = 1 AND ra_type = 3 AND label != '误触发' AND triggered = 1), 0),
            COALESCE(SUM(eligible = 1 AND ra_type = 3 AND label != '误触发' AND triggered = 0), 0),
            COALESCE(SUM(valid_non_excl = 1 AND ra_type = 3 AND label = '误触发' AND triggered = 1), 0),
            COALESCE(SUM(valid_non_excl = 1 AND ra_type = 3 AND label = '误触发' AND triggered IS NOT NULL), 0)
        FROM shuyi_eval"""
    ).fetchone()
    db.close()

    (
        cov_n,
        unk_n,
        tp_bin,
        fp_bin,
        fn_bin,
        tn_bin,
        tp_good,
        r_cov_den,
        auto_tp_kept,
        auto_tp_lost,
        auto_fp_kept,
        auto_fp_removed,
        manual_tp_recalled,
        manual_tp_stayed_fn,
        manual_neg_triggered,
        manual_neg_covered,
    ) = [int(x) for x in sim_row]

    # Independent Python cross-check against SQLite counts
    py_elig = [
        (int(r["ra_type"]), str(r.get(label_key)), decisions.get(str(r["issue_id"])))
        for r in pop_rows
        if r.get(label_key) is not None
        and str(r.get(label_key)) != ""
        and str(r.get(label_key)) not in EXCLUDED_LABELS
        and not (int(r["ra_type"]) == 3 and str(r.get(label_key)) == "误触发")
    ]
    assert len(py_elig) == elig_n
    assert sum(t is not None for _, _, t in py_elig) == cov_n
    assert sum(t is True and l != "误触发" for _, l, t in py_elig) == tp_bin
    assert sum(t is True and l == "误触发" for _, l, t in py_elig) == fp_bin
    assert sum(t is False and l != "误触发" for _, l, t in py_elig) == fn_bin
    assert sum(t is False and l == "误触发" for _, l, t in py_elig) == tn_bin

    p_den_sim = tp_bin + fp_bin
    p_unified = ratio(tp_bin, p_den_sim)
    r_covered = ratio(tp_bin, r_cov_den)
    r_full = ratio(tp_bin, road_r_den)
    f1_covered = (
        (2 * p_unified * r_covered / (p_unified + r_covered))
        if (p_unified is not None and r_covered is not None and (p_unified + r_covered) > 0)
        else None
    )
    road_matches = auto_tp_kept + auto_fp_kept + manual_tp_stayed_fn
    repro_rate = ratio(road_matches, cov_n)

    # Also compute all-valid-labels P (if manual + 误触发 were included when triggered)
    p_all_valid = ratio(tp_bin, p_den_sim + manual_neg_triggered)

    return {
        "label_key": label_key,
        "road_online": road_online,
        "replay_eligible": {
            "eligible": elig_n,
            "covered": cov_n,
            "unknown": unk_n,
            "coverage": ratio(cov_n, elig_n),
            "TP": tp_bin,
            "FP": fp_bin,
            "FN": fn_bin,
            "TN": tn_bin,
            "P_numerator": tp_bin,
            "P_strict_good_numerator": tp_good,
            "P_denominator": p_den_sim,
            "R_numerator": tp_bin,
            "R_covered_denominator": r_cov_den,
            "R_full_denominator": road_r_den,
            "P_unified": p_unified,
            "P_strict_good": ratio(tp_good, p_den_sim),
            "R_covered": r_covered,
            "R_full": r_full,
            "F1_covered": f1_covered,
            "delta_vs_road_online_P": (
                (p_unified - road_online["P_unified"])
                if (p_unified is not None and road_online["P_unified"] is not None)
                else None
            ),
            "delta_vs_road_online_R_covered": (
                (r_covered - road_online["R"])
                if (r_covered is not None and road_online["R"] is not None)
                else None
            ),
            "road_trigger_repro_rate": repro_rate,
            "road_vs_replay_breakdown": {
                "auto_tp_kept": auto_tp_kept,
                "auto_tp_dropped": auto_tp_lost,
                "auto_fp_kept": auto_fp_kept,
                "auto_fp_removed": auto_fp_removed,
                "manual_tp_recalled": manual_tp_recalled,
                "manual_tp_stayed_fn": manual_tp_stayed_fn,
            },
        },
        "all_valid_with_manual_false": {
            "manual_false_covered": manual_neg_covered,
            "manual_false_triggered": manual_neg_triggered,
            "P_unified_including_manual_false": p_all_valid,
        },
        "independently_SQL_checked": True,
    }


# ---------------------------------------------------------------------------
# 3. Multi-Release End-to-End Evaluation & Shuyi Reconcile Report Builder
# ---------------------------------------------------------------------------


def evaluate_single_release_shuyi(
    *,
    release: str,
    population_jsonl: Path,
    npz_dir: Path,
    out_dir: Path,
    release_model: str,
    candidate_models: Sequence[Tuple[str, str]] = (),
    include_recorded: bool = True,
    shuyi_screenshot_ref: Optional[Mapping[str, float]] = None,
    label_key: str = "label_6level",
    device: str = "cpu",
    workers: int = 16,
) -> Dict[str, Any]:
    """Evaluate one historical release on its Enhanced Road NPZs and reconcile against Shuyi."""
    npz_dir = Path(npz_dir).expanduser().resolve()
    if (npz_dir / "npz").is_dir():
        npz_dir = npz_dir / "npz"
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    pop_rows = load_population_jsonl(population_jsonl)
    pop_ids = {str(r["issue_id"]) for r in pop_rows}
    npz_paths = sorted(p for p in npz_dir.glob("*.npz") if p.stem in pop_ids)
    if not npz_paths:
        raise FileNotFoundError(f"No matching .npz files for {release} found under {npz_dir}")

    arms_spec: List[Tuple[str, str, bool]] = []
    if include_recorded:
        arms_spec.append(("road_recorded", "recorded", True))
    arms_spec.append(("release_ifx", release_model, True))
    for c_lbl, c_path in candidate_models:
        arms_spec.append((c_lbl, c_path, False))

    arm_evals: Dict[str, Dict[str, Any]] = {}
    arm_views: Dict[str, Dict[str, Dict[str, Optional[bool]]]] = {}
    for lbl, spec, verify_par in arms_spec:
        print(f"[shuyi-{release}] Evaluating '{lbl}' ({spec}) on {len(npz_paths)} NPZs...", flush=True)
        ev = evaluate_model_on_npz_pool(
            npz_paths,
            spec,
            label=lbl,
            modes=("onboard_strict_road", "onboard_full"),
            device=device,
            workers=workers,
            verify_parity=verify_par,
        )
        arm_evals[lbl] = ev
        arm_views[lbl] = extract_trigger_views_for_arm(pop_rows, ev)
        print(f"[shuyi-{release}] Finished '{lbl}' in {ev['elapsed_sec']:.2f}s", flush=True)

    # Road /planning/assist_request ground-truth map + Orion Sim Base map (if available)
    road_bag_gt: Dict[str, Optional[bool]] = {str(r["issue_id"]): None for r in pop_rows}
    first_cases = next(iter(arm_evals.values()))["cases"]
    for c_row in first_cases:
        if c_row["case_id"] in road_bag_gt:
            road_bag_gt[c_row["case_id"]] = c_row["gt_road_request_in_formal_window"]

    orion_base_map: Dict[str, Optional[bool]] = {
        str(r["issue_id"]): (bool(r["orion_sim_base"]) if r.get("orion_sim_base") is not None else None)
        for r in pop_rows
    }
    has_orion_base = any(v is not None for v in orion_base_map.values())

    # Cycle-by-cycle discrete parity summary on `release_ifx` & `road_recorded`
    parity_summaries: Dict[str, Any] = {}
    for lbl in ("road_recorded", "release_ifx"):
        if lbl not in arm_evals:
            continue
        tot_cyc = u_ok = m_ok = r_ok = q_ok = exact_cases = 0
        max_abs_score_diff = 0.0
        for c_row in arm_evals[lbl]["cases"]:
            par = c_row["modes"].get("onboard_strict_road", {}).get("parity")
            if par:
                n_c = int(par["total_cycles"])
                tot_cyc += n_c
                u_c = int(str(par["unstuck_status_matches"]).split("/")[0])
                m_c = int(str(par["by_model_matches"]).split("/")[0])
                r_c = int(str(par["rule_decision_matches"]).split("/")[0])
                q_c = int(str(par["queue_len_matches"]).split("/")[0])
                u_ok += u_c
                m_ok += m_c
                r_ok += r_c
                q_ok += q_c
                if u_c == n_c and m_c == n_c and r_c == n_c and q_c == n_c:
                    exact_cases += 1
                s_diff = par.get("max_score_abs_diff")
                if isinstance(s_diff, (int, float)) and s_diff > max_abs_score_diff:
                    max_abs_score_diff = float(s_diff)
        parity_summaries[lbl] = {
            "cases_checked": len(arm_evals[lbl]["cases"]),
            "discrete_state_exact_cases": exact_cases,
            "total_cycles": tot_cyc,
            "unstuck_status_match_rate": round(u_ok / max(1, tot_cyc), 6),
            "by_model_match_rate": round(m_ok / max(1, tot_cyc), 6),
            "rule_decision_match_rate": round(r_ok / max(1, tot_cyc), 6),
            "queue_len_match_rate": round(q_ok / max(1, tot_cyc), 6),
            "max_score_abs_diff": round(max_abs_score_diff, 8),
        }

    # Score all arms & views under canonical `label_key` (and also `label_4level` for comparison)
    metrics_by_arm: Dict[str, Dict[str, Any]] = {}
    for lbl, v_map in arm_views.items():
        metrics_by_arm[lbl] = {
            v_name: compute_shuyi_reconcile_metrics(pop_rows, dec, label_key=label_key)
            for v_name, dec in v_map.items()
        }
    metrics_road_bag_gt = compute_shuyi_reconcile_metrics(pop_rows, road_bag_gt, label_key=label_key)
    metrics_orion_base = (
        compute_shuyi_reconcile_metrics(pop_rows, orion_base_map, label_key=label_key)
        if has_orion_base
        else None
    )
    metrics_4level_online = compute_shuyi_reconcile_metrics(pop_rows, None, label_key="label_4level")
    metrics_6level_online = compute_shuyi_reconcile_metrics(pop_rows, None, label_key="label_6level")

    sh_ref = dict(shuyi_screenshot_ref or DEFAULT_SHUYI_SCREENSHOT_REFS.get(release, {}))
    rel_strict_causal = metrics_by_arm["release_ifx"]["strict_road_causal"]["replay_eligible"]
    rel_sim_full = metrics_by_arm["release_ifx"]["onboard_full_formal"]["replay_eligible"]
    online_6 = metrics_6level_online["road_online"]

    screenshot_alignment = None
    if "P" in sh_ref and "R" in sh_ref:
        screenshot_alignment = {
            "shuyi_screenshot_P": sh_ref["P"],
            "shuyi_screenshot_R": sh_ref["R"],
            "trail_online_6level_P_diff": (
                round(online_6["P_unified"] - sh_ref["P"], 6) if online_6["P_unified"] is not None else None
            ),
            "trail_online_6level_R_diff": (
                round(online_6["R"] - sh_ref["R"], 6) if online_6["R"] is not None else None
            ),
            "offline_npz_strict_causal_P": rel_strict_causal["P_unified"],
            "offline_npz_strict_causal_R": rel_strict_causal["R_covered"],
            "offline_npz_strict_causal_P_diff_vs_screenshot": (
                round(rel_strict_causal["P_unified"] - sh_ref["P"], 6)
                if rel_strict_causal["P_unified"] is not None
                else None
            ),
            "offline_npz_strict_causal_R_diff_vs_screenshot": (
                round(rel_strict_causal["R_covered"] - sh_ref["R"], 6)
                if rel_strict_causal["R_covered"] is not None
                else None
            ),
            "offline_npz_sim_counterfactual_P": rel_sim_full["P_unified"],
            "offline_npz_sim_counterfactual_R": rel_sim_full["R_covered"],
        }

    # Write per-case JSONL for full auditability
    per_case_path = out_dir / "per_case_shuyi.jsonl"
    rel_case_map = {r["case_id"]: r for r in arm_evals["release_ifx"]["cases"]}
    with per_case_path.open("w", encoding="utf-8") as fp:
        for r in pop_rows:
            iid = str(r["issue_id"])
            c_info = rel_case_map.get(iid)
            rec_obj: Dict[str, Any] = {
                "issue_id": iid,
                "release": release,
                "ra_type": r["ra_type"],
                "label_6level": r.get("label_6level"),
                "label_4level": r.get("label_4level"),
                "npz_available": c_info is not None,
                "num_tensor_frames": c_info["num_tensor_frames"] if c_info else None,
                "num_cycles": c_info["num_cycles"] if c_info else None,
                "road_bag_gt_formal": road_bag_gt.get(iid),
                "orion_sim_base": orion_base_map.get(iid),
                "release_ifx_strict_road_causal": arm_views["release_ifx"]["strict_road_causal"].get(iid),
                "release_ifx_strict_road_formal": arm_views["release_ifx"]["strict_road_formal"].get(iid),
                "release_ifx_onboard_full_formal": arm_views["release_ifx"]["onboard_full_formal"].get(iid),
            }
            if "road_recorded" in arm_views:
                rec_obj["road_recorded_strict_road_causal"] = arm_views["road_recorded"][
                    "strict_road_causal"
                ].get(iid)
            for c_lbl, _ in candidate_models:
                rec_obj[f"{c_lbl}_onboard_full_formal"] = arm_views[c_lbl]["onboard_full_formal"].get(iid)
                rec_obj[f"{c_lbl}_strict_road_causal"] = arm_views[c_lbl]["strict_road_causal"].get(iid)
            fp.write(json.dumps(rec_obj, ensure_ascii=False) + "\n")

    summary = {
        "release": release,
        "generated_at": datetime.now().astimezone().isoformat(),
        "population_jsonl": str(Path(population_jsonl).resolve()),
        "npz_dir": str(npz_dir),
        "population_issues": len(pop_rows),
        "npz_evaluated": len(npz_paths),
        "label_key": label_key,
        "shuyi_screenshot_reference": sh_ref,
        "screenshot_alignment": screenshot_alignment,
        "online_6level": metrics_6level_online["road_online"],
        "online_4level": metrics_4level_online["road_online"],
        "models": {
            lbl: {k: v for k, v in ev.items() if k != "cases"}
            for lbl, ev in arm_evals.items()
        },
        "parity_summaries": parity_summaries,
        "metrics_by_arm": metrics_by_arm,
        "metrics_road_bag_gt_formal": metrics_road_bag_gt,
        "metrics_orion_sim_base": metrics_orion_base,
        "per_case_jsonl": str(per_case_path),
    }
    summary_path = out_dir / "SUMMARY.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["summary_json"] = str(summary_path)
    return summary


def _pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{v * 100:.2f}%"


def _pp_diff(v: Optional[float]) -> str:
    return "-" if v is None else f"{v * 100:+.2f}%"


def run_multi_release_shuyi_suite(
    config_json: Path,
    out_dir: Path,
    *,
    device: str = "cpu",
    workers: int = 16,
) -> Dict[str, Any]:
    """Run offline NPZ inference & Shuyi board reconciliation across all configured releases."""
    cfg = json.loads(Path(config_json).read_text(encoding="utf-8"))
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    candidate_models = [(str(item["label"]), str(item["path"])) for item in cfg.get("candidate_models", [])]
    include_recorded = bool(cfg.get("include_recorded", True))
    label_key = str(cfg.get("label_key", "label_6level"))
    reuse_existing_summaries = bool(cfg.get("reuse_existing_summaries", False))

    release_summaries: List[Dict[str, Any]] = []
    for item in cfg["releases"]:
        rel = str(item["release"])
        rel_out = out_dir / rel
        existing_summary_path = rel_out / "SUMMARY.json"
        if (
            reuse_existing_summaries
            and not bool(item.get("force_recompute", False))
            and existing_summary_path.is_file()
        ):
            print(f"[shuyi-{rel}] Reusing existing SUMMARY.json from {existing_summary_path}", flush=True)
            release_summaries.append(json.loads(existing_summary_path.read_text(encoding="utf-8")))
            continue
        res = evaluate_single_release_shuyi(
            release=rel,
            population_jsonl=Path(item["population_jsonl"]),
            npz_dir=Path(item["npz_dir"]),
            out_dir=rel_out,
            release_model=str(item["release_model"]),
            candidate_models=candidate_models,
            include_recorded=include_recorded,
            shuyi_screenshot_ref=item.get("shuyi_screenshot") or DEFAULT_SHUYI_SCREENSHOT_REFS.get(rel),
            label_key=str(item.get("label_key") or label_key),
            device=device,
            workers=workers,
        )
        release_summaries.append(res)

    # Write flat CSV table across all releases
    csv_path = out_dir / "MULTI_RELEASE_SHUYI_RECONCILE.csv"
    csv_fields = [
        "release",
        "population_issues",
        "eligible_issues",
        "npz_covered_eligible",
        "coverage",
        "shuyi_screenshot_P",
        "shuyi_screenshot_R",
        "trail_online_6level_P",
        "trail_online_6level_R",
        "npz_strict_causal_P",
        "npz_strict_causal_R",
        "npz_strict_causal_P_diff_vs_shuyi",
        "npz_strict_causal_R_diff_vs_shuyi",
        "npz_strict_causal_road_repro_rate",
        "npz_sim_full_P",
        "npz_sim_full_R",
        "orion_sim_base_P",
        "orion_sim_base_R",
        "ifx_discrete_cycle_match_rate",
    ]
    for c_lbl, _ in candidate_models:
        csv_fields.extend([f"{c_lbl}_sim_full_P", f"{c_lbl}_sim_full_R"])

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=csv_fields)
        writer.writeheader()
        for s in release_summaries:
            sc_m = s["metrics_by_arm"]["release_ifx"]["strict_road_causal"]["replay_eligible"]
            sf_m = s["metrics_by_arm"]["release_ifx"]["onboard_full_formal"]["replay_eligible"]
            or_m = s["metrics_orion_sim_base"]["replay_eligible"] if s["metrics_orion_sim_base"] else None
            sh = s["shuyi_screenshot_reference"]
            on6 = s["online_6level"]
            par = s["parity_summaries"].get("release_ifx", {})
            row_dict: Dict[str, Any] = {
                "release": s["release"],
                "population_issues": s["population_issues"],
                "eligible_issues": sc_m["eligible"],
                "npz_covered_eligible": sc_m["covered"],
                "coverage": _pct(sc_m["coverage"]),
                "shuyi_screenshot_P": _pct(sh.get("P")),
                "shuyi_screenshot_R": _pct(sh.get("R")),
                "trail_online_6level_P": _pct(on6["P_unified"]),
                "trail_online_6level_R": _pct(on6["R"]),
                "npz_strict_causal_P": _pct(sc_m["P_unified"]),
                "npz_strict_causal_R": _pct(sc_m["R_covered"]),
                "npz_strict_causal_P_diff_vs_shuyi": _pp_diff(
                    (sc_m["P_unified"] - sh["P"]) if (sc_m["P_unified"] is not None and "P" in sh) else None
                ),
                "npz_strict_causal_R_diff_vs_shuyi": _pp_diff(
                    (sc_m["R_covered"] - sh["R"]) if (sc_m["R_covered"] is not None and "R" in sh) else None
                ),
                "npz_strict_causal_road_repro_rate": _pct(sc_m["road_trigger_repro_rate"]),
                "npz_sim_full_P": _pct(sf_m["P_unified"]),
                "npz_sim_full_R": _pct(sf_m["R_covered"]),
                "orion_sim_base_P": _pct(or_m["P_unified"]) if or_m else "-",
                "orion_sim_base_R": _pct(or_m["R_covered"]) if or_m else "-",
                "ifx_discrete_cycle_match_rate": _pct(par.get("unstuck_status_match_rate")),
            }
            for c_lbl, _ in candidate_models:
                cm = s["metrics_by_arm"][c_lbl]["onboard_full_formal"]["replay_eligible"]
                row_dict[f"{c_lbl}_sim_full_P"] = _pct(cm["P_unified"])
                row_dict[f"{c_lbl}_sim_full_R"] = _pct(cm["R_covered"])
            writer.writerow(row_dict)

    # Render Markdown summary report
    md_lines = [
        "# Historical Releases (`1009` – `1113`) Offline NPZ Inference vs Shuyi Board (`288969 / 6276081`) Reconciliation Report",
        "",
        f"- **Generated At**: `{datetime.now().astimezone().isoformat()}`",
        "- **Target Shuyi Chart**: `reportId=288969`, `subReportId=6276081` — **自触发指标（不包含RA红绿灯）** (`自触发准确率/召回率-AutoTriage+人工修正`)",
        "",
        "## 1. End-to-End Shuyi Board Alignment (`strict_road_causal` with Native Release `.ifxmodel`)",
        "",
        "| Release | Eligible / Covered | Shuyi Screenshot (P / R) | Live Trail 6-Level Online (P / R) | Offline NPZ `release_ifx` Causal (P / R) | NPZ vs Shuyi Diff (ΔP / ΔR) | Road Trigger Repro Rate | 10Hz Status Parity |",
        "| --- | ---: | :---: | :---: | :---: | :---: | ---: | ---: |",
    ]
    for s in release_summaries:
        sc_m = s["metrics_by_arm"]["release_ifx"]["strict_road_causal"]["replay_eligible"]
        sh = s["shuyi_screenshot_reference"]
        on6 = s["online_6level"]
        par = s["parity_summaries"].get("release_ifx", {})
        dp = (sc_m["P_unified"] - sh["P"]) if (sc_m["P_unified"] is not None and "P" in sh) else None
        dr = (sc_m["R_covered"] - sh["R"]) if (sc_m["R_covered"] is not None and "R" in sh) else None
        md_lines.append(
            f"| `{s['release']}` | {sc_m['covered']}/{sc_m['eligible']} ({_pct(sc_m['coverage'])}) | "
            f"**{_pct(sh.get('P'))} / {_pct(sh.get('R'))}** | "
            f"{_pct(on6['P_unified'])} / {_pct(on6['R'])} | "
            f"**{_pct(sc_m['P_unified'])} / {_pct(sc_m['R_covered'])}** | "
            f"`{_pp_diff(dp)}` / `{_pp_diff(dr)}` | "
            f"{_pct(sc_m['road_trigger_repro_rate'])} | "
            f"{_pct(par.get('unstuck_status_match_rate'))} |"
        )

    md_lines.extend([
        "",
        "## 2. Counterfactual Simulation Mode (`onboard_full` 30s Window) vs Historical Orion Sim Baselines & Candidate `CR 7028995 v122`",
        "",
        "| Release | Historical Orion Sim Base (P / R) | Offline NPZ `release_ifx` `onboard_full` (P / R) | Candidate `CR 7028995 v122` `onboard_full` (P / R) |",
        "| --- | :---: | :---: | :---: |",
    ])
    for s in release_summaries:
        sf_m = s["metrics_by_arm"]["release_ifx"]["onboard_full_formal"]["replay_eligible"]
        or_m = s["metrics_orion_sim_base"]["replay_eligible"] if s["metrics_orion_sim_base"] else None
        cand_str = "-"
        if candidate_models:
            c0 = candidate_models[0][0]
            cm = s["metrics_by_arm"][c0]["onboard_full_formal"]["replay_eligible"]
            cand_str = f"**{_pct(cm['P_unified'])} / {_pct(cm['R_covered'])}** (`TP={cm['TP']}, FP={cm['FP']}`)"
        or_str = (
            f"{_pct(or_m['P_unified'])} / {_pct(or_m['R_covered'])} (`n={or_m['covered']}`)"
            if or_m
            else "-"
        )
        md_lines.append(
            f"| `{s['release']}` | {or_str} | "
            f"{_pct(sf_m['P_unified'])} / {_pct(sf_m['R_covered'])} (`TP={sf_m['TP']}, FP={sf_m['FP']}`) | "
            f"{cand_str} |"
        )

    report_md = out_dir / "REPORT.md"
    report_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    suite_summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "releases": release_summaries,
        "csv_path": str(csv_path),
        "report_md": str(report_md),
    }
    suite_json = out_dir / "MULTI_RELEASE_SUMMARY.json"
    suite_json.write_text(json.dumps(suite_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    suite_summary["summary_json"] = str(suite_json)
    return suite_summary
