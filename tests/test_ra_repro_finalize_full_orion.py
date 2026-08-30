from copy import deepcopy

from scripts.ra_repro_finalize_full_orion import _markdown, _overall


def _result(*, evaluated, road_matches, truth, complete=True):
  cohorts = {}
  for cohort in ("positive_auto", "negative_auto", "positive_manual"):
    count = evaluated[cohort]
    matches = road_matches[cohort]
    cohorts[cohort] = {
        "evaluated": count,
        "triggered": matches,
        "not_triggered": count - matches,
        "road_behavior_matches": matches,
        "road_behavior_reproduction": matches / count if count else None,
    }
  return {
      "manifest_audit": {
          "source_rows": sum(evaluated.values()),
          "submitted_rows": sum(evaluated.values()),
          "excluded_rows": 0,
      },
      "completed": sum(evaluated.values()),
      "terminal_failed": 0,
      "completed_dpe_covered": sum(evaluated.values()),
      "completed_missing_dpe": 0,
      "completed_pending_dpe_grace": 0,
      "cohorts": cohorts,
      "truth": truth,
      "quality": {
          "simulator_cache_hits": 0,
          "simulator_cache_field_missing": 0,
          "inference_log_missing": 0,
          "dpe_output_missing": 0,
          "output_bag_missing": 0,
          "failed_evaluations": 0,
          "tasks_with_warnings": sum(evaluated.values()),
          "tasks_with_unexpected_warnings": 0,
          "gate_passed_so_far": True,
      },
      "is_terminal_and_complete": complete,
  }


def test_overall_uses_weighted_counts_not_mean_of_release_rates():
  small = _result(
      evaluated={
          "positive_auto": 1,
          "negative_auto": 1,
          "positive_manual": 1,
      },
      road_matches={
          "positive_auto": 1,
          "negative_auto": 1,
          "positive_manual": 1,
      },
      truth={"tp": 2, "fn": 0, "fp": 1, "tn": 0},
  )
  large = _result(
      evaluated={
          "positive_auto": 9,
          "negative_auto": 9,
          "positive_manual": 9,
      },
      road_matches={
          "positive_auto": 0,
          "negative_auto": 0,
          "positive_manual": 0,
      },
      truth={"tp": 0, "fn": 18, "fp": 0, "tn": 9},
  )

  overall = _overall({"small": small, "large": large})

  assert overall["cohorts"]["positive_auto"][
      "road_behavior_reproduction"] == 0.1
  assert overall["cohorts"]["negative_auto"][
      "road_behavior_reproduction"] == 0.1
  assert overall["truth"]["precision"] == 2 / 3
  assert overall["truth"]["recall"] == 0.1
  assert overall["truth"]["specificity"] == 0.9
  assert overall["truth"]["accuracy"] == 11 / 30
  assert overall["all_terminal_and_complete"] is True


def test_overall_and_markdown_surface_incomplete_quality_gate():
  result = _result(
      evaluated={
          "positive_auto": 1,
          "negative_auto": 1,
          "positive_manual": 1,
      },
      road_matches={
          "positive_auto": 1,
          "negative_auto": 1,
          "positive_manual": 1,
      },
      truth={"tp": 2, "fn": 0, "fp": 1, "tn": 0},
      complete=False,
  )
  result = deepcopy(result)
  result["quality"]["simulator_cache_hits"] = 1
  result["quality"]["gate_passed_so_far"] = False
  overall = _overall({"release": result})
  row = {
      "release": "release",
      "job_id": 1,
      "completed": 3,
      "submitted_rows": 3,
      "completed_dpe_covered": 3,
      "positive_auto_road_reproduction": 1.0,
      "negative_auto_road_reproduction": 1.0,
      "positive_manual_road_reproduction": 1.0,
      "truth_precision": 2 / 3,
      "truth_recall": 1.0,
      "truth_specificity": 0.0,
      "truth_accuracy": 2 / 3,
      "quality_gate_passed_so_far": False,
      "terminal_and_complete": False,
  }

  markdown = _markdown([row], overall)

  assert overall["quality"]["simulator_cache_hits"] == 1
  assert overall["all_quality_gates_passed_so_far"] is False
  assert overall["all_tasks_terminal"] is True
  assert "Report state: **FINAL_WITH_QUALITY_FAILURES**" in markdown
  assert "cache hits 1" in markdown


def test_markdown_stays_provisional_while_submitted_task_is_not_terminal():
  result = _result(
      evaluated={
          "positive_auto": 1,
          "negative_auto": 1,
          "positive_manual": 1,
      },
      road_matches={
          "positive_auto": 1,
          "negative_auto": 1,
          "positive_manual": 1,
      },
      truth={"tp": 2, "fn": 0, "fp": 1, "tn": 0},
      complete=False,
  )
  result["manifest_audit"]["source_rows"] = 4
  result["manifest_audit"]["submitted_rows"] = 4
  overall = _overall({"release": result})

  assert overall["all_tasks_terminal"] is False
  assert overall["report_state"] == "PROVISIONAL"
