from pathlib import Path
import sys

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ra_repro_scenario_sample import build_manifest


def test_build_manifest_uses_auditable_long_history_window(tmp_path):
  source = tmp_path / "source.csv"
  pd.DataFrame([{
      "release": "gen4-release-20260814",
      "cohort": "positive_auto",
      "issue_id": "cn1",
      "version": "1.gen4-release-20260814.1",
      "create_time": 1_000_000,
      "ra_merge_result": "成功",
      "ra_trigger": "StuckModel",
      "ra_start_timestamp": 100_000,
      "trip_start_time": 10_000,
      "trip_end_time": 200_000,
      "trip_id": "trip",
  }]).to_csv(source, index=False)

  manifest = build_manifest(
      source,
      sample_size=1,
      seed="seed",
      releases=None,
      cohorts=None,
      run_label="test",
  )
  row = manifest.iloc[0]

  assert row["scenario_start_timestamp"] == 40_000
  assert row["scenario_end_timestamp"] == 110_000
  assert row["scenario_pre_buffer_ms"] == 60_000
  assert row["scenario_post_buffer_ms"] == 10_000
  assert "pre60000ms_post10000ms" in row["scenario_name"]


def test_physical_manifest_keeps_trigger_groups_and_changes_identity_with_inputs(tmp_path):
  source = tmp_path / "physical.csv"
  rows = [{
      "release": "gen4-release-20261106", "cohort": cohort, "issue_id": f"cn{index}",
      "ra_start_timestamp": 100_000, "trip_start_time": 10_000, "trip_end_time": 200_000,
      "trip_id": "12345_20261106_120000",
  } for index, cohort in enumerate(("source_auto", "source_manual"))]
  pd.DataFrame(rows).to_csv(source, index=False)
  def build():
    return build_manifest(source, 100, "seed", None, None, "ra_repro_physical_20261106", physical=True)
  manifest = build()
  assert set(manifest["cohort"]) == {"source_auto", "source_manual"}
  assert manifest.iloc[0]["validation_error"] == manifest.iloc[1]["validation_error"] == ""
  assert "_AutoTrigger" in manifest.iloc[0]["scenario_labels"]
  assert "_ManualTrigger" in manifest.iloc[1]["scenario_labels"]
  original = manifest["scenario_name"].tolist()
  assert build()["scenario_name"].tolist() == original
  rows[0]["ra_start_timestamp"] += 1000
  pd.DataFrame(rows).to_csv(source, index=False)
  updated = build()["scenario_name"].tolist()
  assert updated[0] != original[0] and updated[1] == original[1]
