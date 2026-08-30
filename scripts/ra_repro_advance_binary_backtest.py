#!/usr/bin/env python3
"""Advance the rolling RA binary backtest by at most one state transition.

The command is intentionally single-step and idempotent.  It either reports
an active job, launches one missing window part, finalizes one complete target,
or reports a quality-gate failure.  It never launches while another valid
backtest job is active.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ra_repro_finalize_binary_backtest import (
    finalize,
    inspect_job_configuration,
)
from scripts.ra_repro_launch_binary_backtest import (
    TEMPLATE_JOBS,
    build_and_maybe_launch,
    select_manifest,
)
from scripts.ra_repro_validate_orion import validate


def _load_orion_status_api():
  from orion.db_accessor.task_accessor import TaskAccessor
  from orion_client.utils.config_utils import get_auth_token
  from orion_protos.orion_task_pb2 import OrionTask
  from voy_data_utils.regions import Regions, TrailRegionMgr
  return TaskAccessor, get_auth_token, OrionTask, Regions, TrailRegionMgr


def _valid_entries(registry: dict[str, Any]) -> list[dict[str, Any]]:
  return [
      dict(entry) for entry in registry.values()
      if entry.get("valid_for_metrics") is not False and
      entry.get("job_id") is not None
  ]


def _status_by_job(job_ids: Sequence[int]) -> dict[int, dict[str, int]]:
  TaskAccessor, _, OrionTask, Regions, TrailRegionMgr = _load_orion_status_api()
  if not job_ids:
    return {}
  with TrailRegionMgr(Regions.CN, is_pre=False):
    raw = TaskAccessor.get_status_counts(list(job_ids))
  return {
      int(job_id): {
          OrionTask.Status.Name(int(status)): int(count)
          for status, count in counts.items()
      }
      for job_id, counts in raw.items()
  }


def _parse_orion_time(value: Any) -> datetime | None:
  if not value:
    return None
  text = str(value).strip()
  if text.endswith("Z"):
    text = f"{text[:-1]}+00:00"
  try:
    parsed = datetime.fromisoformat(text)
  except ValueError:
    return None
  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=timezone.utc)
  return parsed.astimezone(timezone.utc)


def _running_task_details(job_ids: Sequence[int]) -> list[dict[str, Any]]:
  """Return auditable timing details for currently running mapper tasks."""
  TaskAccessor, _, OrionTask, Regions, TrailRegionMgr = (
      _load_orion_status_api())
  now = datetime.now(timezone.utc)
  details = []
  with TrailRegionMgr(Regions.CN, is_pre=False):
    for job_id in job_ids:
      for task in TaskAccessor.query({"job_id": int(job_id)}):
        if int(task.get("status", -1)) != OrionTask.RUNNING:
          continue
        runs = task.get("task_runs") or []
        run = runs[-1] if runs else task
        assigned_at = _parse_orion_time(run.get("assign_time"))
        elapsed_seconds = (
            max((now - assigned_at).total_seconds(), 0.0)
            if assigned_at else None)
        timeout_seconds = int(run.get("timeout_sec") or 0) or None
        details.append({
            "job_id": int(job_id),
            "task_id": int(task["id"]),
            "scenario_id": int(task["signature"]),
            "assigned_at": (
                assigned_at.isoformat() if assigned_at else None),
            "elapsed_seconds": elapsed_seconds,
            "timeout_seconds": timeout_seconds,
            "elapsed_fraction_of_timeout": (
                elapsed_seconds / timeout_seconds
                if elapsed_seconds is not None and timeout_seconds else None),
            "worker_name": run.get("worker_name"),
            "worker_ip": run.get("worker_ip"),
            "run_version": int(run.get("version") or 0),
        })
  return sorted(details, key=lambda item: (item["job_id"], item["task_id"]))


def _window(target: str, size: int) -> list[str]:
  releases = list(TEMPLATE_JOBS)
  index = releases.index(target)
  if index + 1 < size:
    raise ValueError(f"Target {target} has no complete {size}-release window")
  return releases[index - size + 1:index + 1]


def _entry_is_complete(entry: dict[str, Any],
                       status: dict[str, int]) -> bool:
  return (
      status.get("COMPLETED", 0) == int(entry["scenario_count"]) and
      not any(status.get(name, 0) for name in (
          "UNASSIGNED", "RUNNING", "FAILED", "CANCELLED")))


def _find_anomalous_jobs(
    entries: Sequence[dict[str, Any]],
    statuses: dict[int, dict[str, int]],
) -> list[dict[str, Any]]:
  anomalous = []
  for entry in entries:
    job_id = int(entry["job_id"])
    status = statuses.get(job_id, {})
    if status.get("FAILED", 0) or status.get("CANCELLED", 0):
      anomalous.append({"job_id": job_id, "status": status})
  return anomalous


def _confirm_anomalous_jobs(
    entries: Sequence[dict[str, Any]],
    statuses: dict[int, dict[str, int]],
    confirm_seconds: float,
) -> tuple[dict[int, dict[str, int]], list[dict[str, Any]],
           dict[str, Any] | None]:
  """Confirm terminal anomalies while tolerating Orion's retry transition."""
  first_observation = _find_anomalous_jobs(entries, statuses)
  if not first_observation:
    return statuses, [], None
  if confirm_seconds > 0:
    time.sleep(confirm_seconds)
    statuses = _status_by_job(
        [int(entry["job_id"]) for entry in entries])
  anomalous = _find_anomalous_jobs(entries, statuses)
  confirmation = {
      "first_observation": first_observation,
      "confirm_after_seconds": confirm_seconds,
      "confirmed": bool(anomalous),
  }
  return statuses, anomalous, confirmation


