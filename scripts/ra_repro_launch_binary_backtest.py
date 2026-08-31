#!/usr/bin/env python3
"""Plan and optionally launch a rolling RA binary backtest Orion job.

The target release provides the binary/runtime template.  Scenarios are read
from one or more same-or-earlier release cohorts in the immutable full-release
manifest.  Dry-run is the default; ``--execute`` is required to create an
Orion job.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


TEMPLATE_JOBS = {
    "gen4-release-20260605": 45142557,
    "gen4-release-20260612": 45142603,
    "gen4-release-20260618": 45142545,
    "gen4-release-20260626": 45142543,
    "gen4-release-20260710": 45142555,
    "gen4-release-20260717": 45142549,
    "gen4-release-20260724": 45142551,
    "gen4-release-20260731": 45142547,
    "gen4-release-20260807": 45142565,
    "gen4-release-20260814": 45142567,
    "gen4-release-20260821": 45142569,
}
COHORTS = ("positive_auto", "negative_auto", "positive_manual")
INDEPENDENT_REPLAY_FLAG = "--planning_enable_sim_assist_stuck_independent_replay"
MAX_BACKTEST_CONCURRENCY = 20


def _write_registry(path: Path, registry: dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix(path.suffix + ".tmp")
  temporary.write_text(
      json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8")
  temporary.replace(path)


def _load_api(need_launch: bool):
  try:
    from orion.db_accessor.job_accessor import JobAccessor
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion.model.constants import TaskArgKeys
    from orion_client.api.clone_job_impl import clone_job
    from orion_client.utils.config_utils import get_auth_token
    from orion_internal.model.constants import JobArgKeys
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError(
        "Orion Python libraries are unavailable; load the Voyager "
        ".vscode/voyager.env PYTHONPATH and LD_LIBRARY_PATH") from exc
  launch_job = None
  if need_launch:
    try:
      from orion_client.api.launch_job_impl import launch_job
    except ImportError as exc:
      raise RuntimeError(
          "Orion launch dependencies are unavailable; use the validated "
          "Voyager launch environment") from exc
  return (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job,
          get_auth_token, JobArgKeys, OrionTask, Regions, TrailRegionMgr)


def _stable_rank(seed: str, row: pd.Series) -> str:
  identity = ":".join((
      seed,
      str(row["release"]),
      str(row["cohort"]),
      str(int(row["scenario_id"])),
      str(row["issue_id"]),
  ))
  return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _manifest_hash(frame: pd.DataFrame) -> str:
  rows = [
      f"{row.release}|{row.cohort}|{int(row.scenario_id)}|{row.issue_id}"
      for row in frame.sort_values(
          ["release", "cohort", "scenario_id"]).itertuples()
  ]
  return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def select_manifest(manifest_path: Path, source_releases: Sequence[str],
                    sample_per_cohort: int, seed: str) -> tuple[pd.DataFrame,
                                                                  dict[str,
                                                                       int]]:
  frame = pd.read_csv(manifest_path, low_memory=False)
  required = {
      "release", "cohort", "scenario_id", "issue_id", "upload_status",
      "validation_error"
  }
  missing = required - set(frame.columns)
  if missing:
    raise ValueError(f"Manifest missing columns: {sorted(missing)}")
  unknown = sorted(set(source_releases) - set(frame["release"].astype(str)))
  if unknown:
    raise ValueError(f"Manifest has no source releases: {unknown}")
  frame = frame[
      frame["release"].isin(source_releases) & frame["cohort"].isin(COHORTS)
  ].copy()
  if frame.empty:
    raise ValueError("No manifest rows matched source releases/cohorts")
  if frame["validation_error"].fillna("").astype(str).ne("").any():
    raise ValueError("Selected manifest contains invalid scenario conversions")

  statuses = frame["upload_status"].fillna("").astype(str)
  no_bag = statuses.str.contains("does not have bags", regex=False)
  missing_trip = (
      statuses.str.contains("trip_id(", regex=False) &
      statuses.str.contains("does not exist", regex=False))
  excluded = no_bag | missing_trip
  unexpected = sorted(
      set(statuses[~excluded]) - {"uploaded", "existing"})
  if unexpected:
    raise ValueError(f"Manifest has unusable upload statuses: {unexpected}")
  audit = {
      "source_rows": len(frame),
      "excluded_no_bag": int(no_bag.sum()),
      "excluded_missing_trip": int(missing_trip.sum()),
  }
  frame = frame[~excluded].copy()
  if frame["scenario_id"].isna().any():
    raise ValueError("Usable manifest rows contain missing scenario ids")
  issue_ids = frame["issue_id"].fillna("").astype(str).str.strip()
  if issue_ids.eq("").any():
    raise ValueError("Usable manifest rows contain missing issue ids")
  if issue_ids.duplicated().any():
    raise ValueError("Usable manifest rows contain duplicate issue ids")
  frame["issue_id"] = issue_ids
  frame["scenario_id"] = frame["scenario_id"].astype(int)
  if frame["scenario_id"].duplicated().any():
    raise ValueError("Selected manifest contains duplicate scenario ids")

  if sample_per_cohort > 0:
    selected = []
    for (_, _), group in frame.groupby(["release", "cohort"], sort=True):
      ranked = group.copy()
      ranked["_backtest_rank"] = ranked.apply(
          lambda row: _stable_rank(seed, row), axis=1)
      selected.append(ranked.sort_values("_backtest_rank").head(
          sample_per_cohort).drop(columns="_backtest_rank"))
    frame = pd.concat(selected, ignore_index=True)
  frame["backtest_source_release"] = frame["release"]
  return frame.sort_values(
      ["release", "cohort", "scenario_id"]).reset_index(drop=True), audit


def _registry_key(target_release: str, source_releases: Sequence[str],
                  sample_per_cohort: int, seed: str,
                  selected_hash: str, max_concurrency: int) -> str:
  sources = ",".join(source_releases)
  sim_config_hash = hashlib.sha256(
      (f"{INDEPENDENT_REPLAY_FLAG}|simulator_cache=disabled|dpe=enabled|"
       f"max_concurrency={max_concurrency}").encode("utf-8")).hexdigest()[:12]
  return (f"target={target_release}|sources={sources}|sample="
          f"{sample_per_cohort}|seed={seed}|manifest={selected_hash[:16]}|"
          f"sim_config={sim_config_hash}")


def _enable_independent_replay(task: Any) -> None:
  exec_args_key = "--sim-exec-args"
  exec_args = str(task.arguments.get(exec_args_key, ""))
  tokens = exec_args.split()
  if INDEPENDENT_REPLAY_FLAG not in tokens:
    tokens.append(INDEPENDENT_REPLAY_FLAG)
  task.arguments[exec_args_key] = " " + " ".join(tokens)
  if INDEPENDENT_REPLAY_FLAG not in task.arguments[exec_args_key].split():
    raise RuntimeError("Failed to enable independent RA replay")


def build_and_maybe_launch(
    manifest_path: Path,
    target_release: str,
    source_releases: Sequence[str],
    sample_per_cohort: int,
    seed: str,
    selected_manifest_path: Path,
    analysis_manifest_path: Path | None,
    registry_path: Path,
    max_concurrency: int,
    execute: bool,
    token: str | None,
) -> dict[str, Any]:
  (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job,
   get_auth_token, JobArgKeys, OrionTask, Regions,
   TrailRegionMgr) = _load_api(execute)
  selected, audit = select_manifest(
      manifest_path, source_releases, sample_per_cohort, seed)
  selected_hash = _manifest_hash(selected)
  key = _registry_key(target_release, source_releases, sample_per_cohort, seed,
                      selected_hash, max_concurrency)

  registry: dict[str, Any] = {}
  if registry_path.exists():
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
  if key in registry:
    raise RuntimeError(
        f"Refusing duplicate launch; registry already contains {key}: "
        f"{registry[key]}")

  template_job_id = TEMPLATE_JOBS[target_release]
  token = token or get_auth_token(None, Regions.CN)
  with TrailRegionMgr(Regions.CN, is_pre=False):
    metadata = JobAccessor.get(template_job_id)
    template_tasks = list(TaskAccessor.query({
        "job_id": template_job_id,
        "kind": OrionTask.MAPPER,
        "extra_fields": "task_args",
    }))
  if not metadata or not template_tasks:
    raise RuntimeError(f"Template Job {template_job_id} is incomplete")
  if metadata["cluster"] != "prod_gen4":
    raise RuntimeError(
        f"Gen4 backtest requires prod_gen4, got {metadata['cluster']}")
  if not 1 <= max_concurrency <= MAX_BACKTEST_CONCURRENCY:
    raise ValueError(
        "RA binary backtest max_concurrency must be between 1 and "
        f"{MAX_BACKTEST_CONCURRENCY}")

  template_task_id = int(template_tasks[0]["id"])
  orion_job = clone_job(
      job_id=template_job_id,
      task_id_list=[template_task_id],
      region=Regions.CN,
  )
  template = OrionTask()
  template.CopyFrom(orion_job.mapper_tasks[0])
  orion_job.ClearField("mapper_tasks")
  for scenario_id in selected["scenario_id"]:
    task = orion_job.mapper_tasks.add()
    task.CopyFrom(template)
    task.signature = str(scenario_id)
    scenario_key = (TaskArgKeys.SCENARIO_ID if hasattr(
        TaskArgKeys, "SCENARIO_ID") else "--scenario-id")
    task.arguments[scenario_key] = str(scenario_id)
    task.arguments[TaskArgKeys.SIMULATOR_CACHE] = "disabled"
    _enable_independent_replay(task)

  for task in orion_job.mapper_tasks:
    if "--enable-dpe" not in task.arguments:
      raise RuntimeError("RA binary backtest requires DPE on every task")
    if task.arguments[TaskArgKeys.SIMULATOR_CACHE] != "disabled":
      raise RuntimeError("RA binary backtest requires simulator cache disabled")
    if INDEPENDENT_REPLAY_FLAG not in str(
        task.arguments.get("--sim-exec-args", "")).split():
      raise RuntimeError("RA binary backtest requires independent replay")

  date_token = target_release.removeprefix("gen4-release-")
  source_token = "_".join(item.removeprefix("gen4-release-")
                          for item in source_releases)
  mode = f"canary{sample_per_cohort}" if sample_per_cohort else "full"
  orion_job.description = f"RA_binary_backtest_{date_token}_{mode}"
  orion_job.labels[:] = [
      "ra_binary_backtest_20260831", target_release, "simulation",
      "binary-backtest", mode, f"sources_{source_token}"
  ]
  orion_job.arguments[JobArgKeys.SIMULATOR_CACHE] = "disabled"

  selected = selected.copy()
  selected["backtest_target_release"] = target_release
  selected["backtest_template_job_id"] = template_job_id
  selected["backtest_manifest_hash"] = selected_hash
  selected_manifest_path.parent.mkdir(parents=True, exist_ok=True)
  selected.to_csv(selected_manifest_path, index=False)

  analysis_scenario_count = len(selected)
  if analysis_manifest_path is not None:
    if target_release in source_releases:
      analysis = selected.copy()
    else:
      diagonal, _ = select_manifest(
          manifest_path, [target_release], sample_per_cohort, seed)
      diagonal = diagonal.copy()
      diagonal["backtest_target_release"] = target_release
      diagonal["backtest_template_job_id"] = template_job_id
      diagonal["backtest_manifest_hash"] = selected_hash
      analysis = pd.concat([selected, diagonal], ignore_index=True)
    if analysis["scenario_id"].duplicated().any():
      raise ValueError("Backtest analysis manifest has duplicate scenarios")
    analysis_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    analysis.to_csv(analysis_manifest_path, index=False)
    analysis_scenario_count = len(analysis)

  counts = selected.groupby(["release", "cohort"]).size()
  summary: dict[str, Any] = {
      "registry_key": key,
      "target_release": target_release,
      "template_job_id": template_job_id,
      "binary_id": int(template.arguments[TaskArgKeys.BINARY_ID]),
      "source_releases": list(source_releases),
      "sample_per_cohort": sample_per_cohort,
      "seed": seed,
      "scenario_count": len(selected),
      "cohort_counts": {
          f"{release}:{cohort}": int(value)
          for (release, cohort), value in counts.items()
      },
      "selected_manifest": str(selected_manifest_path),
      "analysis_manifest": (
          str(analysis_manifest_path) if analysis_manifest_path else None),
      "analysis_scenario_count": analysis_scenario_count,
      "diagonal_scenarios_require_matching_job": (
          target_release not in source_releases),
      "selected_manifest_hash": selected_hash,
      **audit,
      "cluster": metadata["cluster"],
      "runtime_reference": metadata["runtime_reference"],
      "priority": metadata["priority"],
      "max_concurrency": max_concurrency,
      "simulator_cache": "disabled",
      "required_sim_flag": INDEPENDENT_REPLAY_FLAG,
      "execute": execute,
  }
  if not execute:
    return summary

  assert launch_job is not None
  summary["launch_state"] = "pending"
  summary["launch_requested_at"] = datetime.now(timezone.utc).isoformat()
  summary["job_id"] = None
  registry[key] = summary
  _write_registry(registry_path, registry)
  try:
    job_id = launch_job(
        orion_job,
        cluster_name=metadata["cluster"],
        max_concurrency=max_concurrency,
        priority=metadata["priority"],
        override_runtime=metadata["runtime_reference"],
        override_token=token,
    )
  except Exception as exc:
    summary["launch_state"] = "uncertain"
    summary["launch_error"] = f"{type(exc).__name__}: {exc}"
    registry[key] = summary
    _write_registry(registry_path, registry)
    raise
  summary["job_id"] = job_id
  summary["launch_state"] = "launched"
  summary["launched_at"] = datetime.now(timezone.utc).isoformat()
  registry[key] = summary
  _write_registry(registry_path, registry)
  return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--manifest", type=Path, required=True)
  parser.add_argument("--target-release", choices=sorted(TEMPLATE_JOBS),
                      required=True)
  parser.add_argument("--source-release", action="append", required=True,
                      dest="source_releases")
  parser.add_argument("--sample-per-cohort", type=int, default=10)
  parser.add_argument("--seed", default="ra_binary_backtest_20260831_v1")
  parser.add_argument(
      "--max-concurrency", type=int, default=MAX_BACKTEST_CONCURRENCY)
  parser.add_argument("--selected-manifest", type=Path, required=True)
  parser.add_argument("--analysis-manifest", type=Path, default=None)
  parser.add_argument(
      "--registry", type=Path,
      default=Path("reports/ra_binary_backtest_20260831_jobs.json"))
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if args.sample_per_cohort < 0:
    raise SystemExit("--sample-per-cohort must be >= 0 (0 means full)")
  if not 1 <= args.max_concurrency <= MAX_BACKTEST_CONCURRENCY:
    raise SystemExit(
        "--max-concurrency must be between 1 and "
        f"{MAX_BACKTEST_CONCURRENCY}")
  release_order = list(TEMPLATE_JOBS)
  target_index = release_order.index(args.target_release)
  if any(release_order.index(item) > target_index
         for item in args.source_releases):
    raise SystemExit("Every scenario release must be no later than target release")
  print(json.dumps(build_and_maybe_launch(
      args.manifest,
      args.target_release,
      args.source_releases,
      args.sample_per_cohort,
      args.seed,
      args.selected_manifest,
      args.analysis_manifest,
      args.registry,
      args.max_concurrency,
      args.execute,
      args.orion_token,
  ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
