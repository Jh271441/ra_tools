#!/usr/bin/env python3
"""Continuously run the single-job rolling RA backtest state machine."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import traceback
from typing import Sequence

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ra_repro_advance_binary_backtest import advance


_PROFILE_ANNOTATION_PATTERN = re.compile(
    r'\{"text":\s*"(?P<text>(?:[^"\\]|\\.)*)",\s*'
    r'"x":\s*"(?P<timestamp>[^"]+)"[^}]*"yref":\s*"paper"\}')


def _parse_task_profile_annotations(html: str) -> list[dict[str, str]]:
  """Extract stage transitions from Orion's live Plotly task profile."""
  annotations = []
  seen = set()
  for match in _PROFILE_ANNOTATION_PATTERN.finditer(html):
    text = json.loads(f'"{match.group("text")}"')
    if not any(stage in text for stage in (
        "Downloading data", "Running simulation", "Result evaluation",
        "PERSISTING", "Uploading data", "__end__")):
      continue
    key = (match.group("timestamp"), text)
    if key in seen:
      continue
    seen.add(key)
    annotations.append({
        "timestamp": match.group("timestamp"),
        "stage": text.replace("<br>", " / "),
    })
  return annotations


def _fetch_task_profile_summary(task_id: int) -> dict:
  """Read a running worker's profile through Orion's production proxy."""
  from orion.utils.node_type import NodeType
  from orion_internal.cluster.config import get_mgmt_nodes
  from orion_internal.cluster.constants import ClusterNames
  from orion_internal.cluster.rpc_service import get_node_rpc_url
  from voy_data_utils.regions import Regions

  proxy_ip = get_mgmt_nodes()[NodeType.PROXY][ClusterNames.PROD][Regions.CN].ip
  url = get_node_rpc_url(proxy_ip, NodeType.PROXY, "get_task_info_page")
  response = requests.get(url, params={"task_id": task_id}, timeout=60)
  response.raise_for_status()
  annotations = _parse_task_profile_annotations(response.text)
  return {
      "response_bytes": len(response.content),
      "latest_stage": annotations[-1] if annotations else None,
      "stage_transitions": annotations,
  }


def _enrich_long_running_tasks(result: dict,
                               profile_after_seconds: float) -> None:
  """Attach best-effort live stage data without affecting quality gates."""
  for task in result.get("running_tasks", []):
    elapsed = task.get("elapsed_seconds")
    if elapsed is None or float(elapsed) < profile_after_seconds:
      continue
    try:
      task["live_profile"] = _fetch_task_profile_summary(int(task["task_id"]))
    except Exception as exc:  # pylint: disable=broad-exception-caught
      task["live_profile_error"] = repr(exc)


def _cancel_anomalous_jobs(result: dict) -> dict | None:
  """Cancel unfinished work for jobs that already contain bad task states."""
  job_ids = sorted({
      int(item["job_id"])
      for item in result.get("anomalous_jobs", [])
      if int(item.get("status", {}).get("UNASSIGNED", 0)) > 0 or
      int(item.get("status", {}).get("RUNNING", 0)) > 0
  })
  if not job_ids:
    return None

  try:
    from orion_client.api.proxy_client import cancel_orion_job_through_proxy
    from orion_client.utils.config_utils import get_auth_token
    from voy_data_utils.regions import Regions
  except ImportError as exc:
    raise RuntimeError(
        "Orion Python libraries are unavailable; cannot cancel anomalous "
        "jobs") from exc

  token = get_auth_token(None, Regions.CN)
  response = cancel_orion_job_through_proxy(
      Regions.CN,
      job_ids,
      is_async=False,
      override_token=token,
  )
  if not response.is_success:
    raise RuntimeError(f"Failed to cancel anomalous Orion jobs: {response}")
  return {
      "action": "cancel_anomalous_jobs",
      "job_ids": job_ids,
      "cancelled_at": datetime.now(timezone.utc).isoformat(),
  }


def _emit(payload: dict, audit_log: Path) -> None:
  text = json.dumps(payload, ensure_ascii=False)
  print(text, flush=True)
  audit_log.parent.mkdir(parents=True, exist_ok=True)
  with audit_log.open("a", encoding="utf-8") as fh:
    fh.write(text + "\n")


