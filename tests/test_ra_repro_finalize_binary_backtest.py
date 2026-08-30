from pathlib import Path
import sys

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ra_repro_finalize_binary_backtest import (
    INDEPENDENT_REPLAY_FLAG,
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
      "tasks": [{"task_args": valid_args.copy()} for _ in range(3)],
  }]

  summary = summarize_job_configuration(jobs, 1775147)

  assert summary["gate_passed"] is True
  assert summary["task_count"] == 3

  jobs[0]["tasks"][1]["task_args"].pop("--enable-dpe")
  jobs[0]["tasks"][2]["task_args"]["--sim-exec-args"] = "--sim_aligned_mode"
  summary = summarize_job_configuration(jobs, 1775147)

  assert summary["gate_passed"] is False
  assert summary["dpe_disabled"] == 1
  assert summary["independent_replay_missing"] == 1
