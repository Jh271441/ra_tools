#!/usr/bin/env python3
"""Analyze paired Orion tasks for the independent-RA-replay batch A/B."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
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


def _ratio(numerator: int, denominator: int) -> float | None:
  return numerator / denominator if denominator else None


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
  groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
  for row in rows:
    groups[str(row[key])].append(row)
  result = {}
  for name, group in sorted(groups.items()):
    complete = [row for row in group if row["paired_dpe_complete"]]
    transitions = Counter(row["transition"] for row in complete)
    result[name] = {
        "scenarios": len(group),
        "paired_dpe_complete": len(complete),
        "control_triggered": sum(bool(row["control_triggered"])
                                 for row in complete),
        "feature_triggered": sum(bool(row["feature_triggered"])
                                 for row in complete),
        "transitions": dict(sorted(transitions.items())),
    }
  return result


def analyze(job_id: int, manifest_path: Path) -> dict[str, Any]:
  manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  TaskAccessor, OrionTask, Regions, TrailRegionMgr = _load_orion_api()
  with TrailRegionMgr(Regions.CN, is_pre=False):
    tasks = list(TaskAccessor.query({
        "job_id": job_id,
        "kind": OrionTask.MAPPER,
        "extra_fields": "task_args,result",
    }))
  task_by_signature = {str(task["signature"]): task for task in tasks}
  dpe = SimResultClient().query_all_pages(
      job_id,
      metrics=["dpe_assist_channel_triggered"],
      page_size=100,
  )
  dpe_by_signature = {}
  if not dpe.empty:
    for row in dpe.to_dict("records"):
      dpe_by_signature[str(row["signature"])] = row.get(_TRIGGER_METRIC)

  paired_rows = []
  quality = Counter()
  status_counts = Counter()
  for manifest_row in manifest["rows"]:
    scenario_id = int(manifest_row["scenario_id"])
    arm_rows = {}
    for arm in ("control", "feature"):
      signature = f"{scenario_id}-{arm}"
      task = task_by_signature.get(signature)
      if task is None:
        arm_rows[arm] = {
            "signature": signature,
            "task_present": False,
            "triggered": None,
        }
        quality["missing_task"] += 1
        continue
      status = int(task["status"])
      status_counts[str(status)] += 1
      result = _result_dict(task.get("result"))
      metric = dpe_by_signature.get(signature)
      triggered = metric is not None and float(metric) >= 1.0
      arm_rows[arm] = {
          "task_id": int(task["id"]),
          "signature": signature,
          "task_present": True,
          "status": status,
          "terminal": status in _TERMINAL_STATUSES,
          "completed": status == 3,
          "outcome": task.get("outcome") or "",
          "simulator_cache_hit": result.get("simulator_cache_hit"),
          "inference_log_count": len(
              result.get("inference_log_locations") or []),
          "dpe_output_count": len(result.get("dpe_output_locations") or []),
          "output_bag_count": len(result.get("output_bag_locations") or []),
          "failed_evaluation_count": len(
              result.get("failed_evaluations") or []),
          "dpe_assist_channel_triggered": metric,
          "triggered": triggered if metric is not None else None,
      }
      if status == 3:
        if result.get("simulator_cache_hit") is not False:
          quality["completed_bad_cache_state"] += 1
        if not result.get("inference_log_locations"):
          quality["completed_missing_inference"] += 1
        if not result.get("dpe_output_locations"):
          quality["completed_missing_dpe_output"] += 1
        if not result.get("output_bag_locations"):
          quality["completed_missing_output_bag"] += 1
        if result.get("failed_evaluations"):
          quality["completed_failed_evaluation"] += 1

    control_triggered = arm_rows["control"]["triggered"]
    feature_triggered = arm_rows["feature"]["triggered"]
    paired_complete = control_triggered is not None and feature_triggered is not None
    transition = None
    if paired_complete:
      transition = f"{int(control_triggered)}->{int(feature_triggered)}"
    paired_rows.append({
        **manifest_row,
        "paired_dpe_complete": paired_complete,
        "control_triggered": control_triggered,
        "feature_triggered": feature_triggered,
        "transition": transition,
        "control": arm_rows["control"],
        "feature": arm_rows["feature"],
    })

  terminal = all(
      row[arm].get("terminal", False)
      for row in paired_rows for arm in ("control", "feature"))
  complete_pairs = [row for row in paired_rows if row["paired_dpe_complete"]]
  transitions = Counter(row["transition"] for row in complete_pairs)
  primary = [row for row in complete_pairs
             if row["stratum"] == "pos_auto_old_fn"]
  safety = [row for row in complete_pairs if row["stratum"] in {
      "pos_auto_old_tp", "neg_auto_old_tn", "manual_old_nontrigger"}]
  result = {
      "generated_at": datetime.now(timezone.utc).isoformat(),
      "job_id": job_id,
      "manifest": str(manifest_path),
      "scenario_count": len(manifest["rows"]),
      "expected_task_count": 2 * len(manifest["rows"]),
      "observed_task_count": len(tasks),
      "terminal": terminal,
      "paired_dpe_complete": len(complete_pairs),
      "status_counts": dict(sorted(status_counts.items())),
      "quality_violations": dict(sorted(quality.items())),
      "transitions": dict(sorted(transitions.items())),
      "by_stratum": _aggregate(paired_rows, "stratum"),
      "by_cohort": _aggregate(paired_rows, "cohort"),
      "primary_pos_auto_old_fn": {
          "evaluated": len(primary),
          "control_triggered": sum(bool(row["control_triggered"])
                                   for row in primary),
          "feature_triggered": sum(bool(row["feature_triggered"])
                                   for row in primary),
          "rescued_0_to_1": sum(row["transition"] == "0->1"
                                for row in primary),
          "rescue_rate": _ratio(
              sum(row["transition"] == "0->1" for row in primary),
              len(primary)),
      },
      "safety": {
          "evaluated": len(safety),
          "undesired_transitions": [
              {
                  "scenario_id": row["scenario_id"],
                  "issue_id": row["issue_id"],
                  "stratum": row["stratum"],
                  "transition": row["transition"],
              }
              for row in safety
              if ((row["stratum"] == "pos_auto_old_tp" and
                   row["transition"] == "1->0") or
                  (row["stratum"] in {
                      "neg_auto_old_tn", "manual_old_nontrigger"} and
                   row["transition"] == "0->1"))
          ],
      },
      "rows": paired_rows,
  }
  return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--job-id", type=int)
  parser.add_argument(
      "--registry",
      type=Path,
      default=Path(
          "reports/ra_independent_replay_cr6657869_batch_ab_job.json"),
  )
  parser.add_argument(
      "--manifest",
      type=Path,
      default=Path(
          "reports/ra_independent_replay_cr6657869_batch_ab_manifest.json"),
  )
  parser.add_argument("--output", type=Path)
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  job_id = args.job_id
  if job_id is None:
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    job_id = int(registry["job_id"])
  payload = analyze(job_id, args.manifest)
  text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
  if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(args.output)
  print(text, end="")


if __name__ == "__main__":
  main()
