#!/usr/bin/env python3
"""Safely resume unfinished tasks from an Orion job at higher concurrency.

Dry-run is the default.  Execute mode snapshots UNASSIGNED/RUNNING tasks into
an in-memory clone before cancelling the source job, then launches that clone.
This ordering ensures that a transient DB failure after cancellation cannot
lose the remaining scenario definitions.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from typing import Any, Sequence

import requests


_DB_BASE_URL = os.environ.get("ORION_DB_BASE_URL",
                              "http://orion-dbserver.intra.xiaojukeji.com")
_JOB_QUERY_URL = f"{_DB_BASE_URL}/orion/job/query/"
_TASK_QUERY_URL = f"{_DB_BASE_URL}/orion/task/query/"


def _query(url: str, data: dict[str, str], token: str) -> list[dict[str, Any]]:
  response = requests.post(
      url,
      headers={"Authorization": f"Bearer {token}"},
      data=data,
      timeout=60,
  )
  response.raise_for_status()
  payload = response.json()
  if payload.get("code") != 0:
    raise RuntimeError(f"Orion query failed: {payload}")
  return payload.get("data", {}).get("res", [])


def _load_orion_api():
  try:
    from orion_client.api.clone_job_impl import clone_job
    from orion_client.api.launch_job_impl import launch_job
    from orion_client.api.proxy_client import cancel_orion_job_through_proxy
    from orion_protos.orion_job_pb2 import OrionJob
    from orion_protos.orion_task_pb2 import OrionTask
    from voy_data_utils.regions import Regions
  except ImportError as exc:
    raise RuntimeError(
        "Orion Python libraries are unavailable. Run with Voyager's Orion "
        "build/lib directories on PYTHONPATH.") from exc
  return (clone_job, launch_job, cancel_orion_job_through_proxy, OrionJob,
          OrionTask, Regions)


def _job_metadata(job_id: int, token: str) -> dict[str, Any]:
  rows = _query(_JOB_QUERY_URL, {"id": str(job_id)}, token)
  if len(rows) != 1:
    raise RuntimeError(f"Expected one Orion job {job_id}, got {len(rows)}")
  return rows[0]


def _task_counts(job_id: int, token: str) -> Counter:
  rows = _query(_TASK_QUERY_URL, {"job_id": str(job_id)}, token)
  return Counter(int(row["status"]) for row in rows)


def _task_rows(job_id: int, token: str) -> list[dict[str, Any]]:
  return _query(_TASK_QUERY_URL, {"job_id": str(job_id)}, token)


def resume(job_id: int, token: str, max_concurrency: int,
           execute: bool, probe_count: int = 0,
           without_cancel: bool = False,
           exclude_job_ids: Sequence[int] = ()) -> dict[str, Any]:
  (clone_job, launch_job, cancel_job, OrionJob, OrionTask,
   Regions) = _load_orion_api()
  metadata = _job_metadata(job_id, token)
  task_rows = _task_rows(job_id, token)
  counts = Counter(int(row["status"]) for row in task_rows)
  if metadata.get("state") != OrionJob.RUNNING:
    raise RuntimeError(
        f"Source job must be RUNNING; state={metadata.get('state')}")
  if counts.get(OrionTask.FAILED, 0) or counts.get(OrionTask.CANCELLED, 0):
    raise RuntimeError(
        "Source job already has failed/cancelled tasks; review before resuming")

  pending_count = (counts.get(OrionTask.UNASSIGNED, 0) +
                   counts.get(OrionTask.RUNNING, 0))
  if pending_count == 0:
    raise RuntimeError("Source job has no unfinished mapper tasks")

  if probe_count and without_cancel:
    raise ValueError("--probe-count and --without-cancel are mutually exclusive")
  if exclude_job_ids and not without_cancel:
    raise ValueError("--exclude-job-id requires --without-cancel")

  if probe_count:
    unassigned_ids = sorted(
        int(row["id"]) for row in task_rows
        if int(row["status"]) == OrionTask.UNASSIGNED)
    selected_ids = unassigned_ids[-probe_count:]
    if len(selected_ids) != probe_count:
      raise RuntimeError(
          f"Requested {probe_count} probe tasks, found {len(selected_ids)}")
    clone = clone_job(
        job_id=job_id,
        task_id_list=selected_ids,
        region=Regions.CN,
    )
    expected_clone_count = probe_count
  elif without_cancel:
    excluded_signatures = set()
    for exclude_job_id in exclude_job_ids:
      excluded_signatures.update(
          str(row["signature"]) for row in _task_rows(exclude_job_id, token))
    selected_ids = sorted(
        int(row["id"]) for row in task_rows
        if int(row["status"]) == OrionTask.UNASSIGNED and
        str(row["signature"]) not in excluded_signatures)
    if not selected_ids:
      raise RuntimeError("No queued tasks remain after exclusions")
    clone = clone_job(
        job_id=job_id,
        task_id_list=selected_ids,
        region=Regions.CN,
    )
    expected_clone_count = len(selected_ids)
  else:
    # Snapshot all unfinished definitions before any state mutation. A RUNNING
    # task can finish during the handoff, so downstream validation must dedupe
    # by scenario id and explicitly report conflicting repeated outcomes.
    clone = clone_job(
        job_id=job_id,
        task_status_list=[OrionTask.UNASSIGNED, OrionTask.RUNNING],
        region=Regions.CN,
    )
    expected_clone_count = pending_count
  if len(clone.mapper_tasks) != expected_clone_count:
    raise RuntimeError(
        f"Clone count {len(clone.mapper_tasks)} != expected "
        f"count {expected_clone_count}")

  mode = ("probe" if probe_count else
          "parallel_queued" if without_cancel else "resume")
  marker = f"{mode}_of_{job_id}_concurrency_{max_concurrency}"
  clone.description = f"{clone.description}\n{marker}".strip()
  if marker not in clone.labels:
    clone.labels.append(marker)

  result = {
      "source_job_id": job_id,
      "source_state": metadata.get("state"),
      "source_task_status_counts": dict(sorted(counts.items())),
      "snapshotted_unfinished_tasks": len(clone.mapper_tasks),
      "cluster": metadata.get("cluster"),
      "runtime_reference": metadata.get("runtime_reference"),
      "priority": metadata.get("priority"),
      "requested_max_concurrency": max_concurrency,
      "excluded_job_ids": list(exclude_job_ids),
      "mode": mode,
      "execute": execute,
  }
  if not execute:
    return result

  if not probe_count and not without_cancel:
    response = cancel_job(
        Regions.CN,
        [job_id],
        is_async=False,
        override_token=token,
    )
    if not response.is_success:
      raise RuntimeError(f"Failed to cancel source job: {response}")

  new_job_id = launch_job(
      clone,
      cluster_name=metadata["cluster"],
      max_concurrency=max_concurrency,
      priority=metadata["priority"],
      override_runtime=metadata["runtime_reference"],
      override_token=token,
  )
  result["resumed_job_id"] = new_job_id
  return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--job-id", type=int, required=True)
  parser.add_argument("--max-concurrency", type=int, default=20)
  parser.add_argument("--execute", action="store_true")
  parser.add_argument(
      "--probe-count", type=int, default=0,
      help="Clone only this many queued tasks without cancelling source Job")
  parser.add_argument(
      "--without-cancel", action="store_true",
      help="Clone remaining queued tasks but leave the source Job running")
  parser.add_argument(
      "--exclude-job-id", type=int, action="append", default=[],
      help="Exclude scenario signatures already present in this Job")
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
  if not 1 <= args.max_concurrency <= 100:
    raise SystemExit("--max-concurrency must be between 1 and 100")
  if not 0 <= args.probe_count <= 20:
    raise SystemExit("--probe-count must be between 0 and 20")
  result = resume(args.job_id, args.orion_token, args.max_concurrency,
                  args.execute, args.probe_count, args.without_cancel,
                  args.exclude_job_id)
  print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
