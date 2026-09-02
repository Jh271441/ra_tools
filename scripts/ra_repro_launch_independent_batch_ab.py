#!/usr/bin/env python3
"""Launch a paired, cache-free Orion A/B across an audited scenario cohort."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Sequence

from scripts.ra_repro_launch_independent_ab import (
    INDEPENDENT_REPLAY_FLAG,
    STATE_RECOVERY_LEVEL4_FLAG,
    _controlled_exec_args,
    _write_registry,
)


DEFAULT_TEMPLATE_JOB_ID = 45142551


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
        "Orion Python libraries are unavailable; run through "
        "scripts/run_with_voyager_env.py") from exc
  return (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job,
          get_auth_token, JobArgKeys, OrionTask, Regions, TrailRegionMgr)


def _load_manifest(path: Path) -> dict[str, Any]:
  payload = json.loads(path.read_text(encoding="utf-8"))
  rows = payload.get("rows") or []
  if not rows:
    raise ValueError("A/B manifest has no rows")
  scenario_ids = [int(row["scenario_id"]) for row in rows]
  issue_ids = [str(row["issue_id"]) for row in rows]
  if len(scenario_ids) != len(set(scenario_ids)):
    raise ValueError("A/B manifest contains duplicate scenario ids")
  if len(issue_ids) != len(set(issue_ids)):
    raise ValueError("A/B manifest contains duplicate issue ids")
  allowed_cohorts = {"positive_auto", "negative_auto", "positive_manual"}
  unknown = {str(row["cohort"]) for row in rows} - allowed_cohorts
  if unknown:
    raise ValueError(f"A/B manifest contains unknown cohorts: {sorted(unknown)}")
  return payload


def build_and_maybe_launch(
    manifest_path: Path,
    binary_id: int,
    template_job_id: int,
    registry_path: Path,
    execute: bool,
    token: str | None,
) -> dict[str, Any]:
  (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job,
   get_auth_token, JobArgKeys, OrionTask, Regions,
   TrailRegionMgr) = _load_api()
  manifest = _load_manifest(manifest_path)
  rows = manifest["rows"]
  with TrailRegionMgr(Regions.CN, is_pre=False):
    metadata = JobAccessor.get(template_job_id)
    template_rows = list(TaskAccessor.query({
        "job_id": template_job_id,
        "kind": OrionTask.MAPPER,
        "extra_fields": "task_args",
    }))
  if not metadata or not template_rows:
    raise RuntimeError(f"Template job {template_job_id} is incomplete")
  if metadata["cluster"] != "prod_gen4":
    raise RuntimeError(
        f"Gen4 RA A/B requires prod_gen4, got {metadata['cluster']}")

  template_task_id = int(template_rows[0]["id"])
  orion_job = clone_job(
      job_id=template_job_id,
      task_id_list=[template_task_id],
      region=Regions.CN,
  )
  template = OrionTask()
  template.CopyFrom(orion_job.mapper_tasks[0])
  scenario_key = (TaskArgKeys.SCENARIO_ID if hasattr(
      TaskArgKeys, "SCENARIO_ID") else "--scenario-id")
  orion_job.ClearField("mapper_tasks")
  task_summaries = []
  for row in rows:
    scenario_id = int(row["scenario_id"])
    for arm, independent in (("control", False), ("feature", True)):
      task = orion_job.mapper_tasks.add()
      task.CopyFrom(template)
      task.signature = f"{scenario_id}-{arm}"
      task.arguments[scenario_key] = str(scenario_id)
      task.arguments[TaskArgKeys.BINARY_ID] = str(binary_id)
      task.arguments[TaskArgKeys.SIMULATOR_CACHE] = "disabled"
      task.arguments["--upload-output-bag"] = "always"
      task.arguments.pop("--enable-infer-cache", None)
      task.arguments["--sim-exec-args"] = _controlled_exec_args(
          str(task.arguments.get("--sim-exec-args", "")), independent)
      tokens = task.arguments["--sim-exec-args"].split()
      if tokens.count(STATE_RECOVERY_LEVEL4_FLAG) != 1:
        raise RuntimeError(f"Bad level-4 flags for {task.signature}")
      if (INDEPENDENT_REPLAY_FLAG in tokens) != independent:
        raise RuntimeError(f"Independent replay mismatch for {task.signature}")
      if "--enable-dpe" not in task.arguments:
        raise RuntimeError(f"DPE is disabled for {task.signature}")
      if "--use-trip-hdmap" not in task.arguments:
        raise RuntimeError(f"Trip map is disabled for {task.signature}")
      task_summaries.append({
          "signature": task.signature,
          "scenario_id": scenario_id,
          "issue_id": str(row["issue_id"]),
          "cohort": str(row["cohort"]),
          "stratum": str(row["stratum"]),
          "arm": arm,
          "independent_replay": independent,
      })

  orion_job.description = "RA_independent_replay_batch_AB_cr6657869_0724"
  orion_job.labels[:] = [
      "ra_independent_replay_batch_ab",
      "cr_6657869",
      "gen4-release-20260724",
      "simulation",
  ]
  orion_job.arguments[JobArgKeys.SIMULATOR_CACHE] = "disabled"
  summary = {
      "manifest": str(manifest_path),
      "release": manifest["release"],
      "sampling_seed": manifest["seed"],
      "source_job_id": manifest["source_job_id"],
      "template_job_id": template_job_id,
      "template_task_id": template_task_id,
      "binary_id": binary_id,
      "cluster": metadata["cluster"],
      "runtime_reference": metadata["runtime_reference"],
      "priority": metadata["priority"],
      "max_concurrency": 1,
      "scenario_count": len(rows),
      "task_count": len(task_summaries),
      "simulator_cache": "disabled",
      "inference_cache": "disabled",
      "output_bag": "always",
      "stratum_counts": manifest["sampling"],
      "tasks": task_summaries,
      "execute": execute,
  }
  if not execute:
    return summary
  if registry_path.exists():
    previous = json.loads(registry_path.read_text(encoding="utf-8"))
    if previous.get("job_id"):
      raise RuntimeError(
          f"Refusing duplicate launch; registry has job {previous['job_id']}")
  token = token or get_auth_token(None, Regions.CN)
  summary["launch_state"] = "pending"
  summary["launch_requested_at"] = datetime.now(timezone.utc).isoformat()
  _write_registry(registry_path, summary)
  job_id = launch_job(
      orion_job,
      cluster_name=metadata["cluster"],
      max_concurrency=1,
      priority=metadata["priority"],
      override_runtime=metadata["runtime_reference"],
      override_token=token,
  )
  summary["job_id"] = int(job_id)
  summary["launch_state"] = "launched"
  summary["launched_at"] = datetime.now(timezone.utc).isoformat()
  _write_registry(registry_path, summary)
  return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--manifest", type=Path, required=True)
  parser.add_argument("--binary-id", type=int, required=True)
  parser.add_argument(
      "--template-job-id", type=int, default=DEFAULT_TEMPLATE_JOB_ID)
  parser.add_argument(
      "--registry",
      type=Path,
      default=Path(
          "reports/ra_independent_replay_cr6657869_batch_ab_job.json"),
  )
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  parser.add_argument("--execute", action="store_true")
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if args.binary_id <= 0:
    raise SystemExit("--binary-id must be positive")
  print(json.dumps(build_and_maybe_launch(
      args.manifest,
      args.binary_id,
      args.template_job_id,
      args.registry,
      args.execute,
      args.orion_token,
  ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
