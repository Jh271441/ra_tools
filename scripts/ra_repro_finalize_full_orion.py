#!/usr/bin/env python3
"""Validate all registered full-release RA jobs and render final metrics."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ra_repro_validate_orion import validate
from ra_api.sim_result_api import SimResultClient


_TRIGGER_METRIC = "dpe_assist_channel_triggered__group1"


def _ratio(numerator: int, denominator: int) -> float | None:
  return numerator / denominator if denominator else None


def _pct(value: float | None) -> str:
  return "—" if value is None else f"{value:.2%}"


def _summary_row(release: str, job_id: int,
                 result: dict[str, Any]) -> dict[str, Any]:
  audit = result["manifest_audit"]
  cohorts = result["cohorts"]
  truth = result["truth"]
  return {
      "release": release,
      "job_id": job_id,
      "source_rows": audit["source_rows"],
      "submitted_rows": audit["submitted_rows"],
      "excluded_rows": audit["excluded_rows"],
      "completed": result["completed"],
      "terminal_failed": result["terminal_failed"],
      "completed_dpe_covered": result["completed_dpe_covered"],
      "completed_missing_dpe": result["completed_missing_dpe"],
      "completed_pending_dpe_grace": result[
          "completed_pending_dpe_grace"],
      "quality_gate_passed_so_far": result["quality"][
          "gate_passed_so_far"],
      "positive_auto_road_reproduction": cohorts["positive_auto"][
          "road_behavior_reproduction"],
      "negative_auto_road_reproduction": cohorts["negative_auto"][
          "road_behavior_reproduction"],
      "positive_manual_road_reproduction": cohorts["positive_manual"][
          "road_behavior_reproduction"],
      "truth_tp": truth["tp"],
      "truth_fn": truth["fn"],
      "truth_fp": truth["fp"],
      "truth_tn": truth["tn"],
      "truth_precision": truth["precision"],
      "truth_recall": truth["recall"],
      "truth_specificity": truth["specificity"],
      "truth_accuracy": truth["accuracy"],
      "terminal_and_complete": result["is_terminal_and_complete"],
  }


def _overall(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
  cohorts = {}
  for cohort in ("positive_auto", "negative_auto", "positive_manual"):
    evaluated = sum(result["cohorts"][cohort]["evaluated"]
                    for result in results.values())
    triggered = sum(result["cohorts"][cohort]["triggered"]
                    for result in results.values())
    road_matches = sum(result["cohorts"][cohort]["road_behavior_matches"]
                       for result in results.values())
    cohorts[cohort] = {
        "evaluated": evaluated,
        "triggered": triggered,
        "not_triggered": evaluated - triggered,
        "road_behavior_matches": road_matches,
        "road_behavior_reproduction": _ratio(road_matches, evaluated),
    }
  tp = sum(result["truth"]["tp"] for result in results.values())
  fn = sum(result["truth"]["fn"] for result in results.values())
  fp = sum(result["truth"]["fp"] for result in results.values())
  tn = sum(result["truth"]["tn"] for result in results.values())
  quality_keys = (
      "simulator_cache_hits",
      "simulator_cache_field_missing",
      "inference_log_missing",
      "dpe_output_missing",
      "output_bag_missing",
      "failed_evaluations",
      "tasks_with_warnings",
      "tasks_with_unexpected_warnings",
  )
  quality = {
      key: sum(int(result["quality"][key]) for result in results.values())
      for key in quality_keys
  }
  completed = sum(result["completed"] for result in results.values())
  completed_dpe_covered = sum(result["completed_dpe_covered"]
                              for result in results.values())
  all_tasks_terminal = all(
      int(result.get("terminal", result["completed"] +
                     result["terminal_failed"])) ==
      int(result.get("manifest_unique_scenarios",
                     result["manifest_audit"]["submitted_rows"]))
      for result in results.values())
  completed_missing_dpe = sum(result["completed_missing_dpe"]
                              for result in results.values())
  completed_pending_dpe_grace = sum(
      result["completed_pending_dpe_grace"] for result in results.values())
  all_analysis_inputs_final = (
      all_tasks_terminal and completed_missing_dpe == 0 and
      completed_pending_dpe_grace == 0)
  all_quality_gates_passed = all(
      result["quality"]["gate_passed_so_far"]
      for result in results.values())
  if not all_analysis_inputs_final:
    report_state = "PROVISIONAL"
  elif all_quality_gates_passed:
    report_state = "FINAL"
  else:
    report_state = "FINAL_WITH_QUALITY_FAILURES"
  return {
      "source_rows": sum(result["manifest_audit"]["source_rows"]
                         for result in results.values()),
      "submitted_rows": sum(result["manifest_audit"]["submitted_rows"]
                            for result in results.values()),
      "excluded_rows": sum(result["manifest_audit"]["excluded_rows"]
                           for result in results.values()),
      "completed": completed,
      "terminal_failed": sum(result["terminal_failed"]
                             for result in results.values()),
      "completed_dpe_covered": completed_dpe_covered,
      "completed_missing_dpe": completed_missing_dpe,
      "completed_pending_dpe_grace": completed_pending_dpe_grace,
      "completed_dpe_coverage": _ratio(completed_dpe_covered, completed),
      "quality": quality,
      "cohorts": cohorts,
      "truth": {
          "tp": tp,
          "fn": fn,
          "fp": fp,
          "tn": tn,
          "precision": _ratio(tp, tp + fp),
          "recall": _ratio(tp, tp + fn),
          "specificity": _ratio(tn, tn + fp),
          "accuracy": _ratio(tp + tn, tp + fn + fp + tn),
      },
      "all_tasks_terminal": all_tasks_terminal,
      "all_analysis_inputs_final": all_analysis_inputs_final,
      "report_state": report_state,
      "all_quality_gates_passed_so_far": all_quality_gates_passed,
      "all_terminal_and_complete": all(
          result["is_terminal_and_complete"] for result in results.values()),
  }


def _markdown(rows: list[dict[str, Any]], overall: dict[str, Any]) -> str:
  report_state = overall["report_state"]
  lines = [
      "# RA full-release reproduction status",
      "",
      f"Report state: **{report_state}**.",
      "",
      "Historical road behavior expects `positive_auto` and `negative_auto` "
      "to trigger, and `positive_manual` not to trigger. Business truth treats "
      "`positive_auto` plus `positive_manual` as positive and `negative_auto` "
      "as negative.",
      "",
      "| Release | Job | Done / submitted | DPE | Pos-auto road | Neg-auto road | Manual road | Precision | Recall | Specificity | Accuracy | Quality | Complete |",
      "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|",
  ]
  for row in rows:
    lines.append(
        f"| {row['release']} | {row['job_id']} | "
        f"{row['completed']} / {row['submitted_rows']} | "
        f"{row['completed_dpe_covered']} | "
        f"{_pct(row['positive_auto_road_reproduction'])} | "
        f"{_pct(row['negative_auto_road_reproduction'])} | "
        f"{_pct(row['positive_manual_road_reproduction'])} | "
        f"{_pct(row['truth_precision'])} | {_pct(row['truth_recall'])} | "
        f"{_pct(row['truth_specificity'])} | {_pct(row['truth_accuracy'])} | "
        f"{'pass' if row['quality_gate_passed_so_far'] else 'fail'} | "
        f"{'yes' if row['terminal_and_complete'] else 'no'} |")
  truth = overall["truth"]
  cohorts = overall["cohorts"]
  lines.extend([
      "",
      f"Overall submitted: {overall['submitted_rows']} / "
      f"{overall['source_rows']} (excluded {overall['excluded_rows']}).",
      f"Completed with DPE: {overall['completed_dpe_covered']} / "
      f"{overall['completed']} "
      f"({_pct(overall['completed_dpe_coverage'])}).",
      f"Road reproduction: positive_auto "
      f"{_pct(cohorts['positive_auto']['road_behavior_reproduction'])}, "
      f"negative_auto {_pct(cohorts['negative_auto']['road_behavior_reproduction'])}, "
      f"positive_manual {_pct(cohorts['positive_manual']['road_behavior_reproduction'])}.",
      f"Business truth: precision {_pct(truth['precision'])}, "
      f"recall {_pct(truth['recall'])}, specificity "
      f"{_pct(truth['specificity'])}, accuracy {_pct(truth['accuracy'])}.",
      f"All submitted tasks terminal: "
      f"{'yes' if overall['all_tasks_terminal'] else 'no'}.",
      f"All terminal and complete: "
      f"{'yes' if overall['all_terminal_and_complete'] else 'no'}.",
      f"All quality gates passed so far: "
      f"{'yes' if overall['all_quality_gates_passed_so_far'] else 'no'}.",
      "Quality counts: cache hits "
      f"{overall['quality']['simulator_cache_hits']}, missing cache field "
      f"{overall['quality']['simulator_cache_field_missing']}, missing "
      f"inference log {overall['quality']['inference_log_missing']}, missing "
      f"DPE output {overall['quality']['dpe_output_missing']}, missing output "
      f"bag {overall['quality']['output_bag_missing']}, failed evaluations "
      f"{overall['quality']['failed_evaluations']}, unexpected-warning tasks "
      f"{overall['quality']['tasks_with_unexpected_warnings']}.",
      "",
  ])
  return "\n".join(lines)


def _write_payload(payload: dict[str, Any], output_prefix: Path) -> None:
  output_prefix.parent.mkdir(parents=True, exist_ok=True)
  output_prefix.with_suffix(".json").write_text(
      json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8")
  pd.DataFrame(payload["summary"]).to_csv(
      output_prefix.with_suffix(".csv"), index=False)
  output_prefix.with_suffix(".md").write_text(
      _markdown(payload["summary"], payload["overall"]), encoding="utf-8")


def finalize(registry_path: Path, manifest_template: str, token: str,
             output_prefix: Path) -> dict[str, Any]:
  registry = json.loads(registry_path.read_text(encoding="utf-8"))
  results = {}
  rows = []
  for release, registered in registry.items():
    version_date = release.rsplit("-", 1)[-1]
    manifest_path = Path(manifest_template.format(
        release=release, date=version_date))
    result = validate([int(registered["job_id"])], manifest_path, release,
                      token)
    results[release] = result
    rows.append(_summary_row(release, int(registered["job_id"]), result))
  overall = _overall(results)
  payload = {
      "generated_at": datetime.now(timezone.utc).isoformat(),
      "registry": str(registry_path),
      "manifest_template": manifest_template,
      "overall": overall,
      "summary": rows,
      "per_release": results,
  }
  _write_payload(payload, output_prefix)
  return payload


def rerender(existing_json: Path, output_prefix: Path) -> dict[str, Any]:
  """Re-render an already validated payload without querying Orion again."""
  payload = json.loads(existing_json.read_text(encoding="utf-8"))
  payload["overall"] = _overall(payload["per_release"])
  payload["rerendered_at"] = datetime.now(timezone.utc).isoformat()
  _write_payload(payload, output_prefix)
  return payload


def attach_scenario_results(existing_json: Path, registry_path: Path,
                            manifest_template: str,
                            output_prefix: Path) -> dict[str, Any]:
  """Attach scenario-level DPE rows without re-querying Orion task state."""
  payload = json.loads(existing_json.read_text(encoding="utf-8"))
  registry = json.loads(registry_path.read_text(encoding="utf-8"))
  client = SimResultClient()
  for release, registered in registry.items():
    version_date = release.rsplit("-", 1)[-1]
    manifest_path = Path(manifest_template.format(
        release=release, date=version_date))
    manifest = pd.read_csv(manifest_path, low_memory=False)
    manifest = manifest[manifest["release"].astype(str).eq(release)].copy()
    if "upload_status" in manifest.columns:
      manifest = manifest[manifest["upload_status"].isin(("uploaded", "existing"))]
    manifest["scenario_id"] = manifest["scenario_id"].astype(int)

    job_id = int(registered["job_id"])
    dpe = client.query_all_pages(
        job_id,
        metrics=["dpe_assist_channel_triggered"],
        page_size=1000,
    )
    if dpe.empty:
      raise RuntimeError(f"DPE returned no rows for {release} job {job_id}")
    dpe["scenario_id"] = dpe["scenario_id"].astype(int)
    dpe = dpe[["scenario_id", _TRIGGER_METRIC]].drop_duplicates(
        "scenario_id")
    failed_ids = {
        int(value)
        for value in payload["per_release"][release].get(
            "terminal_failed_scenario_ids", [])
    }
    if failed_ids:
      dpe = dpe[~dpe["scenario_id"].isin(failed_ids)]
    joined = manifest[["scenario_id", "issue_id", "cohort"]].merge(
        dpe, on="scenario_id", how="inner", validate="1:1")
    expected = int(payload["per_release"][release]["completed_dpe_covered"])
    if len(joined) != expected:
      raise RuntimeError(
          f"DPE coverage mismatch for {release}: expected {expected}, "
          f"received {len(joined)}")
    payload["per_release"][release]["scenario_results"] = [
        {
            "scenario_id": int(row.scenario_id),
            "issue_id": str(row.issue_id),
            "cohort": str(row.cohort),
            "source_job_id": job_id,
            "dpe_assist_channel_triggered": float(
                getattr(row, _TRIGGER_METRIC)),
            "sim_triggered": bool(getattr(row, _TRIGGER_METRIC) >= 1),
        }
        for row in joined.itertuples(index=False)
    ]
  payload["scenario_results_attached_at"] = datetime.now(
      timezone.utc).isoformat()
  payload["overall"] = _overall(payload["per_release"])
  _write_payload(payload, output_prefix)
  return payload


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument(
      "--registry", type=Path,
      default=Path("reports/ra_repro_full_20260829_jobs.json"))
  parser.add_argument(
      "--manifest-template",
      default="reports/ra_repro_full_20260829_manifest.csv")
  parser.add_argument(
      "--output-prefix", type=Path,
      default=Path("reports/ra_repro_full_20260829_metrics"))
  parser.add_argument(
      "--rerender-existing", type=Path, default=None,
      help="Re-render a validated JSON payload without querying Orion/DPE")
  parser.add_argument(
      "--attach-scenario-results", type=Path, default=None,
      help="Attach DPE scenario rows to an existing final metrics JSON")
  parser.add_argument("--orion-token", default=None)
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if args.attach_scenario_results:
    payload = attach_scenario_results(
        args.attach_scenario_results,
        args.registry,
        args.manifest_template,
        args.output_prefix,
    )
    print(json.dumps({
        release: len(result.get("scenario_results") or [])
        for release, result in payload["per_release"].items()
    }, ensure_ascii=False, indent=2))
    return
  if args.rerender_existing:
    payload = rerender(args.rerender_existing, args.output_prefix)
    print(json.dumps(payload["overall"], ensure_ascii=False, indent=2))
    return
  token = args.orion_token
  if not token:
    try:
      from orion_client.utils.config_utils import get_auth_token
      from voy_data_utils.regions import Regions
      token = get_auth_token(None, Regions.CN)
    except ImportError as exc:
      raise SystemExit("Set --orion-token or add Orion libs to PYTHONPATH") from exc
  payload = finalize(args.registry, args.manifest_template, token,
                     args.output_prefix)
  print(json.dumps(payload["overall"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
