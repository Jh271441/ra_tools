#!/usr/bin/env python3
"""Validate and publish one rolling RA binary-backtest result artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ra_repro_validate_orion import validate


COHORTS = ("positive_auto", "negative_auto", "positive_manual")
INDEPENDENT_REPLAY_FLAG = "--planning_enable_sim_assist_stuck_independent_replay"
STATE_RECOVERY_LEVEL4_FLAG = "--sim_state_recovery_level=4"
MAX_BACKTEST_CONCURRENCY = 20


def _state_recovery_levels(exec_args: Any) -> list[str]:
  """Return every explicitly configured simulation state recovery level."""
  tokens = str(exec_args or "").split()
  levels = []
  for index, token in enumerate(tokens):
    if token.startswith("--sim_state_recovery_level="):
      levels.append(token.partition("=")[2])
    elif token == "--sim_state_recovery_level" and index + 1 < len(tokens):
      levels.append(tokens[index + 1])
  return levels


def summarize_job_configuration(
    jobs: Sequence[dict[str, Any]],
    expected_binary_id: int,
    expected_scenario_ids: Sequence[int] | None = None,
    expected_max_concurrency: int | None = None,
    max_allowed_concurrency: int = MAX_BACKTEST_CONCURRENCY,
) -> dict[str, Any]:
  """Summarize immutable submission-time gates for a set of Orion jobs."""
  total_tasks = sum(len(job["tasks"]) for job in jobs)
  binary_mismatches = 0
  cache_mismatches = 0
  dpe_disabled = 0
  independent_replay_missing = 0
  state_recovery_level_mismatches = 0
  task_scenario_ids = []
  task_signature_parse_failures = 0
  per_job = []
  for job in jobs:
    tasks = job["tasks"]
    for task in tasks:
      try:
        task_scenario_ids.append(int(task["signature"]))
      except (KeyError, TypeError, ValueError):
        task_signature_parse_failures += 1
      args = task.get("task_args") or {}
      if hasattr(args, "as_dict"):
        args = args.as_dict()
      try:
        binary_matches = int(args.get("--binary-id")) == expected_binary_id
      except (TypeError, ValueError):
        binary_matches = False
      binary_mismatches += int(not binary_matches)
      cache_mismatches += int(args.get("--simulator-cache") != "disabled")
      dpe_disabled += int("--enable-dpe" not in args)
      independent_replay_missing += int(
          INDEPENDENT_REPLAY_FLAG not in str(
              args.get("--sim-exec-args", "")).split())
      state_recovery_level_mismatches += int(
          _state_recovery_levels(args.get("--sim-exec-args")) != ["4"])
    per_job.append({
        "job_id": int(job["job_id"]),
        "task_count": len(tasks),
        "cluster": str(job.get("cluster") or ""),
        "max_concurrency": int(job.get("max_concurrency") or 0),
    })

  cluster_mismatches = sum(
      item["cluster"] != "prod_gen4" for item in per_job)
  concurrency_mismatches = sum(
      not 1 <= item["max_concurrency"] <= max_allowed_concurrency or
      (expected_max_concurrency is not None and
       item["max_concurrency"] != expected_max_concurrency)
      for item in per_job)
  expected_task_set = (
      {int(value) for value in expected_scenario_ids}
      if expected_scenario_ids is not None else None)
  actual_task_set = set(task_scenario_ids)
  task_signature_duplicates = len(task_scenario_ids) - len(actual_task_set)
  expected_scenario_duplicates = (
      len(expected_scenario_ids) - len(expected_task_set)
      if expected_scenario_ids is not None else 0)
  missing_scenario_ids = sorted(
      expected_task_set - actual_task_set) if expected_task_set is not None else []
  unexpected_scenario_ids = sorted(
      actual_task_set - expected_task_set) if expected_task_set is not None else []
  gate_passed = bool(total_tasks and not any((
      binary_mismatches,
      cache_mismatches,
      dpe_disabled,
      independent_replay_missing,
      state_recovery_level_mismatches,
      cluster_mismatches,
      concurrency_mismatches,
      task_signature_parse_failures if expected_task_set is not None else 0,
      task_signature_duplicates if expected_task_set is not None else 0,
      expected_scenario_duplicates,
      len(missing_scenario_ids),
      len(unexpected_scenario_ids),
  )))
  return {
      "expected_binary_id": expected_binary_id,
      "expected_max_concurrency": expected_max_concurrency,
      "max_allowed_concurrency": max_allowed_concurrency,
      "job_count": len(jobs),
      "task_count": total_tasks,
      "binary_mismatches": binary_mismatches,
      "simulator_cache_mismatches": cache_mismatches,
      "dpe_disabled": dpe_disabled,
      "independent_replay_missing": independent_replay_missing,
      "state_recovery_level_mismatches": state_recovery_level_mismatches,
      "cluster_mismatches": cluster_mismatches,
      "concurrency_mismatches": concurrency_mismatches,
      "task_set_checked": expected_task_set is not None,
      "expected_scenario_count": (
          len(expected_scenario_ids)
          if expected_scenario_ids is not None else None),
      "actual_unique_scenario_count": len(actual_task_set),
      "task_signature_parse_failures": task_signature_parse_failures,
      "task_signature_duplicates": task_signature_duplicates,
      "expected_scenario_duplicates": expected_scenario_duplicates,
      "missing_scenario_ids": missing_scenario_ids,
      "unexpected_scenario_ids": unexpected_scenario_ids,
      "gate_passed": gate_passed,
      "jobs": per_job,
  }


def inspect_job_configuration(
    job_ids: Sequence[int],
    expected_binary_id: int,
    expected_scenario_ids: Sequence[int] | None = None,
    expected_max_concurrency: int | None = None,
    max_allowed_concurrency: int = MAX_BACKTEST_CONCURRENCY,
) -> dict[str, Any]:
  """Read task arguments and job placement settings from Orion storage."""
  try:
    from orion.db_accessor.job_accessor import JobAccessor
    from orion.db_accessor.task_accessor import TaskAccessor
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError(
        "Orion configuration gate requires Voyager Orion libraries") from exc

  jobs = []
  with TrailRegionMgr(Regions.CN, is_pre=False):
    for job_id in job_ids:
      metadata = JobAccessor.get(int(job_id))
      tasks = list(TaskAccessor.query({
          "job_id": int(job_id),
          "extra_fields": "task_args",
      }))
      jobs.append({
          "job_id": int(job_id),
          "cluster": metadata.get("cluster"),
          "max_concurrency": metadata.get("max_concurrency"),
          "tasks": tasks,
      })
  return summarize_job_configuration(
      jobs, expected_binary_id, expected_scenario_ids,
      expected_max_concurrency, max_allowed_concurrency)


def summarize_sources(manifest: pd.DataFrame,
                      scenario_results: Sequence[dict[str, Any]]) -> dict[str,
                                                                           Any]:
  required = {"release", "cohort", "scenario_id"}
  missing = required - set(manifest.columns)
  if missing:
    raise ValueError(f"Analysis manifest missing columns: {sorted(missing)}")
  manifest = manifest[manifest["cohort"].isin(COHORTS)].copy()
  manifest["scenario_id"] = manifest["scenario_id"].astype(int)
  results = pd.DataFrame(scenario_results)
  if results.empty:
    results = pd.DataFrame(columns=["scenario_id", "sim_triggered"])
  results["scenario_id"] = results["scenario_id"].astype(int)
  if results["scenario_id"].duplicated().any():
    raise ValueError("Scenario results contain duplicate scenario ids")
  joined = manifest.merge(
      results[["scenario_id", "sim_triggered"]],
      on="scenario_id",
      how="left",
      validate="1:1",
  )

  sources = {}
  for release, group in joined.groupby("release", sort=True):
    evaluated = group["sim_triggered"].notna()
    triggered = group["sim_triggered"].eq(True) & evaluated
    truth_positive = group["cohort"].isin(
        ("positive_auto", "positive_manual")) & evaluated
    truth_negative = group["cohort"].eq("negative_auto") & evaluated
    tp = int((truth_positive & triggered).sum())
    fn = int((truth_positive & ~triggered).sum())
    fp = int((truth_negative & triggered).sum())
    tn = int((truth_negative & ~triggered).sum())
    expected = len(group)
    evaluated_count = int(evaluated.sum())
    cohort_metrics = {}
    for cohort in COHORTS:
      cohort_group = group[group["cohort"].eq(cohort)]
      cohort_evaluated = cohort_group["sim_triggered"].notna()
      cohort_triggered = (
          cohort_group["sim_triggered"].eq(True) & cohort_evaluated)
      cohort_expected = len(cohort_group)
      cohort_evaluated_count = int(cohort_evaluated.sum())
      cohort_triggered_count = int(cohort_triggered.sum())
      cohort_metrics[cohort] = {
          "expected": cohort_expected,
          "evaluated": cohort_evaluated_count,
          "triggered": cohort_triggered_count,
          "not_triggered": cohort_evaluated_count - cohort_triggered_count,
          "trigger_rate": (
              cohort_triggered_count / cohort_evaluated_count
              if cohort_evaluated_count else None),
      }
    positive_auto = cohort_metrics["positive_auto"]
    positive_manual = cohort_metrics["positive_manual"]
    negative_auto = cohort_metrics["negative_auto"]
    positive_auto_not_triggered = int(positive_auto["not_triggered"])
    positive_manual_not_triggered = int(positive_manual["not_triggered"])
    negative_auto_not_triggered = int(negative_auto["not_triggered"])
    road_behavior_matches = (
        int(positive_auto["triggered"])
        + int(negative_auto["triggered"])
        + positive_manual_not_triggered
    )
    trigger_repro_fn = fn + negative_auto_not_triggered
    sources[str(release)] = {
        "expected": expected,
        "evaluated": evaluated_count,
        "dpe_coverage": evaluated_count / expected if expected else 0.0,
        # Raw canary confusion counts are retained for audit. Dashboard P/R is
        # post-stratified with these per-cohort trigger rates and the online
        # TP/FP/FN population; equal-size canary cohorts must not be treated as
        # the online class distribution.
        "estimated_tp": tp,
        "estimated_fp": fp,
        "estimated_fn": fn,
        "estimated_tn": tn,
        "positive_auto_not_triggered": positive_auto_not_triggered,
        "positive_manual_not_triggered": positive_manual_not_triggered,
        "negative_auto_not_triggered": negative_auto_not_triggered,
        "business_recall_fn": fn,
        "trigger_repro_fn": trigger_repro_fn,
        "trigger_repro_recall": (
            tp / (tp + trigger_repro_fn)
            if tp + trigger_repro_fn else 0.0),
        "road_behavior_matches": road_behavior_matches,
        "road_behavior_reproduction": (
            road_behavior_matches / evaluated_count
            if evaluated_count else 0.0),
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "estimation_method": "cohort_poststratification",
        "cohorts": cohort_metrics,
        "cohort_counts": {
            str(cohort): int(count)
            for cohort, count in group["cohort"].value_counts().items()
        },
    }
  return sources


def finalize(
    job_ids: Sequence[int],
    analysis_manifest_path: Path,
    target_release: str,
    binary_id: int,
    output_path: Path,
    token: str,
    allow_partial: bool,
    expected_max_concurrency: int | None = None,
) -> dict[str, Any]:
  manifest = pd.read_csv(analysis_manifest_path, low_memory=False)
  job_configuration = inspect_job_configuration(
      job_ids, binary_id, manifest["scenario_id"].astype(int).tolist(),
      expected_max_concurrency)
  if not job_configuration["gate_passed"]:
    raise RuntimeError(
        "Binary backtest submission configuration gate failed; refusing to "
        f"publish: {job_configuration}")
  validation = validate(job_ids, analysis_manifest_path, None, token)
  sources = summarize_sources(manifest, validation.get("scenario_results") or [])
  source_releases = sorted(sources)
  source_complete = all(
      item["expected"] == item["evaluated"] for item in sources.values())
  cohort_complete = all(
      set(item.get("cohorts") or {}) == set(COHORTS) and
      all(
          int(cohort["expected"]) > 0 and
          int(cohort["evaluated"]) == int(cohort["expected"]) and
          cohort["trigger_rate"] is not None
          for cohort in item["cohorts"].values())
      for item in sources.values())
  gate_passed = bool(
      validation.get("is_terminal_and_complete") and source_complete and
      cohort_complete)
  if not gate_passed and not allow_partial:
    raise RuntimeError(
        "Binary backtest quality gate is not complete; refusing to publish. "
        f"terminal_complete={validation.get('is_terminal_and_complete')}, "
        f"source_complete={source_complete}, "
        f"cohort_complete={cohort_complete}")

  payload: dict[str, Any] = {"targets": {}}
  if output_path.exists():
    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
      payload = loaded
  payload.setdefault("targets", {})
  payload["generated_at"] = datetime.now(timezone.utc).isoformat()
  payload["targets"][target_release] = {
      "target_release": target_release,
      "binary_id": binary_id,
      "job_ids": list(job_ids),
      "source_releases": source_releases,
      "window_size": len(source_releases),
      "analysis_manifest": str(analysis_manifest_path),
      "quality_gate_passed": gate_passed,
      "job_configuration": job_configuration,
      "quality": validation.get("quality") or {},
      "sources": sources,
  }
  output_path.parent.mkdir(parents=True, exist_ok=True)
  temporary = output_path.with_suffix(output_path.suffix + ".tmp")
  temporary.write_text(
      json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8")
  temporary.replace(output_path)
  return payload["targets"][target_release]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--job-id", type=int, action="append", required=True)
  parser.add_argument("--analysis-manifest", type=Path, required=True)
  parser.add_argument("--target-release", required=True)
  parser.add_argument("--binary-id", type=int, required=True)
  parser.add_argument(
      "--output", type=Path,
      default=Path("reports/ra_binary_backtest_20260831_metrics.json"))
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  parser.add_argument("--allow-partial", action="store_true")
  parser.add_argument(
      "--expected-max-concurrency", type=int,
      default=MAX_BACKTEST_CONCURRENCY)
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if not args.orion_token:
    try:
      from orion_client.utils.config_utils import get_auth_token
      from voy_data_utils.regions import Regions
      args.orion_token = get_auth_token(None, Regions.CN)
    except ImportError as exc:
      raise SystemExit("Set ORION_TOKEN or load Voyager Orion libraries") from exc
  result = finalize(
      args.job_id,
      args.analysis_manifest,
      args.target_release,
      args.binary_id,
      args.output,
      args.orion_token,
      args.allow_partial,
      args.expected_max_concurrency,
  )
  print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
