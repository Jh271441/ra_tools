#!/usr/bin/env python3
"""Build and optionally upload sampled RA reproduction scenarios.

The default mode is read-only: it deterministically samples each release and
cohort, validates the issue-to-tripSegment conversion, and writes a manifest.
Pass --upload only after reviewing that manifest.  Existing scenarios carrying
the same run label are queried first, making repeated uploads idempotent by
scenario name.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from ra_api.scenario_api import ScenarioInterface, TripSegment


LOGGER = logging.getLogger(__name__)
DEFAULT_SOURCE = "/tmp/ra_trail_20260601_20260828/simulation_cohorts.csv"
DEFAULT_OUTPUT = "/tmp/ra_repro_20260828_sample50.csv"
COHORTS = ("positive_auto", "negative_auto", "positive_manual")
MODULES = ["PREDICTION", "PLANNING", "ROUTING", "MODEL_POSE", "CONTROL"]


def _as_int(value: object, field: str) -> int:
  if value is None or pd.isna(value):
    raise ValueError(f"missing {field}")
  return int(float(value))


def _stable_rank(issue_id: str, seed: str) -> str:
  return hashlib.sha256(f"{seed}:{issue_id}".encode("utf-8")).hexdigest()


def _build_suffix(version: object) -> str:
  match = re.search(r"\.(\d+)$", str(version or ""))
  return match.group(1) if match else "unknown"


def _round_robin_sample(frame: pd.DataFrame, count: int, seed: str) -> pd.DataFrame:
  """Sample evenly across result, trigger, build suffix, and create date."""
  if len(frame) <= count:
    return frame.copy()
  work = frame.copy()
  work["_build"] = work["version"].map(_build_suffix)
  work["_date"] = pd.to_datetime(
      work["create_time"], unit="ms", utc=True, errors="coerce").dt.strftime("%Y-%m-%d")
  work["_stratum"] = list(zip(
      work["ra_merge_result"].fillna("<empty>"),
      work["ra_trigger"].fillna("<empty>"),
      work["_build"],
      work["_date"].fillna("<empty>"),
  ))
  work["_rank"] = work["issue_id"].astype(str).map(
      lambda issue_id: _stable_rank(issue_id, seed))
  groups = {
      key: group.sort_values("_rank").to_dict("records")
      for key, group in work.groupby("_stratum", sort=True)
  }
  selected = []
  keys = sorted(groups, key=str)
  while len(selected) < count and keys:
    remaining = []
    for key in keys:
      rows = groups[key]
      if rows and len(selected) < count:
        selected.append(rows.pop(0))
      if rows:
        remaining.append(key)
    keys = remaining
  result = pd.DataFrame(selected)
  return result[frame.columns]


def build_manifest(source: Path, sample_size: int, seed: str,
                   releases: Iterable[str] | None, cohorts: Iterable[str] | None,
                   run_label: str) -> pd.DataFrame:
  frame = pd.read_csv(source, low_memory=False)
  if "datae_visible_filters_match" in frame:
    frame = frame[frame["datae_visible_filters_match"].astype(str).str.lower().isin(
        ("true", "1"))]
  frame = frame[frame["cohort"].isin(COHORTS)].copy()
  if cohorts:
    wanted_cohorts = set(cohorts)
    unknown = wanted_cohorts - set(COHORTS)
    if unknown:
      raise ValueError(f"unknown cohorts: {sorted(unknown)}")
    frame = frame[frame["cohort"].isin(wanted_cohorts)]
  if releases:
    wanted = set(releases)
    frame = frame[frame["release"].isin(wanted)]

  sampled = []
  for (release, cohort), group in frame.groupby(["release", "cohort"], sort=True):
    selected = _round_robin_sample(
        group, sample_size, f"{seed}:{release}:{cohort}")
    selected = selected.copy()
    selected["source_count"] = len(group)
    sampled.append(selected)
  if not sampled:
    raise ValueError("no rows matched requested releases/cohorts")
  result = pd.concat(sampled, ignore_index=True)
  # The source CSV is very wide and fragmented; compact it before appending
  # manifest-only columns.
  result = result.copy()

  starts = []
  ends = []
  names = []
  labels = []
  errors = []
  warnings = []
  for row in result.to_dict("records"):
    error = ""
    warning = ""
    try:
      anchor = _as_int(row.get("ra_start_timestamp"), "ra_start_timestamp")
      trip_start = _as_int(row.get("trip_start_time"), "trip_start_time")
      trip_end = _as_int(row.get("trip_end_time"), "trip_end_time")
      if trip_start > 0 and trip_end > trip_start and trip_start <= anchor <= trip_end:
        start = max(anchor - 20_000, trip_start)
        end = min(anchor + 10_000, trip_end)
      else:
        start = anchor - 20_000
        end = anchor + 10_000
        warning = (
            f"ignored unusable trip bounds {trip_start}..{trip_end}; "
            "used anchor window")
      if end <= start:
        raise ValueError(f"invalid clipped window {start}..{end}")
    except (TypeError, ValueError) as exc:
      start = end = None
      error = str(exc)
    release = str(row["release"])
    cohort = str(row["cohort"])
    issue_id = str(row["issue_id"])
    trigger_group = "ManualTrigger" if cohort == "positive_manual" else "AutoTrigger"
    scenario_name = f"{run_label}_{release}_{cohort}_{issue_id}"
    scenario_labels = [
        run_label,
        f"{run_label}_{release}",
        f"{run_label}_{cohort}",
        f"{run_label}_{trigger_group}",
        "scenario_from_issue",
        "data_sim",
        f"#{issue_id[2:]}" if issue_id.startswith("cn") else issue_id,
    ]
    starts.append(start)
    ends.append(end)
    names.append(scenario_name)
    labels.append(json.dumps(scenario_labels, ensure_ascii=False))
    errors.append(error)
    warnings.append(warning)
  result["scenario_start_timestamp"] = starts
  result["scenario_end_timestamp"] = ends
  result["scenario_duration_ms"] = result["scenario_end_timestamp"] - result[
      "scenario_start_timestamp"]
  result["scenario_name"] = names
  result["scenario_labels"] = labels
  result["validation_error"] = errors
  result["boundary_warning"] = warnings
  result["scenario_id"] = pd.NA
  result["upload_status"] = "dry_run"
  return result


def _existing_by_name(run_label: str) -> dict[str, int]:
  # The legacy ScenarioInterface forwards this value verbatim; the backend
  # expects a comma-separated string, not a Python list.
  frame = ScenarioInterface.query_scenario(query_labels=run_label, size=500)
  if frame.empty:
    return {}
  return {
      str(row["name"]): int(row["id"])
      for row in frame.to_dict("records")
      if row.get("name") and row.get("id") is not None
  }


def _upload_one(row: dict, username: str) -> tuple[bool, object]:
  labels = json.loads(row["scenario_labels"])
  return ScenarioInterface.add_scenario(
      name=str(row["scenario_name"]),
      trip_segment=TripSegment(
          str(row["trip_id"]),
          int(row["scenario_start_timestamp"]),
          int(row["scenario_end_timestamp"]),
      ),
      metrics_json=None,
      module=MODULES,
      scenario_label=labels,
      scenario_tags=None,
      username=username,
      warmup_s=3,
      description=(
          "RA road-to-sim reproduction sample; "
          f"release={row['release']}; cohort={row['cohort']}; issue={row['issue_id']}"),
      extra_attrs=None,
  )


def upload_manifest(frame: pd.DataFrame, run_label: str, username: str,
                    limit: int | None, workers: int) -> pd.DataFrame:
  result = frame.copy()
  existing = _existing_by_name(run_label)
  pending: list[tuple[int, dict]] = []
  for index, row in result.iterrows():
    if row["validation_error"]:
      result.at[index, "upload_status"] = "invalid"
      continue
    name = str(row["scenario_name"])
    if name in existing:
      result.at[index, "scenario_id"] = existing[name]
      result.at[index, "upload_status"] = "existing"
      continue
    if limit is not None and len(pending) >= limit:
      result.at[index, "upload_status"] = "not_uploaded_limit"
      continue
    pending.append((index, row.to_dict()))

  LOGGER.info("existing=%d, creating=%d with workers=%d", len(existing),
              len(pending), workers)
  with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
    future_to_item = {
        pool.submit(_upload_one, row, username): (index, row)
        for index, row in pending
    }
    for completed, future in enumerate(
        concurrent.futures.as_completed(future_to_item), start=1):
      index, row = future_to_item[future]
      try:
        ok, value = future.result()
      except Exception as exc:  # Preserve the failed row for a later retry.
        ok, value = False, f"exception:{exc}"
      if ok:
        result.at[index, "scenario_id"] = int(value)
        result.at[index, "upload_status"] = "uploaded"
        existing[str(row["scenario_name"])] = int(value)
      else:
        result.at[index, "upload_status"] = f"failed:{value}"
      if completed % 100 == 0 or completed == len(pending):
        LOGGER.info("upload progress %d/%d", completed, len(pending))
  return result


def _log_summary(frame: pd.DataFrame) -> None:
  summary = frame.groupby(["release", "cohort"], sort=True).agg(
      sampled=("issue_id", "size"),
      source=("source_count", "max"),
      invalid=("validation_error", lambda values: sum(bool(value) for value in values)),
  ).reset_index()
  LOGGER.info("\n%s", summary.to_string(index=False))
  LOGGER.info("total sampled=%d, invalid=%d", len(frame),
              int(frame["validation_error"].astype(bool).sum()))


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--source", default=DEFAULT_SOURCE)
  parser.add_argument("--output", default=DEFAULT_OUTPUT)
  parser.add_argument("--sample-size", type=int, default=50)
  parser.add_argument("--seed", default="ra-repro-20260828-v1")
  parser.add_argument("--release", action="append", default=[])
  parser.add_argument("--cohort", action="append", default=[])
  parser.add_argument("--run-label", default="ra_repro_sample50_20260828")
  parser.add_argument("--username", default="jasperchen")
  parser.add_argument("--upload", action="store_true")
  parser.add_argument("--workers", type=int, default=8)
  parser.add_argument(
      "--upload-limit", type=int, default=None,
      help="Maximum number of new scenarios to create; useful for canary upload.")
  return parser.parse_args()


def main() -> None:
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
  args = parse_args()
  frame = build_manifest(
      Path(args.source), args.sample_size, args.seed, args.release or None,
      args.cohort or None, args.run_label)
  _log_summary(frame)
  if args.upload:
    frame = upload_manifest(
        frame, args.run_label, args.username, args.upload_limit, args.workers)
    LOGGER.info("upload statuses: %s", frame["upload_status"].value_counts().to_dict())
  output = Path(args.output)
  output.parent.mkdir(parents=True, exist_ok=True)
  frame.to_csv(output, index=False)
  LOGGER.info("wrote %s", output)


if __name__ == "__main__":
  main()
