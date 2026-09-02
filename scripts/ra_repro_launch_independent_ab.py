#!/usr/bin/env python3
"""Launch one controlled Orion A/B for independent RA replay.

The two mapper tasks use the same binary, scenario, runtime, map, and DPE
configuration.  Control uses native level-4 recovery; feature additionally
keeps simulation-produced RA seed/component state.  The job is forced to one
concurrent mapper and both simulator/inference caches are disabled.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Sequence


DEFAULT_TEMPLATE_JOB_ID = 43988133
DEFAULT_SCENARIO_ID = 29433817
INDEPENDENT_REPLAY_FLAG = "--planning_enable_sim_assist_stuck_independent_replay"
STATE_RECOVERY_LEVEL4_FLAG = "--sim_state_recovery_level=4"


def _load_api():
  try:
    from orion.db_accessor.job_accessor import JobAccessor
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion.model.constants import TaskArgKeys
    from orion_client.api.clone_job_impl import clone_job
    from orion_client.api.launch_job_impl import launch_job
    from orion_internal.model.constants import JobArgKeys
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError(
        "Orion Python libraries are unavailable; run through "
        "scripts/run_with_voyager_env.py") from exc
  return (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job,
          JobArgKeys, OrionTask, Regions, TrailRegionMgr)


def _controlled_exec_args(raw: str, independent: bool) -> str:
  tokens = raw.split()
  result = []
  skip_next = False
  for token in tokens:
    if skip_next:
      skip_next = False
      continue
    if token == "--sim_state_recovery_level":
      skip_next = True
      continue
    if token.startswith("--sim_state_recovery_level="):
      continue
    if token == INDEPENDENT_REPLAY_FLAG:
      continue
    result.append(token)
  result.append(STATE_RECOVERY_LEVEL4_FLAG)
  if independent:
    result.append(INDEPENDENT_REPLAY_FLAG)
  return " " + " ".join(result)


def _write_registry(path: Path, payload: dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix(path.suffix + ".tmp")
  temporary.write_text(
      json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8")
  temporary.replace(path)


def build_and_maybe_launch(
    binary_id: int,
    scenario_id: int,
    template_job_id: int,
    token: str,
    registry_path: Path,
    execute: bool,
) -> dict[str, Any]:
  (JobAccessor, TaskAccessor, TaskArgKeys, clone_job, launch_job, JobArgKeys,
   OrionTask, Regions, TrailRegionMgr) = _load_api()
  with TrailRegionMgr(Regions.CN, is_pre=False):
    metadata = JobAccessor.get(template_job_id)
    template_rows = list(TaskAccessor.query({
        "job_id": template_job_id,
        "kind": OrionTask.MAPPER,
        "extra_fields": "task_args",
    }))
  if not metadata or len(template_rows) != 1:
    raise RuntimeError(
        f"Expected one complete template task in job {template_job_id}")
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

    exec_tokens = task.arguments["--sim-exec-args"].split()
    if exec_tokens.count(STATE_RECOVERY_LEVEL4_FLAG) != 1:
      raise RuntimeError("Each arm must contain exactly one level-4 flag")
    if (INDEPENDENT_REPLAY_FLAG in exec_tokens) != independent:
      raise RuntimeError(f"Independent replay flag mismatch for {arm}")
    if "--enable-dpe" not in task.arguments:
      raise RuntimeError("Each arm must enable DPE")
    if "--use-trip-hdmap" not in task.arguments:
      raise RuntimeError("Each arm must use the road-test trip map")
    if "--enable-infer-cache" in task.arguments:
      raise RuntimeError("Inference cache must be disabled for fair A/B")
    task_summaries.append({
        "arm": arm,
        "signature": task.signature,
        "scenario_id": scenario_id,
        "binary_id": binary_id,
        "simulator_cache": task.arguments[TaskArgKeys.SIMULATOR_CACHE],
        "output_bag": task.arguments["--upload-output-bag"],
        "independent_replay": independent,
        "sim_exec_args": task.arguments["--sim-exec-args"],
    })

  date_token = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
  orion_job.description = (
      f"RA_independent_replay_AB_cr6657869_scenario_{scenario_id}")
  orion_job.labels[:] = [
      "ra_independent_replay_ab", "cr_6657869", "simulation", "canary",
      f"scenario_{scenario_id}",
  ]
  orion_job.arguments[JobArgKeys.SIMULATOR_CACHE] = "disabled"

  summary = {
      "template_job_id": template_job_id,
      "template_task_id": template_task_id,
      "scenario_id": scenario_id,
      "binary_id": binary_id,
      "cluster": metadata["cluster"],
      "runtime_reference": metadata["runtime_reference"],
      "priority": metadata["priority"],
      "max_concurrency": 1,
      "simulator_cache": "disabled",
      "inference_cache": "disabled",
      "task_count": len(task_summaries),
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
  summary["launch_token"] = date_token
  _write_registry(registry_path, summary)
  return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--binary-id", type=int, required=True)
  parser.add_argument("--scenario-id", type=int, default=DEFAULT_SCENARIO_ID)
  parser.add_argument(
      "--template-job-id", type=int, default=DEFAULT_TEMPLATE_JOB_ID)
  parser.add_argument(
      "--registry", type=Path,
      default=Path("reports/ra_independent_replay_cr6657869_ab_job.json"))
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  parser.add_argument("--execute", action="store_true")
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if args.binary_id <= 0:
    raise SystemExit("--binary-id must be positive")
  if not args.orion_token:
    raise SystemExit("Set ORION_TOKEN or pass --orion-token")
  summary = build_and_maybe_launch(
      args.binary_id,
      args.scenario_id,
      args.template_job_id,
      args.orion_token,
      args.registry,
      args.execute,
  )
  print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
