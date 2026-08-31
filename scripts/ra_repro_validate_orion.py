#!/usr/bin/env python3
"""Validate an RA reproduction Orion job against its scenario manifest.

This is a read-only helper.  It joins Orion task state and Trail DPE results
to the manifest by scenario id, then reports road-behavior reproduction and
business-truth metrics separately.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, Sequence

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ra_api.sim_result_api import SimResultClient


_ORION_DB_BASE_URL = os.environ.get(
    "ORION_DB_BASE_URL", "http://orion-dbserver.intra.xiaojukeji.com")
_ORION_QUERY_URL = f"{_ORION_DB_BASE_URL}/orion/task/query/"
_TRIGGER_METRIC = "dpe_assist_channel_triggered__group1"
_COHORTS = ("positive_auto", "negative_auto", "positive_manual")
_ALLOWED_WARNING_MODULES = {"task_reuse_cache_key_build_miss"}
_DPE_LAG_GRACE_SECONDS = 120
_ORION_QUERY_MAX_ATTEMPTS = 5
_ORION_QUERY_PAGE_SIZE = 20
_ORION_LIGHT_QUERY_PAGE_SIZE = 500


def _post_orion_query(data: dict[str, str], token: str) -> requests.Response:
  """POST one Orion query page with bounded retries for gateway failures."""
  for attempt in range(1, _ORION_QUERY_MAX_ATTEMPTS + 1):
    try:
      response = requests.post(
          _ORION_QUERY_URL,
          headers={"Authorization": f"Bearer {token}"},
          data=data,
          timeout=60,
      )
      if response.status_code not in (502, 503, 504):
        response.raise_for_status()
        return response
      response.raise_for_status()
    except (requests.ConnectionError, requests.Timeout,
            requests.HTTPError) as exc:
      retryable_http = (
          not isinstance(exc, requests.HTTPError) or
          exc.response is not None and exc.response.status_code in (502, 503,
                                                                     504))
      if not retryable_http or attempt == _ORION_QUERY_MAX_ATTEMPTS:
        raise
      time.sleep(2 ** (attempt - 1))
  raise AssertionError("unreachable")


def _query_pages(params: dict[str, str], token: str,
                 page_size: int) -> list[dict[str, Any]]:
  """Query all matching tasks using monotonically increasing task IDs."""
  tasks = []
  next_minimum_id = 0
  while True:
    response = _post_orion_query({
        **params,
        "id__gt": str(next_minimum_id),
        "page": "1",
        "size": str(page_size),
    }, token)
    payload = response.json()
    if payload.get("code") != 0:
      raise RuntimeError(f"Orion query failed: {payload}")
    page = payload.get("data", {}).get("res", [])
    tasks.extend(page)
    if len(page) < page_size:
      break
    last_id = int(page[-1]["id"])
    if last_id <= next_minimum_id:
      raise RuntimeError("Orion task pagination did not advance")
    next_minimum_id = last_id
  return tasks


def _query_results_by_task_ids(job_id: int, token: str) -> list[dict[str, Any]]:
  """Fallback for gateways that reject result-heavy job-id queries."""
  light_tasks = _query_pages(
      {"job_id": str(job_id)}, token, _ORION_LIGHT_QUERY_PAGE_SIZE)
  expected_ids = [int(task["id"]) for task in light_tasks]
  tasks = []
  for start in range(0, len(expected_ids), _ORION_QUERY_PAGE_SIZE):
    chunk = expected_ids[start:start + _ORION_QUERY_PAGE_SIZE]
    response = _post_orion_query({
        "id": ",".join(map(str, chunk)),
        "extra_fields": "result",
        "page": "1",
        "size": str(len(chunk)),
    }, token)
    payload = response.json()
    if payload.get("code") != 0:
      raise RuntimeError(f"Orion query failed: {payload}")
    page = payload.get("data", {}).get("res", [])
    received_ids = {int(task["id"]) for task in page}
    if received_ids != set(chunk):
      raise RuntimeError(
          f"Orion task-ID fallback mismatch for job {job_id}: requested "
          f"{len(chunk)}, received {len(received_ids)}")
    tasks.extend(page)
  if {int(task["id"]) for task in tasks} != set(expected_ids):
    raise RuntimeError(f"Orion task-ID fallback incomplete for job {job_id}")
  return tasks


def _query_results_via_accessor(job_id: int) -> list[dict[str, Any]]:
  """Last-resort query path using Orion's region-aware DB accessor."""
  try:
    from orion.db_accessor.task_accessor import TaskAccessor
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError(
        "Orion TaskAccessor fallback requires Voyager build/lib paths") from exc

  with TrailRegionMgr(Regions.CN, is_pre=False):
    light_tasks = list(TaskAccessor.query({"job_id": job_id}))
    expected_ids = [int(task["id"]) for task in light_tasks]
    tasks = []
    for start in range(0, len(expected_ids), _ORION_QUERY_PAGE_SIZE):
      chunk = expected_ids[start:start + _ORION_QUERY_PAGE_SIZE]
      page = list(TaskAccessor.query({
          "id": ",".join(map(str, chunk)),
          "extra_fields": "result",
      }))
      received_ids = {int(task["id"]) for task in page}
      if received_ids != set(chunk):
        raise RuntimeError(
            f"Orion accessor fallback mismatch for job {job_id}: requested "
            f"{len(chunk)}, received {len(received_ids)}")
      for task in page:
        result = task.get("result")
        if result is not None and hasattr(result, "as_dict"):
          task["result"] = result.as_dict()
      tasks.extend(page)
  if {int(task["id"]) for task in tasks} != set(expected_ids):
    raise RuntimeError(f"Orion accessor fallback incomplete for job {job_id}")
  return tasks