def _active_jobs(
    entries: Sequence[dict[str, Any]],
    statuses: dict[int, dict[str, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
  active = []
  active_entries = []
  for entry in entries:
    job_id = int(entry["job_id"])
    status = statuses.get(job_id, {})
    if status.get("UNASSIGNED", 0) or status.get("RUNNING", 0):
      active.append({"job_id": job_id, "status": status})
      active_entries.append(entry)
  return active, active_entries


def _validate_entry(entry: dict[str, Any], token: str) -> dict[str, Any]:
  job_id = int(entry["job_id"])
  configuration = inspect_job_configuration([job_id], int(entry["binary_id"]))
  result = validate(
      [job_id], Path(entry["selected_manifest"]), None, token)
  passed = bool(
      configuration["gate_passed"] and result["is_terminal_and_complete"])
  quality = result.get("quality") or {}
  manifest_matches = (
      int(result.get("manifest_rows") or 0) == int(entry["scenario_count"]))
  incremental_gate_passed = bool(
      configuration["gate_passed"] and manifest_matches and
      not int(result.get("terminal_failed") or 0) and
      quality.get("gate_passed_so_far") is True)
  return {
      "job_id": job_id,
      "passed": passed,
      "incremental_gate_passed": incremental_gate_passed,
      "waiting_for_dpe": bool(
          configuration["gate_passed"] and
          result.get("completed_pending_dpe_grace", 0) and
          not result.get("completed_missing_dpe", 0)),
      "configuration": configuration,
      "quality": quality,
      "completed": result.get("completed"),
      "terminal_failed": result.get("terminal_failed"),
      "completed_missing_dpe": result.get("completed_missing_dpe"),
      "completed_pending_dpe_grace": result.get(
          "completed_pending_dpe_grace"),
      "manifest_rows": result.get("manifest_rows"),
      "expected_manifest_rows": int(entry["scenario_count"]),
  }


def advance(
    manifest_path: Path,
    registry_path: Path,
    metrics_path: Path,
    target_release: str | None,
    window_size: int,
    sample_per_cohort: int,
    seed: str,
    execute: bool,
    token: str | None,
    anomaly_confirm_seconds: float = 5.0,
) -> dict[str, Any]:
  registry = (
      json.loads(registry_path.read_text(encoding="utf-8"))
      if registry_path.exists() else {})
  unresolved_intents = [{
      "registry_key": key,
      "launch_state": entry.get("launch_state"),
      "launch_requested_at": entry.get("launch_requested_at"),
      "launch_error": entry.get("launch_error"),
  } for key, entry in registry.items()
                        if entry.get("valid_for_metrics") is not False and
                        entry.get("job_id") is None]
  if unresolved_intents:
    return {
        "action": "stop",
        "reason": "unresolved Orion launch intent; reconcile before retry",
        "unresolved_launch_intents": unresolved_intents,
    }
  entries = _valid_entries(registry)
  statuses = _status_by_job([int(entry["job_id"]) for entry in entries])

  statuses, anomalous, anomaly_confirmation = _confirm_anomalous_jobs(
      entries, statuses, anomaly_confirm_seconds)
  if anomalous:
    return {
        "action": "stop",
        "reason": "active or terminal job has failed/cancelled tasks",
        "anomalous_jobs": anomalous,
        "anomaly_confirmation": anomaly_confirmation,
    }

  active, active_entries = _active_jobs(entries, statuses)
  if active:
    incremental_validations = []
    completed_entries = [
        entry for entry in active_entries
        if statuses.get(int(entry["job_id"]), {}).get("COMPLETED", 0)
    ]
    if completed_entries:
      _, get_auth_token, _, Regions, _ = _load_orion_status_api()
      token = token or get_auth_token(None, Regions.CN)
      incremental_anomalies = []
      for entry in completed_entries:
        checked = _validate_entry(entry, token)
        incremental_validations.append(checked)
        if not checked["incremental_gate_passed"]:
          job_id = int(entry["job_id"])
          incremental_anomalies.append({
              "job_id": job_id,
              "status": statuses.get(job_id, {}),
              "validation": checked,
          })
      if incremental_anomalies:
        return {
            "action": "stop",
            "reason": "active job failed incremental quality gate",
            "anomalous_jobs": incremental_anomalies,
        }
      # Validation can take long enough for Orion to complete another task.
      # Refresh before emitting the audit record so status and validation
      # counts describe one coherent observation rather than adjacent states.
      statuses = _status_by_job(
          [int(entry["job_id"]) for entry in entries])
      statuses, anomalous, anomaly_confirmation = _confirm_anomalous_jobs(
          entries, statuses, anomaly_confirm_seconds)
      if anomalous:
        return {
            "action": "stop",
            "reason": "active or terminal job has failed/cancelled tasks",
            "anomalous_jobs": anomalous,
            "anomaly_confirmation": anomaly_confirmation,
        }
      active, active_entries = _active_jobs(entries, statuses)
    if active:
      result = {
          "action": "wait",
          "active_jobs": active,
          "running_tasks": _running_task_details(
              [int(entry["job_id"]) for entry in active_entries]),
      }
      if incremental_validations:
        result["incremental_validations"] = incremental_validations
      return result

  _, get_auth_token, _, Regions, _ = _load_orion_status_api()
  token = token or get_auth_token(None, Regions.CN)
  releases = list(TEMPLATE_JOBS)
  candidates = [target_release] if target_release else list(
      reversed(releases[window_size - 1:]))

  existing_targets = {}
  if metrics_path.exists():
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    existing_targets = payload.get("targets") or {}

  for target in candidates:
    desired = _window(target, window_size)
    if target in existing_targets and existing_targets[target].get(
        "quality_gate_passed"):
      continue
    target_entries = [
        entry for entry in entries
        if entry.get("target_release") == target and
        int(entry.get("sample_per_cohort", -1)) == sample_per_cohort and
        entry.get("seed") == seed
    ]

    validations = []
    covered = set()
    for entry in target_entries:
      status = statuses.get(int(entry["job_id"]), {})
      if not _entry_is_complete(entry, status):
        return {
            "action": "stop",
            "reason": "terminal job is not a clean complete set",
            "job_id": int(entry["job_id"]),
            "status": status,
        }
      checked = _validate_entry(entry, token)
      validations.append(checked)
      if not checked["passed"]:
        if checked["waiting_for_dpe"]:
          return {
              "action": "wait_dpe",
              "target_release": target,
              "validation": checked,
          }
        return {
            "action": "stop",
            "reason": "quality gate failed",
            "target_release": target,
            "validation": checked,
        }
      covered.update(entry.get("source_releases") or [])

    missing = [release for release in desired if release not in covered]
    if missing:
      date_token = target.removeprefix("gen4-release-")
      release_token = "_".join(
          release.removeprefix("gen4-release-") for release in missing)
      prefix = Path("reports") / (
          f"ra_binary_backtest_20260831_{date_token}_canary"
          f"{sample_per_cohort}_{release_token}")
      launch = build_and_maybe_launch(
          manifest_path=manifest_path,
          target_release=target,
          source_releases=missing,
          sample_per_cohort=sample_per_cohort,
          seed=seed,
          selected_manifest_path=Path(f"{prefix}_manifest.csv"),
          analysis_manifest_path=Path(f"{prefix}_analysis_manifest.csv"),
          registry_path=registry_path,
          max_concurrency=1,
          execute=execute,
          token=token,
      )
      return {
          "action": "launch" if execute else "plan_launch",
          "target_release": target,
          "desired_window": desired,
          "already_covered": sorted(covered),
          "missing_releases": missing,
          "prior_validations": validations,
          "launch": launch,
      }

    combined, _ = select_manifest(
        manifest_path, desired, sample_per_cohort, seed)
    combined["backtest_target_release"] = target
    combined_path = Path("reports") / (
        f"ra_binary_backtest_20260831_{target.removeprefix('gen4-release-')}"
        f"_canary{sample_per_cohort}_window{window_size}_analysis_manifest.csv")
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(combined_path, index=False)
    job_ids = [int(entry["job_id"]) for entry in target_entries]
    binary_ids = {int(entry["binary_id"]) for entry in target_entries}
    if len(binary_ids) != 1:
      return {
          "action": "stop",
          "reason": "target entries disagree on binary id",
          "binary_ids": sorted(binary_ids),
      }
    result = finalize(
        job_ids=job_ids,
        analysis_manifest_path=combined_path,
        target_release=target,
        binary_id=binary_ids.pop(),
        output_path=metrics_path,
        token=token,
        allow_partial=False,
    )
    return {
        "action": "finalize",
        "target_release": target,
        "desired_window": desired,
        "job_ids": job_ids,
        "validations": validations,
        "result": result,
    }

  return {"action": "complete", "targets": candidates}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument(
      "--manifest", type=Path,
      default=Path("reports/ra_repro_full_20260829_manifest.csv"))
  parser.add_argument(
      "--registry", type=Path,
      default=Path("reports/ra_binary_backtest_20260831_jobs.json"))
  parser.add_argument(
      "--metrics", type=Path,
      default=Path("reports/ra_binary_backtest_20260831_metrics.json"))
  parser.add_argument("--target-release", choices=sorted(TEMPLATE_JOBS))
  parser.add_argument("--window-size", type=int, default=4)
  parser.add_argument("--sample-per-cohort", type=int, default=10)
  parser.add_argument("--seed", default="ra_binary_backtest_20260831_v1")
  parser.add_argument("--execute", action="store_true")
  parser.add_argument("--anomaly-confirm-seconds", type=float, default=5.0)
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if args.window_size < 2:
    raise SystemExit("--window-size must be at least 2")
  if args.sample_per_cohort <= 0:
    raise SystemExit("--sample-per-cohort must be positive for canary advance")
  if args.anomaly_confirm_seconds < 0:
    raise SystemExit("--anomaly-confirm-seconds must be non-negative")
  result = advance(
      manifest_path=args.manifest,
      registry_path=args.registry,
      metrics_path=args.metrics,
      target_release=args.target_release,
      window_size=args.window_size,
      sample_per_cohort=args.sample_per_cohort,
      seed=args.seed,
      execute=args.execute,
      token=args.orion_token,
      anomaly_confirm_seconds=args.anomaly_confirm_seconds,
  )
  result["observed_at"] = datetime.now(timezone.utc).isoformat()
  print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