def _write_status_snapshot(payload: dict, status_path: Path) -> None:
  """Atomically publish the latest pipeline state for read-only consumers."""
  status_path.parent.mkdir(parents=True, exist_ok=True)
  temporary = status_path.with_suffix(status_path.suffix + ".tmp")
  temporary.write_text(
      json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )
  temporary.replace(status_path)


def _write_error_status_snapshot(error: dict, status_path: Path) -> None:
  """Mark the last good snapshot stale while retaining its job state."""
  current = {}
  if status_path.exists():
    current = json.loads(status_path.read_text(encoding="utf-8"))
  current["last_successful_observed_at"] = current.get("observed_at")
  current["observed_at"] = error["observed_at"]
  current["snapshot_status"] = "stale_due_to_monitor_error"
  current["monitor_error"] = {
      "consecutive_errors": error["consecutive_errors"],
      "error": error["error"],
  }
  _write_status_snapshot(current, status_path)


def _refresh_dashboard_if_needed(
    metrics_path: Path,
    stamp_path: Path,
    api_base_url: str,
    online_metrics_path: Path | None = None,
) -> dict | None:
  artifact_paths = {"binary_backtest": metrics_path}
  if online_metrics_path is not None:
    artifact_paths["online_metrics"] = online_metrics_path
  artifact_generations = {}
  for name, path in artifact_paths.items():
    if not path.exists():
      continue
    payload = json.loads(path.read_text(encoding="utf-8"))
    generated_at = str(payload.get("generated_at") or "")
    if generated_at:
      artifact_generations[name] = generated_at
  if not artifact_generations:
    return None
  if stamp_path.exists():
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    if stamp.get("artifact_generations") == artifact_generations:
      return None
    # Preserve compatibility with stamps written before online metrics were
    # tracked as a separate dashboard input.
    if (
        set(artifact_generations) == {"binary_backtest"}
        and stamp.get("generated_at") == artifact_generations["binary_backtest"]
    ):
      return None

  response = requests.post(
      f"{api_base_url.rstrip('/')}/dashboard/refresh",
      json={"force": True},
      timeout=30,
  )
  response.raise_for_status()
  job = response.json()
  job_id = str(job["job_id"])
  deadline = time.monotonic() + 1800
  while time.monotonic() < deadline:
    status_response = requests.get(
        f"{api_base_url.rstrip('/')}/dashboard/refresh/{job_id}",
        timeout=30,
    )
    status_response.raise_for_status()
    status = status_response.json()
    if status.get("status") == "completed":
      stamp = {
          "generated_at": max(artifact_generations.values()),
          "artifact_generations": artifact_generations,
          "refresh_job_id": job_id,
          "completed_at": datetime.now(timezone.utc).isoformat(),
      }
      stamp_path.parent.mkdir(parents=True, exist_ok=True)
      stamp_path.write_text(
          json.dumps(stamp, ensure_ascii=False, indent=2) + "\n",
          encoding="utf-8")
      return stamp
    if status.get("status") == "failed":
      raise RuntimeError(f"Dashboard refresh failed: {status}")
    time.sleep(5)
  raise TimeoutError(f"Dashboard refresh {job_id} did not finish in 1800s")


