#!/usr/bin/env python3
"""Build and optionally launch one full-release RA reproduction Orion job.

The script clones a validated sample task as the execution template, replaces
only scenario identity, disables simulator cache, and launches every uploaded
scenario in the supplied release manifest.  Dry-run is the default.
"""

from __future__ import annotations

import argparse
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


def _load_api():
  try:
    from orion.db_accessor.job_accessor import JobAccessor
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion.model.constants import TaskArgKeys
    from orion_client.api.clone_job_impl import clone_job
    from orion_client.api.launch_job_impl import launch_job
    from orion_client.utils.config_utils import get_auth_token
    from orion_internal.model.constants import JobArgKeys
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError(
        "Orion Python libraries are unavailable; add Voyager Orion build/lib "
        "directories to PYTHONPATH") from exc
  return (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job,
          get_auth_token, JobArgKeys, OrionTask, Regions, TrailRegionMgr)


def _load_manifest(path: Path, release: str) -> tuple[pd.DataFrame, dict[str, int]]:
  frame = pd.read_csv(path, low_memory=False)
  frame = frame[frame["release"].eq(release)].copy()
  if frame.empty:
    raise ValueError(f"Manifest has no rows for {release}")
  if frame["validation_error"].fillna("").astype(str).ne("").any():
    raise ValueError("Manifest contains invalid scenario conversions")
  allowed_statuses = {"uploaded", "existing"}
  statuses = frame["upload_status"].astype(str)
  no_bag = statuses.str.contains("does not have bags", regex=False)
  missing_trip = (
      statuses.str.contains("trip_id(", regex=False) &
      statuses.str.contains("does not exist", regex=False))
  nonretryable = no_bag | missing_trip
  bad_statuses = sorted(
      set(statuses[~nonretryable]) - allowed_statuses)
  if bad_statuses:
    raise ValueError(f"Manifest has unusable upload statuses: {bad_statuses}")
  exclusions = {
      "source_rows": len(frame),
      "excluded_no_bag": int(no_bag.sum()),
      "excluded_missing_trip": int(missing_trip.sum()),
  }
  frame = frame[~nonretryable].copy()
  if frame["scenario_id"].isna().any():
    raise ValueError("Manifest contains missing scenario ids")
  frame["scenario_id"] = frame["scenario_id"].astype(int)
  if frame["scenario_id"].duplicated().any():
    raise ValueError("Manifest contains duplicate scenario ids")
  if frame["issue_id"].astype(str).duplicated().any():
    raise ValueError("Manifest contains duplicate issue ids")
  return frame, exclusions


def build_and_maybe_launch(manifest_path: Path, release: str,
                           max_concurrency: int, run_label: str,
                           execute: bool, token: str | None,
                           registry_path: Path) -> dict[str, Any]:
  (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job,
   get_auth_token, JobArgKeys, OrionTask, Regions,
   TrailRegionMgr) = _load_api()
  template_job_id = TEMPLATE_JOBS[release]
  frame, exclusions = _load_manifest(manifest_path, release)
  description = f"RA_repro_full_{release.removeprefix('gen4-release-')}"

  registry = {}
  if registry_path.exists():
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
  if release in registry:
    raise RuntimeError(
        f"Refusing duplicate launch; registry already has {release}: "
        f"{registry[release]}")

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
  template_task_id = int(template_tasks[0]["id"])
  orion_job = clone_job(
      job_id=template_job_id,
      task_id_list=[template_task_id],
      region=Regions.CN,
  )
  template = OrionTask()
  template.CopyFrom(orion_job.mapper_tasks[0])
  orion_job.ClearField("mapper_tasks")
  for scenario_id in frame["scenario_id"]:
    task = orion_job.mapper_tasks.add()
    task.CopyFrom(template)
    task.signature = str(scenario_id)
    task.arguments[TaskArgKeys.SCENARIO_ID if hasattr(
        TaskArgKeys, "SCENARIO_ID") else "--scenario-id"] = str(scenario_id)
    task.arguments[TaskArgKeys.SIMULATOR_CACHE] = "disabled"

  orion_job.description = description
  labels = [run_label, release, "simulation", "full"]
  orion_job.labels[:] = labels
  orion_job.arguments[JobArgKeys.SIMULATOR_CACHE] = "disabled"

  summary = {
      "release": release,
      "template_job_id": template_job_id,
      "binary_id": int(template.arguments[TaskArgKeys.BINARY_ID]),
      "scenario_count": len(frame),
      **exclusions,
      "cohort_counts": {
          str(key): int(value)
          for key, value in frame["cohort"].value_counts().sort_index().items()
      },
      "cluster": metadata["cluster"],
      "runtime_reference": metadata["runtime_reference"],
      "priority": metadata["priority"],
      "max_concurrency": max_concurrency,
      "simulator_cache": "disabled",
      "execute": execute,
  }
  if not execute:
    return summary

  job_id = launch_job(
      orion_job,
      cluster_name=metadata["cluster"],
      max_concurrency=max_concurrency,
      priority=metadata["priority"],
      override_runtime=metadata["runtime_reference"],
      override_token=token,
  )
  summary["job_id"] = job_id
  registry[release] = summary
  registry_path.parent.mkdir(parents=True, exist_ok=True)
  registry_path.write_text(
      json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8")
  return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--manifest", type=Path, required=True)
  parser.add_argument("--release", choices=sorted(TEMPLATE_JOBS), required=True)
  parser.add_argument("--max-concurrency", type=int, default=100)
  parser.add_argument("--run-label", default="ra_repro_full_20260829")
  parser.add_argument(
      "--registry", type=Path,
      default=Path("reports/ra_repro_full_20260829_jobs.json"))
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if not 1 <= args.max_concurrency <= 100:
    raise SystemExit("--max-concurrency must be between 1 and 100")
  print(json.dumps(build_and_maybe_launch(
      args.manifest, args.release, args.max_concurrency, args.run_label,
      args.execute, args.orion_token, args.registry),
      ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
