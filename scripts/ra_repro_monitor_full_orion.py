#!/usr/bin/env python3
"""Read-only status monitor for full-release RA reproduction Orion jobs."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Sequence


def _load_orion_api():
  try:
    from orion.db_accessor.job_accessor import JobAccessor
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion_protos.orion_job_pb2 import OrionJob
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError(
        "Orion Python libraries are unavailable; add Voyager Orion build/lib "
        "directories to PYTHONPATH") from exc
  return (JobAccessor, TaskAccessor, OrionJob, OrionTask, Regions,
          TrailRegionMgr)


def monitor(registry_path: Path) -> dict[str, Any]:
  registry = json.loads(registry_path.read_text(encoding="utf-8"))
  invalid_entries = {
      key: entry for key, entry in registry.items()
      if entry.get("valid_for_metrics") is False
  }
  registry = {
      key: entry for key, entry in registry.items()
      if entry.get("valid_for_metrics") is not False
  }
  (JobAccessor, TaskAccessor, OrionJob, OrionTask, Regions,
   TrailRegionMgr) = _load_orion_api()

  jobs = []
  with TrailRegionMgr(Regions.CN, is_pre=False):
    job_ids = [int(entry["job_id"]) for entry in registry.values()]
    status_counts = TaskAccessor.get_status_counts(job_ids)
    for release, registered in registry.items():
      job_id = int(registered["job_id"])
      metadata = JobAccessor.get(job_id)
      counts = Counter({
          OrionTask.Status.Name(int(status)): int(count)
          for status, count in status_counts.get(job_id, {}).items()
      })
      declared = int(metadata["num_total_tasks"])
      expected = int(registered["scenario_count"])
      queried = sum(counts.values())
      max_concurrency = int(metadata["max_concurrency"])
      jobs.append({
          "release": release,
          "job_id": job_id,
          "job_state": OrionJob.State.Name(int(metadata["state"])),
          "expected_tasks": expected,
          "declared_tasks": declared,
          "queried_tasks": queried,
          "max_concurrency": max_concurrency,
          "task_status": dict(sorted(counts.items())),
          "count_gate_passed": expected == declared == queried,
          "configured_concurrency_gate_passed": (
              max_concurrency == int(registered["max_concurrency"])),
          "observed_concurrency_gate_passed": (
              counts["RUNNING"] <= max_concurrency),
      })

  totals = Counter()
  for job in jobs:
    totals.update(job["task_status"])
  anomaly_statuses = {
      key: value for key, value in totals.items()
      if key in ("FAILED", "CANCELLED") and value
  }
  active = totals["UNASSIGNED"] + totals["RUNNING"]
  return {
      "observed_at": datetime.now(timezone.utc).isoformat(),
      "registry": str(registry_path),
      "skipped_invalid_jobs": [{
          "registry_key": key,
          "job_id": int(entry["job_id"]),
          "invalid_reason": entry.get("invalid_reason"),
      } for key, entry in invalid_entries.items()],
      "job_count": len(jobs),
      "expected_tasks": sum(job["expected_tasks"] for job in jobs),
      "declared_tasks": sum(job["declared_tasks"] for job in jobs),
      "queried_tasks": sum(job["queried_tasks"] for job in jobs),
      "task_status": dict(sorted(totals.items())),
      "observed_running": totals["RUNNING"],
      "remaining_active": active,
      "all_count_gates_passed": all(
          job["count_gate_passed"] for job in jobs),
      "all_configured_concurrency_gates_passed": all(
          job["configured_concurrency_gate_passed"] for job in jobs),
      "all_observed_concurrency_gates_passed": all(
          job["observed_concurrency_gate_passed"] for job in jobs),
      "anomaly_statuses": anomaly_statuses,
      "all_terminal": active == 0,
      "jobs": jobs,
  }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument(
      "--registry",
      type=Path,
      default=Path("reports/ra_repro_full_20260829_jobs.json"),
  )
  parser.add_argument("--output", type=Path, default=None)
  parser.add_argument(
      "--summary-only", action="store_true",
      help="Print only aggregate fields while retaining full --output JSON",
  )
  parser.add_argument(
      "--anomaly-confirm-seconds", type=float, default=5.0,
      help="Re-query after this delay before treating FAILED/CANCELLED as current",
  )
  parser.add_argument(
      "--history",
      type=Path,
      default=Path("reports/ra_repro_full_20260829_status_history.jsonl"),
      help="Append compact timestamp/status snapshots; pass an empty path to disable",
  )
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  result = monitor(args.registry)
  if result["anomaly_statuses"] and args.anomaly_confirm_seconds > 0:
    first_observation = {
        "observed_at": result["observed_at"],
        "anomaly_statuses": result["anomaly_statuses"],
    }
    time.sleep(args.anomaly_confirm_seconds)
    result = monitor(args.registry)
    result["anomaly_confirmation"] = {
        "first_observation": first_observation,
        "confirm_after_seconds": args.anomaly_confirm_seconds,
        "confirmed_anomaly_statuses": result["anomaly_statuses"],
        "transient": not bool(result["anomaly_statuses"]),
    }
  result["completion_fraction"] = (
      result["task_status"].get("COMPLETED", 0) / result["expected_tasks"])
  if args.history:
    prior_peak = 0
    history_rows = []
    if args.history.exists():
      for line in args.history.read_text(encoding="utf-8").splitlines():
        if line.strip():
          snapshot = json.loads(line)
          history_rows.append(snapshot)
          prior_peak = max(
              prior_peak, int(snapshot.get("observed_running", 0)))
    result["observed_running_peak"] = max(
        prior_peak, int(result["observed_running"]))
    result["recent_completion_rate_per_hour"] = None
    result["estimated_remaining_hours"] = None
    if history_rows:
      current_time = datetime.fromisoformat(result["observed_at"])
      eligible = []
      for snapshot in history_rows:
        elapsed = (
            current_time - datetime.fromisoformat(snapshot["observed_at"])
        ).total_seconds()
        if 300 <= elapsed <= 3600:
          eligible.append((elapsed, snapshot))
      if eligible:
        elapsed, baseline = max(eligible)
        completed_delta = (
            result["task_status"].get("COMPLETED", 0) -
            baseline["task_status"].get("COMPLETED", 0))
        if completed_delta > 0:
          rate = completed_delta / elapsed * 3600
          result["recent_completion_rate_per_hour"] = rate
          result["estimated_remaining_hours"] = (
              result["remaining_active"] / rate)
  text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
  if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
  if args.history:
    args.history.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        key: result[key]
        for key in (
            "observed_at", "task_status", "observed_running",
            "observed_running_peak", "remaining_active", "all_terminal",
            "anomaly_statuses", "completion_fraction",
            "recent_completion_rate_per_hour", "estimated_remaining_hours")
    }
    if "anomaly_confirmation" in result:
      compact["anomaly_confirmation"] = result["anomaly_confirmation"]
    with args.history.open("a", encoding="utf-8") as stream:
      stream.write(json.dumps(compact, ensure_ascii=False) + "\n")
  if args.summary_only:
    summary = {key: value for key, value in result.items() if key != "jobs"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
  else:
    print(text, end="")


if __name__ == "__main__":
  main()
