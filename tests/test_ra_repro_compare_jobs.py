import pandas as pd

from scripts.ra_repro_compare_jobs import _summarize_overlap


def test_summarize_overlap_reports_cohort_disagreement():
  overlap = pd.DataFrame([
      {
          "issue_id": "cn1",
          "cohort": "positive_auto",
          "scenario_id_current": 1,
          "scenario_id_reference": 11,
          "triggered_current": True,
          "triggered_reference": True,
      },
      {
          "issue_id": "cn2",
          "cohort": "negative_auto",
          "scenario_id_current": 2,
          "scenario_id_reference": 12,
          "triggered_current": False,
          "triggered_reference": True,
      },
  ])

  result = _summarize_overlap(overlap, 32, 200, 100)

  assert result["exact_segment_overlap_possible"] == 32
  assert result["evaluated_overlap"] == 2
  assert result["agreements"] == 1
  assert result["disagreements"] == 1
  assert result["agreement_rate"] == 0.5
  assert result["cohorts"]["negative_auto"]["agreement_rate"] == 0.0
  assert result["conflicts"][0]["issue_id"] == "cn2"