def _query_orion(job_id: int, token: str) -> pd.DataFrame:
  # The normal path is efficient. Some Orion gateways intermittently reject
  # any result-heavy query filtered by job_id; in that case use a verified
  # task-ID batch fallback rather than losing final-report availability.
  try:
    tasks = _query_pages({
        "job_id": str(job_id),
        "extra_fields": "result",
    }, token, _ORION_QUERY_PAGE_SIZE)
  except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
    try:
      tasks = _query_results_by_task_ids(job_id, token)
    except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
      tasks = _query_results_via_accessor(job_id)

  rows = []
  for task in tasks:
    task_runs = task.get("task_runs") or []
    run = task_runs[-1] if task_runs else task
    prior_runs = task_runs[:-1]
    prior_failed_runs = sum(
        int(item.get("status", -1)) in (4, 5) for item in prior_runs)
    prior_dpe_oom_runs = sum(
        "dpe exceeded memory quota" in " ".join((
            str(item.get("outcome") or ""),
            str(item.get("outcome_detail") or ""),
        )).lower()
        for item in prior_runs)
    result = run.get("result", {}) or {}
    warnings = result.get("warnings") or []
    warning_modules = {
        warning.get("module") if isinstance(warning, dict) else None
        for warning in warnings
    }
    rows.append({
        "source_job_id": job_id,
        "scenario_id": int(task["signature"]),
        "task_id": task.get("id"),
        "task_status": task.get("status"),
        "task_outcome": run.get("outcome", ""),
        "task_outcome_detail": run.get("outcome_detail", ""),
        "task_duration_seconds": run.get("duration_time", 0),
        "task_update_time": task.get("update_time"),
        "task_retry_count": max(len(task_runs) - 1, 0),
        "prior_failed_task_run_count": prior_failed_runs,
        "prior_dpe_oom_task_run_count": prior_dpe_oom_runs,
        "simulator_cache_hit": result.get("simulator_cache_hit"),
        "inference_log_count": len(result.get("inference_log_locations") or []),
        "dpe_output_count": len(result.get("dpe_output_locations") or []),
        "output_bag_count": len(result.get("output_bag_locations") or []),
        "failed_evaluation_count": len(result.get("failed_evaluations") or []),
        "warning_count": len(warnings),
        "unexpected_warning_count": sum(
            module not in _ALLOWED_WARNING_MODULES
            for module in warning_modules),
    })
  frame = pd.DataFrame(rows)
  if not frame.empty and frame["scenario_id"].duplicated().any():
    raise RuntimeError(f"Orion job {job_id} returned duplicate scenario ids")
  return frame


