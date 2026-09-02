from pathlib import Path
import sys

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ra_repro_launch_binary_backtest import (
    INDEPENDENT_REPLAY_FLAG,
    STATE_RECOVERY_LEVEL4_FLAG,
    _enable_independent_replay,
    _write_registry,
    select_manifest,
)


def test_select_manifest_is_stratified_and_deterministic(tmp_path):
  releases = [
      "gen4-release-20260731",
      "gen4-release-20260807",
      "gen4-release-20260814",
  ]
  cohorts = ("positive_auto", "negative_auto", "positive_manual")
  rows = []
  scenario_id = 1000
  for release in releases:
    for cohort in cohorts:
      for index in range(5):
        rows.append({
            "release": release,
            "cohort": cohort,
            "scenario_id": scenario_id,
            "issue_id": f"cn{scenario_id}",
            "upload_status": "uploaded",
            "validation_error": "",
            "ordinal": index,
        })
        scenario_id += 1
  source = tmp_path / "manifest.csv"
  pd.DataFrame(rows).to_csv(source, index=False)

  first, audit = select_manifest(source, releases, 2, "seed")
  second, _ = select_manifest(source, releases, 2, "seed")

  assert len(first) == 18
  assert first["scenario_id"].tolist() == second["scenario_id"].tolist()
  assert set(first.groupby(["release", "cohort"]).size()) == {2}
  assert first["backtest_source_release"].equals(first["release"])
  assert audit == {
      "source_rows": 45,
      "excluded_no_bag": 0,
      "excluded_missing_trip": 0,
  }


def test_enable_independent_replay_is_idempotent():
  class Task:
    arguments = {
        "--sim-exec-args": " --sim_aligned_mode --sim_state_recovery_level=3"
    }

  task = Task()
  _enable_independent_replay(task)
  _enable_independent_replay(task)

  assert task.arguments["--sim-exec-args"].split().count(
      INDEPENDENT_REPLAY_FLAG) == 1
  assert task.arguments["--sim-exec-args"].split().count(
      STATE_RECOVERY_LEVEL4_FLAG) == 1
  assert "--sim_state_recovery_level=3" not in task.arguments[
      "--sim-exec-args"].split()


def test_enable_independent_replay_replaces_split_state_recovery_flag():
  class Task:
    arguments = {
        "--sim-exec-args": "--sim_state_recovery_level 2 --sim_aligned_mode"
    }

  task = Task()
  _enable_independent_replay(task)

  assert task.arguments["--sim-exec-args"].split() == [
      "--sim_aligned_mode",
      STATE_RECOVERY_LEVEL4_FLAG,
      INDEPENDENT_REPLAY_FLAG,
  ]


def test_write_registry_is_atomic(tmp_path):
  path = tmp_path / "registry.json"

  _write_registry(path, {"key": {"launch_state": "pending"}})

  assert path.read_text(encoding="utf-8").endswith("\n")
  assert not path.with_suffix(".json.tmp").exists()


def test_select_manifest_rejects_duplicate_issue_ids(tmp_path):
  source = tmp_path / "manifest.csv"
  pd.DataFrame([
      {
          "release": "gen4-release-20260731",
          "cohort": "positive_auto",
          "scenario_id": 1,
          "issue_id": "cn1",
          "upload_status": "uploaded",
          "validation_error": "",
      },
      {
          "release": "gen4-release-20260731",
          "cohort": "negative_auto",
          "scenario_id": 2,
          "issue_id": "cn1",
          "upload_status": "uploaded",
          "validation_error": "",
      },
  ]).to_csv(source, index=False)

  with pytest.raises(ValueError, match="duplicate issue ids"):
    select_manifest(
        source, ["gen4-release-20260731"], 0, "seed")
