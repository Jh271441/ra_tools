#!/usr/bin/env python3
"""Compare trigger stability for exact segments shared by two Orion jobs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ra_api.scenario_api import ScenarioInterface
from ra_api.sim_result_api import SimResultClient
from scripts.ra_repro_validate_orion import _load_manifest, _query_orion


_TRIGGER_METRIC = "dpe_assist_channel_triggered__group1"


def _query_dpe(job_id: int) -> pd.DataFrame:
  frame = SimResultClient().query_all_pages(
      job_id,
      metrics=["dpe_assist_channel_triggered"],
      page_size=100,
  )
  if frame.empty:
    return pd.DataFrame(columns=["scenario_id", "triggered"])
  frame = frame[["scenario_id", _TRIGGER_METRIC]].copy()
  frame["scenario_id"] = frame["scenario_id"].astype(int)
  frame["triggered"] = frame[_TRIGGER_METRIC].ge(1)
  return frame[["scenario_id", "triggered"]].drop_duplicates("scenario_id")


def _query_segments(scenario_ids: Sequence[int]) -> pd.DataFrame:
  ids = ",".join(str(value) for value in scenario_ids)
  frame = ScenarioInterface.query_scenario(
      query_scenario_ids=ids,
      size=max(500, len(scenario_ids)),
  )
  required = {"id", "trip_id", "start_timestamp", "end_timestamp"}
  missing = required - set(frame.columns)
  if missing:
    raise ValueError(f"Trail scenario response missing columns: {sorted(missing)}")
  frame = frame.rename(columns={"id": "scenario_id"}).copy()
  for column in ("scenario_id", "start_timestamp", "end_timestamp"):
    frame[column] = frame[column].astype(int)
  return frame[[
      "scenario_id", "trip_id", "start_timestamp", "end_timestamp"
  ]].drop_duplicates("scenario_id")


def _completed(tasks: pd.DataFrame) -> pd.DataFrame:
  selected = tasks["task_status"].eq(3) & tasks["task_outcome"].fillna(
      "").str.startswith("Done")
  return tasks.loc[selected, ["scenario_id"]].drop_duplicates()


def _segment_key(frame: pd.DataFrame, start: str, end: str) -> pd.Series:
  return (frame["trip_id"].astype(str) + "|" +
          frame[start].astype(int).astype(str) + "|" +
          frame[end].astype(int).astype(str))


def _summarize_overlap(overlap: pd.DataFrame, overlap_possible: int,
                       current_job_id: int, reference_job_id: int) -> Dict[str, Any]:
  overlap = overlap.copy()
  overlap["agrees"] = overlap["triggered_current"].eq(
      overlap["triggered_reference"])
  cohorts = {}
  for cohort, group in overlap.groupby("cohort", dropna=False):
    agreements = int(group["agrees"].sum())
    cohorts[str(cohort)] = {
        "evaluated_overlap": len(group),
        "agreements": agreements,
        "disagreements": len(group) - agreements,
        "agreement_rate": agreements / len(group) if len(group) else None,
    }
  agreements = int(overlap["agrees"].sum())
  conflicts = overlap.loc[~overlap["agrees"], [
      "issue_id", "cohort", "scenario_id_current", "scenario_id_reference",
      "triggered_current", "triggered_reference"
  ]].to_dict("records")
  return {
      "current_job_id": current_job_id,
      "reference_job_id": reference_job_id,
      "exact_segment_overlap_possible": overlap_possible,
      "evaluated_overlap": len(overlap),
      "agreements": agreements,
      "disagreements": len(overlap) - agreements,
      "agreement_rate": agreements / len(overlap) if len(overlap) else None,
      "cohorts": cohorts,
      "conflicts": conflicts,
  }


def compare(current_job_id: int, reference_job_id: int, manifest_path: Path,
            release: str | None, token: str) -> Dict[str, Any]:
  manifest = _load_manifest(manifest_path, release)
  required = {"trip_id", "scenario_start_timestamp", "scenario_end_timestamp"}
  missing = required - set(manifest.columns)
  if missing:
    raise ValueError(f"Manifest missing segment columns: {sorted(missing)}")
  manifest["segment_key"] = _segment_key(
      manifest, "scenario_start_timestamp", "scenario_end_timestamp")

  current_tasks = _query_orion(current_job_id, token)
  reference_tasks = _query_orion(reference_job_id, token)
  reference_segments = _query_segments(reference_tasks["scenario_id"].tolist())
  reference_segments["segment_key"] = _segment_key(
      reference_segments, "start_timestamp", "end_timestamp")

  overlap_possible = int(
      manifest["segment_key"].isin(reference_segments["segment_key"]).sum())

  current = manifest.merge(_completed(current_tasks), on="scenario_id")
  current = current.merge(_query_dpe(current_job_id), on="scenario_id")
  current = current.rename(columns={
      "scenario_id": "scenario_id_current",
      "triggered": "triggered_current",
  })

  reference = reference_segments.merge(
      _completed(reference_tasks), on="scenario_id")
  reference = reference.merge(_query_dpe(reference_job_id), on="scenario_id")
  reference = reference.rename(columns={
      "scenario_id": "scenario_id_reference",
      "triggered": "triggered_reference",
  })

  overlap = current.merge(
      reference[[
          "segment_key", "scenario_id_reference", "triggered_reference"
      ]],
      on="segment_key",
      how="inner",
      validate="1:1",
  )
  return _summarize_overlap(overlap, overlap_possible, current_job_id,
                            reference_job_id)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--current-job-id", type=int, required=True)
  parser.add_argument("--reference-job-id", type=int, required=True)
  parser.add_argument("--manifest", type=Path, required=True)
  parser.add_argument("--release", default=None)
  parser.add_argument("--orion-token", default=os.environ.get("ORION_TOKEN"))
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  if not args.orion_token:
    raise SystemExit("Set ORION_TOKEN or pass --orion-token")
  result = compare(args.current_job_id, args.reference_job_id, args.manifest,
                   args.release, args.orion_token)
  print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