def _load_manifest(path: Path, release: str | None) -> pd.DataFrame:
  manifest = pd.read_csv(path, low_memory=False)
  if release:
    release_columns = [
        column for column in ("big_version", "release", "version")
        if column in manifest.columns
    ]
    if not release_columns:
      raise ValueError("Manifest has no release/version column")
    matched = pd.Series(False, index=manifest.index)
    for column in release_columns:
      matched |= manifest[column].astype(str).str.contains(release, na=False)
    manifest = manifest[matched]

  source_rows = len(manifest)
  exclusions = {
      "no_bag": 0,
      "missing_trip": 0,
  }
  if "validation_error" in manifest.columns:
    invalid = manifest["validation_error"].fillna("").astype(str).ne("")
    if invalid.any():
      raise ValueError(
          f"Manifest contains {int(invalid.sum())} invalid conversions")
  if "upload_status" in manifest.columns:
    statuses = manifest["upload_status"].fillna("").astype(str)
    no_bag = statuses.str.contains("does not have bags", regex=False)
    missing_trip = (
        statuses.str.contains("trip_id(", regex=False) &
        statuses.str.contains("does not exist", regex=False))
    nonretryable = no_bag | missing_trip
    usable = statuses.isin(("uploaded", "existing"))
    unexpected = sorted(statuses[~usable & ~nonretryable].unique().tolist())
    if unexpected:
      raise ValueError(
          f"Manifest contains unusable upload statuses: {unexpected}")
    exclusions = {
        "no_bag": int(no_bag.sum()),
        "missing_trip": int(missing_trip.sum()),
    }
    manifest = manifest[usable]

  required = {"scenario_id", "issue_id", "cohort"}
  missing = required - set(manifest.columns)
  if missing:
    raise ValueError(f"Manifest missing columns: {sorted(missing)}")
  manifest = manifest.copy()
  if manifest["scenario_id"].isna().any():
    raise ValueError("Usable manifest rows contain missing scenario ids")
  issue_ids = manifest["issue_id"].fillna("").astype(str).str.strip()
  if issue_ids.eq("").any():
    raise ValueError("Usable manifest rows contain missing issue ids")
  if issue_ids.duplicated().any():
    raise ValueError("Usable manifest rows contain duplicate issue ids")
  manifest["issue_id"] = issue_ids
  manifest["scenario_id"] = manifest["scenario_id"].astype(int)
  manifest.attrs["audit"] = {
      "source_rows": source_rows,
      "submitted_rows": len(manifest),
      "excluded_rows": source_rows - len(manifest),
      "exclusions": exclusions,
  }
  return manifest


def _ratio(numerator: int, denominator: int) -> float | None:
  return numerator / denominator if denominator else None