def _attempt_dashboard_refresh(
    metrics_path: Path,
    stamp_path: Path,
    api_base_url: str,
    online_metrics_path: Path | None = None,
) -> tuple[dict | None, dict | None]:
  """Retry dashboard publication without blocking Orion experiment progress."""
  try:
    return _refresh_dashboard_if_needed(
        metrics_path, stamp_path, api_base_url, online_metrics_path), None
  except Exception as exc:  # pylint: disable=broad-exception-caught
    return None, {
        "action": "dashboard_refresh_error",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "error": repr(exc),
        "traceback": traceback.format_exc(),
    }


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
  parser.add_argument(
      "--online-metrics", type=Path,
      default=Path("reports/ra_online_metrics_20260831.json"))
  parser.add_argument("--window-size", type=int, default=4)
  parser.add_argument("--sample-per-cohort", type=int, default=10)
  parser.add_argument("--seed", default="ra_binary_backtest_20260831_v1")
  parser.add_argument("--poll-seconds", type=float, default=300)
  parser.add_argument(
      "--max-consecutive-errors", type=int, default=30,
      help=("Exit only after this many consecutive control-plane failures; "
            "individual API calls already retry internally."),
  )
  parser.add_argument("--anomaly-confirm-seconds", type=float, default=5.0)
  parser.add_argument(
      "--profile-after-seconds", type=float, default=1800.0,
      help=("Attach best-effort live worker stage transitions to audit rows "
            "after a task has run this long."),
  )
  parser.add_argument(
      "--dashboard-api-base-url",
      default="http://127.0.0.1/sim/api",
  )
  parser.add_argument(
      "--dashboard-refresh-stamp", type=Path,
      default=Path("reports/ra_binary_backtest_20260831_dashboard_refresh.json"),
  )
  parser.add_argument("--execute", action="store_true")
  parser.add_argument(
      "--cancel-on-anomaly",
      action="store_true",
      help=("Cancel remaining tasks when a tracked job contains FAILED or "
            "CANCELLED tasks. The anomaly is written to the audit log first."),
  )
  parser.add_argument(
      "--audit-log", type=Path,
      default=Path("reports/ra_binary_backtest_20260831_pipeline.jsonl"),
  )
  parser.add_argument(
      "--status-snapshot", type=Path,
      default=Path("reports/ra_binary_backtest_20260831_status.json"),
      help="Atomically updated latest pipeline state.",
  )
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if not args.execute:
    raise SystemExit("Pipeline runner requires --execute")
  if args.poll_seconds < 30:
    raise SystemExit("--poll-seconds must be at least 30")
  if args.anomaly_confirm_seconds < 0:
    raise SystemExit("--anomaly-confirm-seconds must be non-negative")
  if args.profile_after_seconds < 0:
    raise SystemExit("--profile-after-seconds must be non-negative")

  consecutive_errors = 0
  while True:
    try:
      refreshed, refresh_error = _attempt_dashboard_refresh(
          args.metrics,
          args.dashboard_refresh_stamp,
          args.dashboard_api_base_url,
          args.online_metrics,
      )
      if refresh_error:
        _emit(refresh_error, args.audit_log)
      if refreshed:
        _emit({
            "action": "dashboard_refresh",
            **refreshed,
        }, args.audit_log)
      result = advance(
          manifest_path=args.manifest,
          registry_path=args.registry,
          metrics_path=args.metrics,
          target_release=None,
          window_size=args.window_size,
          sample_per_cohort=args.sample_per_cohort,
          seed=args.seed,
          execute=True,
          token=None,
          anomaly_confirm_seconds=args.anomaly_confirm_seconds,
      )
      _enrich_long_running_tasks(result, args.profile_after_seconds)
      result["observed_at"] = datetime.now(timezone.utc).isoformat()
      _emit(result, args.audit_log)
      _write_status_snapshot({
          **result,
          "snapshot_status": "current",
      }, args.status_snapshot)
      consecutive_errors = 0
    except Exception as exc:  # pylint: disable=broad-exception-caught
      consecutive_errors += 1
      error = {
          "action": "error",
          "observed_at": datetime.now(timezone.utc).isoformat(),
          "consecutive_errors": consecutive_errors,
          "error": repr(exc),
          "traceback": traceback.format_exc(),
      }
      _emit(error, args.audit_log)
      _write_error_status_snapshot(error, args.status_snapshot)
      if consecutive_errors >= args.max_consecutive_errors:
        raise
      time.sleep(args.poll_seconds)
      continue

    action = result.get("action")
    if action == "complete":
      return
    if action == "stop":
      if args.cancel_on_anomaly:
        cancelled = _cancel_anomalous_jobs(result)
        if cancelled:
          _emit(cancelled, args.audit_log)
      raise RuntimeError(f"Pipeline stopped by quality gate: {result}")
    time.sleep(10 if action in ("launch", "finalize") else args.poll_seconds)


if __name__ == "__main__":
  main()
