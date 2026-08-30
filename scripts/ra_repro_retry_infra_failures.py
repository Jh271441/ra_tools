#!/usr/bin/env python3
"""Safely retry allowlisted failures after a job stops.

Dry-run is the default.  The retry ledger is authoritative: every entry must
still be FAILED, belong to the recorded job/scenario, and match the allowlisted
failure signature.  Orion does not allow the standard retry API while a job is
running, so such entries remain pending without mutation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Sequence


_ALLOWLISTED_OUTCOME_PARTS = (
    "Disk quota exceeded",
    "DPE exceeded memory quota",
    "Executor script returned 135",
    "Failed to extract zstd file",
    "Error writing to file",
    "hdmap_files/map_",
)

_VALIDATION_OUTCOME_PARTS = {
    "simulator_shutdown_sigsegv": ("CppException: SIGSEGV",),
    "planner_timestamp_invariant": (
        "seed.confirm_timestamp() < current_timestamp",
    ),
}


def _is_allowlisted(entry: dict[str, Any], outcome: str) -> bool:
  if any(part in outcome for part in _ALLOWLISTED_OUTCOME_PARTS):
    return True
  failure_class = str(entry.get("failure_class") or "")
  return any(
      part in outcome
      for part in _VALIDATION_OUTCOME_PARTS.get(failure_class, ()))


def _load_api():
  try:
    from orion.db_accessor.job_accessor import JobAccessor
    from orion.db_accessor.task_accessor import TaskAccessor
    from orion_client.api.retry_job_impl import retry_job_impl
    from orion_client.utils.config_utils import get_auth_token
    from orion_protos.orion_job_pb2 import OrionJob
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions, TrailRegionMgr
  except ImportError as exc:
    raise RuntimeError("Add Voyager Orion build/lib paths to PYTHONPATH") from exc
  return (JobAccessor, TaskAccessor, retry_job_impl, get_auth_token, OrionJob,
          OrionTask, Regions, TrailRegionMgr)


def retry(ledger_path: Path, execute: bool,
          token: str | None = None) -> dict[str, Any]:
  (JobAccessor, TaskAccessor, retry_job_impl, get_auth_token, OrionJob,
   OrionTask, Regions, TrailRegionMgr) = _load_api()
  ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
  results = []
  retry_groups: dict[int, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
  token = token or get_auth_token(None, Regions.CN)

  with TrailRegionMgr(Regions.CN, is_pre=False):
    for key, entry in ledger.items():
      job_id = int(entry["job_id"])
      task_id = int(entry["task_id"])
      job = JobAccessor.get(job_id)
      tasks = list(TaskAccessor.query({
          "id": task_id,
          "job_id": job_id,
          "extra_fields": "result",
      }))
      if len(tasks) != 1:
        raise RuntimeError(f"Expected task {task_id}, got {len(tasks)} rows")
      task = tasks[0]
      if int(task["signature"]) != int(entry["scenario_id"]):
        raise RuntimeError(f"Scenario mismatch for task {task_id}")
      job_state = OrionJob.State.Name(int(job["state"]))
      task_status = OrionTask.Status.Name(int(task["status"]))
      outcome = str(task.get("outcome") or "")
      row = {
          "ledger_key": key,
          "job_id": job_id,
          "task_id": task_id,
          "scenario_id": int(entry["scenario_id"]),
          "job_state": job_state,
          "task_status": task_status,
          "execute": execute,
      }
      if task_status == "COMPLETED":
        row["action"] = "already_recovered"
        results.append(row)
        continue
      if task_status != "FAILED":
        row["action"] = "wait_for_failed_or_recovered_state"
        results.append(row)
        continue
      if not _is_allowlisted(entry, outcome):
        raise RuntimeError(
            f"Task {task_id} failure is not allowlisted: {outcome}")
      if job_state == "RUNNING":
        row["action"] = "wait_for_source_job_terminal"
        results.append(row)
        continue
      if not execute:
        row["action"] = "would_retry"
        results.append(row)
        continue
      row["action"] = "pending_batch_retry"
      results.append(row)
      retry_groups.setdefault(job_id, []).append((key, entry, row))

    for job_id, candidates in retry_groups.items():
      task_ids = [int(entry["task_id"]) for _, entry, _ in candidates]
      response = retry_job_impl(
          job_id=job_id,
          task_ids=task_ids,
          override_token=token,
          reason="RA full reproduction: one controlled retry of allowlisted failure",
      )
      if not response.is_success:
        raise RuntimeError(
            f"Retry failed for job {job_id} tasks {task_ids}: {response}")
      submitted_at = datetime.now(timezone.utc).isoformat()
      for _, entry, row in candidates:
        entry["status"] = "retry_submitted"
        entry["retry_submitted_at"] = submitted_at
        row["action"] = "retried"
        row["response_message"] = response.message
      # Persist after every accepted job-level batch.  This keeps the ledger
      # consistent even if a later, unrelated job submission fails.
      ledger_path.write_text(
          json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
          encoding="utf-8")

  if execute:
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
  return {"ledger": str(ledger_path), "results": results}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument(
      "--ledger", type=Path,
      default=Path("reports/ra_repro_full_20260829_retries.json"))
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--orion-token", default=None)
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  result = retry(args.ledger, args.execute, args.orion_token)
  print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