def _summarize(joined: pd.DataFrame,
               job_id: int | Sequence[int]) -> Dict[str, Any]:
  terminal = joined["task_status"].isin((3, 4, 5))
  completed = joined["task_status"].eq(3) & joined[
      "task_outcome"].fillna("").str.startswith(
      "Done")
  terminal_failed = terminal & ~completed
  has_dpe = joined[_TRIGGER_METRIC].notna()
  evaluated = completed & has_dpe
  triggered = joined[_TRIGGER_METRIC].ge(1)
  completed_durations = pd.to_numeric(
      joined.loc[completed, "task_duration_seconds"], errors="coerce").dropna()
  mean_duration = (
      float(completed_durations.mean()) if not completed_durations.empty else None)
  median_duration = (
      float(completed_durations.median())
      if not completed_durations.empty else None)
  p90_duration = (
      float(completed_durations.quantile(0.90))
      if not completed_durations.empty else None)
  p95_duration = (
      float(completed_durations.quantile(0.95))
      if not completed_durations.empty else None)
  max_duration = (
      float(completed_durations.max())
      if not completed_durations.empty else None)
  remaining_tasks = int((~terminal).sum())
  cache_hits = int((completed & joined["simulator_cache_hit"].eq(True)).sum())
  cache_field_missing = int(
      (completed & joined["simulator_cache_hit"].isna()).sum())
  inference_log_missing = int(
      (completed & joined["inference_log_count"].le(0)).sum())
  dpe_output_missing = int(
      (completed & joined["dpe_output_count"].le(0)).sum())
  output_bag_missing = int(
      (completed & joined["output_bag_count"].le(0)).sum())
  failed_evaluations = int(
      (completed & joined["failed_evaluation_count"].gt(0)).sum())
  warnings = int((completed & joined["warning_count"].gt(0)).sum())
  unexpected_warnings = int(
      (completed & joined["unexpected_warning_count"].gt(0)).sum())
  retry_counts = pd.to_numeric(
      joined.get("task_retry_count", pd.Series(0, index=joined.index)),
      errors="coerce").fillna(0).astype(int)
  prior_failed_run_counts = pd.to_numeric(
      joined.get("prior_failed_task_run_count",
                 pd.Series(0, index=joined.index)),
      errors="coerce").fillna(0).astype(int)
  prior_dpe_oom_run_counts = pd.to_numeric(
      joined.get("prior_dpe_oom_task_run_count",
                 pd.Series(0, index=joined.index)),
      errors="coerce").fillna(0).astype(int)
  retried = retry_counts.gt(0)
  prior_dpe_oom = prior_dpe_oom_run_counts.gt(0)
  update_times = pd.to_datetime(
      joined["task_update_time"], utc=True, errors="coerce", format="mixed")
  dpe_grace_cutoff = (pd.Timestamp.now(tz="UTC") -
                      pd.Timedelta(seconds=_DPE_LAG_GRACE_SECONDS))
  completed_pending_dpe_grace_mask = (
      completed & ~has_dpe & update_times.notna() &
      update_times.gt(dpe_grace_cutoff))
  completed_missing_dpe_mask = (
      completed & ~has_dpe & ~completed_pending_dpe_grace_mask)
  completed_pending_dpe_grace = int(
      completed_pending_dpe_grace_mask.sum())
  completed_missing_dpe = int(completed_missing_dpe_mask.sum())
  completed_missing_dpe_scenario_ids = sorted(
      joined.loc[completed_missing_dpe_mask,
                 "scenario_id"].astype(int).tolist())
  completed_pending_dpe_grace_scenario_ids = sorted(
      joined.loc[completed_pending_dpe_grace_mask,
                 "scenario_id"].astype(int).tolist())
  terminal_failed_scenario_ids = sorted(
      joined.loc[terminal_failed, "scenario_id"].astype(int).tolist())
  quality_gate_passed_so_far = not any((
      int(terminal_failed.sum()),
      completed_missing_dpe,
      cache_hits,
      cache_field_missing,
      inference_log_missing,
      dpe_output_missing,
      output_bag_missing,
      failed_evaluations,
      unexpected_warnings,
  ))

  cohorts: Dict[str, Any] = {}
  for cohort in _COHORTS:
    selected = joined["cohort"].eq(cohort) & evaluated
    count = int(selected.sum())
    trigger_count = int((selected & triggered).sum())
    no_trigger_count = count - trigger_count
    expected_road_trigger = cohort != "positive_manual"
    road_matches = trigger_count if expected_road_trigger else no_trigger_count
    cohorts[cohort] = {
        "evaluated": count,
        "triggered": trigger_count,
        "not_triggered": no_trigger_count,
        "road_behavior_matches": road_matches,
        "road_behavior_reproduction": _ratio(road_matches, count),
    }

  truth_positive = joined["cohort"].isin(
      ["positive_auto", "positive_manual"]) & evaluated
  truth_negative = joined["cohort"].eq("negative_auto") & evaluated
  tp = int((truth_positive & triggered).sum())
  fn = int((truth_positive & ~triggered).sum())
  fp = int((truth_negative & triggered).sum())
  tn = int((truth_negative & ~triggered).sum())

  return {
      "job_id": job_id,
      "manifest_rows": len(joined),
      "manifest_unique_scenarios": int(joined["scenario_id"].nunique()),
      "task_status_counts": {
          str(key): int(value)
          for key, value in joined["task_status"].value_counts(
              dropna=False).items()
      },
      "task_outcome_counts": {
          str(key): int(value)
          for key, value in joined["task_outcome"].value_counts(
              dropna=False).items()
      },
      "completed": int(completed.sum()),
      "terminal": int(terminal.sum()),
      "terminal_failed": int(terminal_failed.sum()),
      "terminal_failed_scenario_ids": terminal_failed_scenario_ids,
      "mean_completed_duration_seconds": mean_duration,
      "median_completed_duration_seconds": median_duration,
      "p90_completed_duration_seconds": p90_duration,
      "p95_completed_duration_seconds": p95_duration,
      "max_completed_duration_seconds": max_duration,
      "estimated_remaining_hours_at_concurrency_1": (
          mean_duration * remaining_tasks / 3600 if mean_duration else None),
      "dpe_covered": int(has_dpe.sum()),
      "terminal_dpe_covered": int((terminal & has_dpe).sum()),
      "completed_dpe_covered": int((completed & has_dpe).sum()),
      "completed_missing_dpe": completed_missing_dpe,
      "completed_missing_dpe_scenario_ids": (
          completed_missing_dpe_scenario_ids),
      "completed_pending_dpe_grace": completed_pending_dpe_grace,
      "completed_pending_dpe_grace_scenario_ids": (
          completed_pending_dpe_grace_scenario_ids),
      "dpe_lag_grace_seconds": _DPE_LAG_GRACE_SECONDS,
      "quality": {
          "simulator_cache_hits": cache_hits,
          "simulator_cache_field_missing": cache_field_missing,
          "inference_log_missing": inference_log_missing,
          "dpe_output_missing": dpe_output_missing,
          "output_bag_missing": output_bag_missing,
          "failed_evaluations": failed_evaluations,
          "tasks_with_warnings": warnings,
          "tasks_with_unexpected_warnings": unexpected_warnings,
          "tasks_retried": int(retried.sum()),
          "retry_attempts": int(retry_counts.sum()),
          "prior_failed_task_runs": int(prior_failed_run_counts.sum()),
          "prior_dpe_oom_task_runs": int(prior_dpe_oom_run_counts.sum()),
          "retried_scenario_ids": sorted(
              joined.loc[retried, "scenario_id"].astype(int).tolist()),
          "prior_dpe_oom_scenario_ids": sorted(
              joined.loc[prior_dpe_oom,
                         "scenario_id"].astype(int).tolist()),
          "gate_passed_so_far": quality_gate_passed_so_far,
      },
      "cohorts": cohorts,
      "truth": {
          "tp": tp,
          "fn": fn,
          "fp": fp,
          "tn": tn,
          "precision": _ratio(tp, tp + fp),
          "recall": _ratio(tp, tp + fn),
          "specificity": _ratio(tn, tn + fp),
          "accuracy": _ratio(tp + tn, tp + fn + fp + tn),
      },
      "is_terminal_and_complete": bool(
          len(joined) > 0 and terminal.all() and completed.all() and
          has_dpe.all() and quality_gate_passed_so_far),
  }


