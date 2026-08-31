import json
from pathlib import Path
import sys

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ra_repro_finalize_binary_backtest import (
    INDEPENDENT_REPLAY_FLAG,
    finalize,
    summarize_job_configuration,
    summarize_sources,
)


def test_summarize_sources_keeps_release_truth_counts_separate():
  manifest = pd.DataFrame([
      {"release": "v1", "cohort": "positive_auto", "scenario_id": 1},
      {"release": "v1", "cohort": "positive_manual", "scenario_id": 2},
      {"release": "v1", "cohort": "negative_auto", "scenario_id": 3},
      {"release": "v2", "cohort": "positive_auto", "scenario_id": 4},
      {"release": "v2", "cohort": "positive_manual", "scenario_id": 5},
      {"release": "v2", "cohort": "negative_auto", "scenario_id": 6},
  ])
  results = [
      {"scenario_id": 1, "sim_triggered": True},
      {"scenario_id": 2, "sim_triggered": False},
      {"scenario_id": 3, "sim_triggered": True},
      {"scenario_id": 4, "sim_triggered": True},
      {"scenario_id": 5, "sim_triggered": True},
      {"scenario_id": 6, "sim_triggered": False},
  ]

  sources = summarize_sources(manifest, results)

  assert sources["v1"]["estimated_tp"] == 1
  assert sources["v1"]["estimated_fn"] == 1
  assert sources["v1"]["estimated_fp"] == 1
  assert sources["v1"]["estimated_tn"] == 0
  assert sources["v2"]["estimated_tp"] == 2
  assert sources["v2"]["estimated_fn"] == 0
  assert sources["v2"]["estimated_fp"] == 0
  assert sources["v2"]["estimated_tn"] == 1
  assert sources["v2"]["dpe_coverage"] == 1.0
  assert sources["v1"]["cohorts"]["positive_auto"]["trigger_rate"] == 1.0
  assert sources["v1"]["cohorts"]["positive_manual"]["trigger_rate"] == 0.0
  assert sources["v1"]["cohorts"]["negative_auto"]["trigger_rate"] == 1.0
  assert sources["v2"]["estimation_method"] == "cohort_poststratification"


def test_summarize_job_configuration_requires_all_submission_gates():
  valid_args = {
      "--binary-id": 1775147,
      "--simulator-cache": "disabled",
      "--enable-dpe": "",
      "--sim-exec-args": f"--sim_aligned_mode {INDEPENDENT_REPLAY_FLAG}",
  }
  jobs = [{
      "job_id": 10,
      "cluster": "prod_gen4",
      "max_concurrency": 1,
      "tasks": [{
          "signature": scenario_id,
          "task_args": valid_args.copy(),
      } for scenario_id in range(3)],
  }]

  summary = summarize_job_configuration(jobs, 1775147, [0, 1, 2])

  assert summary["gate_passed"] is True
  assert summary["task_count"] == 3
  assert summary["task_set_checked"] is True
  assert summary["missing_scenario_ids"] == []
  assert summary["unexpected_scenario_ids"] == []

  jobs[0]["tasks"][1]["task_args"].pop("--enable-dpe")
  jobs[0]["tasks"][2]["task_args"]["--sim-exec-args"] = "--sim_aligned_mode"
  summary = summarize_job_configuration(jobs, 1775147)

  assert summary["gate_passed"] is False
  assert summary["dpe_disabled"] == 1
  assert summary["independent_replay_missing"] == 1

  jobs[0]["tasks"][0]["signature"] = 99
  task_mismatch = summarize_job_configuration(jobs, 1775147, [0, 1, 2])
  assert task_mismatch["gate_passed"] is False
  assert task_mismatch["missing_scenario_ids"] == [0]
  assert task_mismatch["unexpected_scenario_ids"] == [99]


def _four_release_manifest() -> pd.DataFrame:
  rows = []
  scenario_id = 1
  for release in ("v1", "v2", "v3", "v4"):
    for cohort in ("positive_auto", "positive_manual", "negative_auto"):
      rows.append({
          "release": release,
          "cohort": cohort,
          "scenario_id": scenario_id,
      })
      scenario_id += 1
  return pd.DataFrame(rows)


def test_finalize_atomically_publishes_only_complete_four_release_matrix(
    tmp_path, monkeypatch):
  manifest = _four_release_manifest()
  manifest_path = tmp_path / "analysis.csv"
  manifest.to_csv(manifest_path, index=False)
  output = tmp_path / "metrics.json"
  scenario_results = [{
      "scenario_id": int(row.scenario_id),
      "sim_triggered": row.cohort != "positive_manual",
  } for row in manifest.itertuples()]
  monkeypatch.setattr(
      "ra_repro_finalize_binary_backtest.inspect_job_configuration",
      lambda job_ids, binary_id, scenario_ids: {
          "gate_passed": True,
          "expected_binary_id": binary_id,
          "expected_scenario_count": len(scenario_ids),
      },
  )
  monkeypatch.setattr(
      "ra_repro_finalize_binary_backtest.validate",
      lambda *args: {
          "is_terminal_and_complete": True,
          "quality": {"gate_passed_so_far": True},
          "scenario_results": scenario_results,
      },
  )

  result = finalize(
      job_ids=[100, 101],
      analysis_manifest_path=manifest_path,
      target_release="v4",
      binary_id=1775147,
      output_path=output,
      token="token",
      allow_partial=False,
  )

  assert result["quality_gate_passed"] is True
  assert result["source_releases"] == ["v1", "v2", "v3", "v4"]
  assert all(item["expected"] == item["evaluated"] == 3
             for item in result["sources"].values())
  payload = json.loads(output.read_text(encoding="utf-8"))
  assert payload["targets"]["v4"] == result
  assert not output.with_suffix(".json.tmp").exists()


def test_finalize_refuses_partial_matrix_without_writing_artifact(
    tmp_path, monkeypatch):
  manifest = _four_release_manifest()
  manifest_path = tmp_path / "analysis.csv"
  manifest.to_csv(manifest_path, index=False)
  output = tmp_path / "metrics.json"
  monkeypatch.setattr(
      "ra_repro_finalize_binary_backtest.inspect_job_configuration",
      lambda job_ids, binary_id, scenario_ids: {"gate_passed": True},
  )
  monkeypatch.setattr(
      "ra_repro_finalize_binary_backtest.validate",
      lambda *args: {
          "is_terminal_and_complete": False,
          "quality": {"gate_passed_so_far": True},
          "scenario_results": [{
              "scenario_id": 1,
              "sim_triggered": True,
          }],
      },
  )

  with pytest.raises(RuntimeError, match="quality gate is not complete"):
    finalize(
        job_ids=[100],
        analysis_manifest_path=manifest_path,
        target_release="v4",
        binary_id=1775147,
        output_path=output,
        token="token",
        allow_partial=False,
    )

  assert not output.exists()
