import pandas as pd
import pytest

from scripts.ra_repro_validate_orion import (
    _load_manifest,
    _post_orion_query,
    _query_orion,
    _query_results_by_task_ids,
    _select_scenario_results,
    _summarize,
    validate,
)


class _Response:

  def __init__(self, status_code, payload=None):
    self.status_code = status_code
    self._payload = payload

  def raise_for_status(self):
    if self.status_code >= 400:
      response = type("HttpResponse", (), {"status_code": self.status_code})()
      raise __import__("requests").HTTPError(response=response)

  def json(self):
    return self._payload


def test_orion_query_retries_transient_gateway_failure(monkeypatch):
  responses = iter([_Response(502), _Response(200)])
  calls = []
  monkeypatch.setattr(
      "scripts.ra_repro_validate_orion.requests.post",
      lambda *args, **kwargs: calls.append((args, kwargs)) or next(responses))
  monkeypatch.setattr("scripts.ra_repro_validate_orion.time.sleep",
                      lambda seconds: None)

  response = _post_orion_query({"job_id": "123"}, "token")

  assert response.status_code == 200
  assert len(calls) == 2


def test_task_id_fallback_requires_complete_exact_batches(monkeypatch):
  light_tasks = [{"id": task_id} for task_id in range(1, 24)]
  monkeypatch.setattr(
      "scripts.ra_repro_validate_orion._query_pages",
      lambda params, token, page_size: light_tasks)

  def post(data, token):
    ids = [int(task_id) for task_id in data["id"].split(",")]
    return _Response(200, {
        "code": 0,
        "data": {"res": [{"id": task_id} for task_id in reversed(ids)]},
    })

  monkeypatch.setattr(
      "scripts.ra_repro_validate_orion._post_orion_query", post)

  rows = _query_results_by_task_ids(123, "token")

  assert {row["id"] for row in rows} == set(range(1, 24))


def test_query_orion_audits_prior_dpe_oom_retry(monkeypatch):
  task = {
      "id": 10,
      "signature": "123",
      "status": 2,
      "update_time": "2026-08-31T00:00:00Z",
      "task_runs": [
          {
              "status": 4,
              "outcome": "DPE exceeded memory quota of 24576 MB",
              "outcome_detail": "Running DPE failed",
              "duration_time": 589,
              "result": {},
          },
          {
              "status": 2,
              "outcome": "",
              "outcome_detail": "",
              "duration_time": 0,
              "result": {},
          },
      ],
  }
  monkeypatch.setattr(
      "scripts.ra_repro_validate_orion._query_pages",
      lambda *args: [task],
  )

  row = _query_orion(100, "token").iloc[0]

  assert row["task_retry_count"] == 1
  assert row["prior_failed_task_run_count"] == 1
  assert row["prior_dpe_oom_task_run_count"] == 1


def _row(cohort, metric, *, outcome="Done with warnings", cache_hit=False):
  return {
      "scenario_id": hash(cohort) % 100000,
      "cohort": cohort,
      "task_status": 3,
      "task_outcome": outcome,
      "task_duration_seconds": 600,
      "task_update_time": "2026-01-01T00:00:00Z",
      "simulator_cache_hit": cache_hit,
      "inference_log_count": 1,
      "dpe_output_count": 1,
      "output_bag_count": 1,
      "failed_evaluation_count": 0,
      "warning_count": 1,
      "unexpected_warning_count": 0,
      "dpe_assist_channel_triggered__group1": metric,
  }


def test_summarize_separates_road_behavior_from_truth():
  rows = [
      _row("positive_auto", 1),
      _row("negative_auto", -1),
      _row("positive_manual", -1),
  ]

  result = _summarize(pd.DataFrame(rows), job_id=123)

  assert result["is_terminal_and_complete"] is True
  assert result["completed"] == 3
  assert result["completed_missing_dpe"] == 0
  assert result["terminal_dpe_covered"] == 3
  assert result["completed_dpe_covered"] == 3
  assert result["quality"]["tasks_with_warnings"] == 3
  assert result["quality"]["gate_passed_so_far"] is True

  assert result["cohorts"]["positive_auto"]["road_behavior_matches"] == 1
  assert result["cohorts"]["negative_auto"]["road_behavior_matches"] == 0
  assert result["cohorts"]["positive_manual"]["road_behavior_matches"] == 1

  assert result["truth"] == {
      "tp": 1,
      "fn": 1,
      "fp": 0,
      "tn": 1,
      "precision": 1.0,
      "recall": 0.5,
      "specificity": 1.0,
      "accuracy": 2 / 3,
  }