def _select_scenario_results(rows: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
  """Select one best task result per scenario across resumed Orion jobs."""
  if rows.empty:
    return rows, []

  rows = rows.copy()
  completed = rows["task_status"].eq(3) & rows[
      "task_outcome"].fillna("").str.startswith("Done")
  has_dpe = rows[_TRIGGER_METRIC].notna()
  # A completed result with DPE is authoritative.  Remaining ranks only make
  # progress reporting useful while a resumed job is still running.
  rows["_selection_rank"] = 0
  rows.loc[rows["task_status"].eq(1), "_selection_rank"] = 1
  rows.loc[rows["task_status"].eq(2), "_selection_rank"] = 2
  rows.loc[completed, "_selection_rank"] = 3
  rows.loc[completed & has_dpe, "_selection_rank"] = 4
  complete_fresh_result = (
      completed & has_dpe & rows["simulator_cache_hit"].eq(False) &
      rows["inference_log_count"].gt(0) & rows["dpe_output_count"].gt(0) &
      rows["output_bag_count"].gt(0) &
      rows["failed_evaluation_count"].eq(0) &
      rows["unexpected_warning_count"].eq(0))
  rows.loc[complete_fresh_result, "_selection_rank"] = 5

  conflicts = []
  for scenario_id, group in rows[completed & has_dpe].groupby("scenario_id"):
    values = sorted(set(group[_TRIGGER_METRIC].ge(1).tolist()))
    if len(values) > 1:
      conflicts.append({
          "scenario_id": int(scenario_id),
          "job_ids": sorted(group["source_job_id"].astype(int).unique().tolist()),
          "trigger_values": values,
      })

  selected = (rows.sort_values(
      ["scenario_id", "_selection_rank", "source_job_id", "task_update_time"],
      na_position="first").drop_duplicates("scenario_id", keep="last").drop(
          columns=["_selection_rank"]))
  return selected, conflicts


def _dashboard_scenario_results(joined: pd.DataFrame) -> list[dict[str, Any]]:
  """Render completed+DPE scenario rows for offline Dashboard ingestion."""
  completed = joined["task_status"].eq(3) & joined[
      "task_outcome"].fillna("").str.startswith("Done")
  evaluated = joined[completed & joined[_TRIGGER_METRIC].notna()]
  rows = []
  for item in evaluated.to_dict(orient="records"):
    rows.append({
        "scenario_id": int(item["scenario_id"]),
        "issue_id": str(item.get("issue_id") or ""),
        "cohort": str(item.get("cohort") or ""),
        "source_job_id": int(item["source_job_id"]),
        "task_id": int(item["task_id"]),
        "dpe_assist_channel_triggered": float(item[_TRIGGER_METRIC]),
        "sim_triggered": bool(float(item[_TRIGGER_METRIC]) >= 1),
    })
  return rows


def validate(job_ids: Sequence[int], manifest_path: Path, release: str | None,
             token: str) -> Dict[str, Any]:
  manifest = _load_manifest(manifest_path, release)
  manifest_audit = manifest.attrs.get("audit", {})
  if manifest["scenario_id"].duplicated().any():
    raise ValueError("Manifest contains duplicate scenario ids")

  if not job_ids:
    raise ValueError("At least one Orion job id is required")

  job_rows = []
  for job_id in job_ids:
    tasks = _query_orion(job_id, token)
    dpe = SimResultClient().query_all_pages(
        job_id,
        metrics=["dpe_assist_channel_triggered"],
        page_size=100,
    )
    if not dpe.empty:
      dpe["scenario_id"] = dpe["scenario_id"].astype(int)
      dpe = dpe[["scenario_id", _TRIGGER_METRIC]].drop_duplicates(
          "scenario_id")
    else:
      dpe = pd.DataFrame(columns=["scenario_id", _TRIGGER_METRIC])
    job_rows.append(tasks.merge(dpe, on="scenario_id", how="left",
                                validate="1:1"))

  tasks, conflicts = _select_scenario_results(
      pd.concat(job_rows, ignore_index=True))
  joined = manifest.merge(tasks, on="scenario_id", how="left", validate="1:1")
  matched = int(joined["task_id"].notna().sum())
  if not joined.empty and matched == 0:
    raise ValueError(
        "Manifest and Orion jobs have zero matching scenario ids; check the "
        "manifest path and remember that --release filters the scenario "
        "source release, not the backtest target release")
  result = _summarize(joined, list(job_ids))
  result["scenario_results"] = _dashboard_scenario_results(joined)
  result["manifest_audit"] = manifest_audit
  result["cross_job_result_conflicts"] = conflicts
  result["cross_job_result_conflict_count"] = len(conflicts)
  if conflicts:
    result["is_terminal_and_complete"] = False
  return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--job-id", type=int, action="append", required=True,
                      help="Repeat for an original job and resumed jobs")
  parser.add_argument("--manifest", type=Path, required=True)
  parser.add_argument("--release", default=None)
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if not args.orion_token:
    try:
      from orion_client.utils.config_utils import get_auth_token
      from voy_data_utils.regions import Regions
      args.orion_token = get_auth_token(None, Regions.CN)
    except ImportError as exc:
      raise SystemExit("Set ORION_TOKEN or pass --orion-token") from exc
  result = validate(args.job_id, args.manifest, args.release,
                    args.orion_token)
  print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
