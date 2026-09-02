#!/usr/bin/env python3
"""Analyze the controlled independent-RA-replay Orion A/B canary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ra_api.sim_result_api import SimResultClient


_TRIGGER_METRIC = "dpe_assist_channel_triggered__group1"
_TERMINAL_STATUSES = {3, 4, 5}


def _load_orion_api():
  try:
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError(
        "Orion Python libraries are unavailable; run through "
        "scripts/run_with_voyager_env.py") from exc
  return TaskAccessor, OrionTask, Regions, TrailRegionMgr


def _result_dict(value: Any) -> dict[str, Any]:
  if value is None:
    return {}
  if hasattr(value, "as_dict"):
    return value.as_dict()
  if isinstance(value, dict):
    return value
  raise TypeError(f"Unsupported Orion result type: {type(value)!r}")


def analyze(job_id: int) -> dict[str, Any]:
  TaskAccessor, OrionTask, Regions, TrailRegionMgr = _load_orion_api()
  with TrailRegionMgr(Regions.CN, is_pre=False):
    tasks = list(TaskAccessor.query({
        "job_id": job_id,
        "kind": OrionTask.MAPPER,
        "extra_fields": "task_args,result",
    }))
  if len(tasks) != 2:
    raise RuntimeError(f"Expected two mapper tasks, got {len(tasks)}")

  dpe = SimResultClient().query_all_pages(
      job_id,
      metrics=["dpe_assist_channel_triggered"],
      page_size=20,
  )
  dpe_by_signature = {}
  if not dpe.empty:
    for row in dpe.to_dict("records"):
      dpe_by_signature[str(row["signature"])] = row.get(_TRIGGER_METRIC)

  rows = []
  for task in sorted(tasks, key=lambda item: str(item["signature"])):
    result = _result_dict(task.get("result"))
    signature = str(task["signature"])
    metric = dpe_by_signature.get(signature)
    rows.append({
        "task_id": int(task["id"]),
        "signature": signature,
        "status": int(task["status"]),
        "outcome": task.get("outcome") or "",
        "terminal": int(task["status"]) in _TERMINAL_STATUSES,
        "completed": int(task["status"]) == 3,
        "simulator_cache_hit": result.get("simulator_cache_hit"),
        "inference_log_count": len(result.get("inference_log_locations") or []),
        "dpe_output_count": len(result.get("dpe_output_locations") or []),
        "output_bag_count": len(result.get("output_bag_locations") or []),
        "failed_evaluation_count": len(result.get("failed_evaluations") or []),
        "dpe_assist_channel_triggered": metric,
        "triggered": metric is not None and float(metric) >= 1.0,
    })

  complete = all(row["terminal"] for row in rows)
  valid = complete and all(
      row["completed"] and row["simulator_cache_hit"] is False and
      row["inference_log_count"] > 0 and row["dpe_output_count"] > 0 and
      row["output_bag_count"] > 0 and row["failed_evaluation_count"] == 0 and
      row["dpe_assist_channel_triggered"] is not None
      for row in rows)
  return {
      "job_id": job_id,
      "terminal": complete,
      "valid_ab": valid,
      "tasks": rows,
  }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--job-id", type=int)
  parser.add_argument(
      "--registry",
      type=Path,
      default=Path("reports/ra_independent_replay_cr6657869_ab_job.json"),
  )
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  job_id = args.job_id
  if job_id is None:
    payload = json.loads(args.registry.read_text(encoding="utf-8"))
    job_id = int(payload["job_id"])
  print(json.dumps(analyze(job_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