def test_summarize_rejects_simulator_cache_hit():
  row = _row("positive_auto", 1, cache_hit=True)

  result = _summarize(pd.DataFrame([row]), job_id=123)

  assert result["quality"]["simulator_cache_hits"] == 1
  assert result["quality"]["gate_passed_so_far"] is False
  assert result["is_terminal_and_complete"] is False


def test_summarize_rejects_completed_result_without_dpe():
  row = _row("positive_auto", None)

  result = _summarize(pd.DataFrame([row]), job_id=123)

  assert result["completed_missing_dpe"] == 1
  assert result["completed_missing_dpe_scenario_ids"] == [
      row["scenario_id"]]
  assert result["quality"]["gate_passed_so_far"] is False
  assert result["is_terminal_and_complete"] is False


def test_summarize_reports_recent_completed_result_in_dpe_grace():
  row = _row("positive_auto", None)
  row["task_update_time"] = pd.Timestamp.now(tz="UTC").isoformat()

  result = _summarize(pd.DataFrame([row]), job_id=123)

  assert result["completed_missing_dpe"] == 0
  assert result["completed_pending_dpe_grace"] == 1
  assert result["completed_pending_dpe_grace_scenario_ids"] == [
      row["scenario_id"]]
  assert result["quality"]["gate_passed_so_far"] is True
  assert result["is_terminal_and_complete"] is False


def test_summarize_reports_retries_without_failing_clean_final_result():
  row = _row("positive_auto", 1)
  row.update({
      "task_retry_count": 1,
      "prior_failed_task_run_count": 1,
      "prior_dpe_oom_task_run_count": 1,
  })

  result = _summarize(pd.DataFrame([row]), job_id=123)

  assert result["quality"]["tasks_retried"] == 1
  assert result["quality"]["retry_attempts"] == 1
  assert result["quality"]["prior_failed_task_runs"] == 1
  assert result["quality"]["prior_dpe_oom_task_runs"] == 1
  assert result["quality"]["retried_scenario_ids"] == [row["scenario_id"]]
  assert result["quality"]["prior_dpe_oom_scenario_ids"] == [
      row["scenario_id"]]
  assert result["quality"]["gate_passed_so_far"] is True
  assert result["is_terminal_and_complete"] is True


def test_summarize_counts_failed_and_cancelled_as_terminal_failures():
  failed = _row("positive_auto", None, outcome="Simulation failed")
  failed["task_status"] = 4
  cancelled = _row("negative_auto", None, outcome="Cancelled")
  cancelled["task_status"] = 5

  result = _summarize(pd.DataFrame([failed, cancelled]), job_id=123)

  assert result["terminal"] == 2
  assert result["completed"] == 0
  assert result["terminal_failed"] == 2
  assert result["terminal_failed_scenario_ids"] == sorted(
      [failed["scenario_id"], cancelled["scenario_id"]])
  assert result["quality"]["gate_passed_so_far"] is False
  assert result["is_terminal_and_complete"] is False


def test_select_scenario_results_prefers_completed_dpe_across_jobs():
  pending = _row("positive_auto", None, outcome="")
  pending.update({
      "scenario_id": 7,
      "source_job_id": 101,
      "task_status": 1,
      "task_update_time": "2026-08-29 10:00:00",
  })
  completed = _row("positive_auto", 1)
  completed.update({
      "scenario_id": 7,
      "source_job_id": 102,
      "task_update_time": "2026-08-29 11:00:00",
  })

  selected, conflicts = _select_scenario_results(
      pd.DataFrame([pending, completed]))

  assert len(selected) == 1
  assert selected.iloc[0]["source_job_id"] == 102
  assert conflicts == []


def test_select_scenario_results_flags_conflicting_completed_runs():
  first = _row("negative_auto", -1)
  first.update({
      "scenario_id": 8,
      "source_job_id": 101,
      "task_update_time": "2026-08-29 10:00:00",
  })
  second = _row("negative_auto", 1)
  second.update({
      "scenario_id": 8,
      "source_job_id": 102,
      "task_update_time": "2026-08-29 11:00:00",
  })

  _, conflicts = _select_scenario_results(pd.DataFrame([first, second]))

  assert conflicts == [{
      "scenario_id": 8,
      "job_ids": [101, 102],
      "trigger_values": [False, True],
  }]


def test_select_scenario_results_prefers_fresh_over_newer_cache_hit():
  fresh = _row("positive_auto", 1)
  fresh.update({
      "scenario_id": 9,
      "source_job_id": 101,
      "task_update_time": "2026-08-29 10:00:00",
  })
  cached = _row("positive_auto", 1, cache_hit=True)
  cached.update({
      "scenario_id": 9,
      "source_job_id": 102,
      "task_update_time": "2026-08-29 11:00:00",
      "inference_log_count": 0,
  })

  selected, conflicts = _select_scenario_results(pd.DataFrame([fresh, cached]))

  assert selected.iloc[0]["source_job_id"] == 101
  assert conflicts == []


def test_load_manifest_excludes_only_explicit_nonretryable_upload_losses(
    tmp_path):
  path = tmp_path / "manifest.csv"
  pd.DataFrame([
      {
          "release": "gen4-release-20260710",
          "scenario_id": 1,
          "issue_id": "cn1",
          "cohort": "positive_auto",
          "upload_status": "uploaded",
          "validation_error": "",
      },
      {
          "release": "gen4-release-20260710",
          "scenario_id": None,
          "issue_id": "cn2",
          "cohort": "negative_auto",
          "upload_status": "failed: trip segment does not have bags",
          "validation_error": "",
      },
      {
          "release": "gen4-release-20260710",
          "scenario_id": None,
          "issue_id": "cn3",
          "cohort": "positive_manual",
          "upload_status": "failed:trip_id(x) does not exist",
          "validation_error": "",
      },
  ]).to_csv(path, index=False)

  manifest = _load_manifest(path, "gen4-release-20260710")

  assert manifest["scenario_id"].tolist() == [1]
  assert manifest.attrs["audit"] == {
      "source_rows": 3,
      "submitted_rows": 1,
      "excluded_rows": 2,
      "exclusions": {"no_bag": 1, "missing_trip": 1},
  }


def test_load_manifest_rejects_retryable_or_unknown_upload_failure(tmp_path):
  path = tmp_path / "manifest.csv"
  pd.DataFrame([{
      "release": "gen4-release-20260710",
      "scenario_id": None,
      "issue_id": "cn1",
      "cohort": "positive_auto",
      "upload_status": "failed:timeout",
      "validation_error": "",
  }]).to_csv(path, index=False)

  with pytest.raises(ValueError, match="unusable upload statuses"):
    _load_manifest(path, "gen4-release-20260710")


def test_validate_rejects_manifest_with_zero_job_scenario_overlap(
    tmp_path, monkeypatch):
  path = tmp_path / "manifest.csv"
  pd.DataFrame([{
      "release": "gen4-release-20260710",
      "scenario_id": 1,
      "issue_id": "cn1",
      "cohort": "positive_auto",
  }]).to_csv(path, index=False)

  task = _row("positive_auto", 1)
  task.update({
      "scenario_id": 2,
      "source_job_id": 123,
      "task_id": 123000001,
  })
  task.pop("dpe_assist_channel_triggered__group1")
  monkeypatch.setattr(
      "scripts.ra_repro_validate_orion._query_orion",
      lambda job_id, token: pd.DataFrame([task]),
  )

  class Client:

    def query_all_pages(self, *args, **kwargs):
      return pd.DataFrame({
          "scenario_id": [2],
          "dpe_assist_channel_triggered__group1": [1],
      })

  monkeypatch.setattr(
      "scripts.ra_repro_validate_orion.SimResultClient", Client)

  with pytest.raises(ValueError, match="zero matching scenario ids"):
    validate([123], path, None, "token")
