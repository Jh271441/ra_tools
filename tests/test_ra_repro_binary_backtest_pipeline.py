import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import ra_repro_advance_binary_backtest as advance_module
from scripts import ra_repro_run_binary_backtest_pipeline as pipeline_module

_RUNNING_TASK_DETAILS = advance_module._running_task_details


@pytest.fixture(autouse=True)
def _stub_running_task_details(monkeypatch):
  monkeypatch.setattr(
      advance_module, "_running_task_details", lambda job_ids: [])


def test_four_release_windows_include_target_and_previous_three():
  assert advance_module._window("gen4-release-20260821", 4) == [
      "gen4-release-20260731",
      "gen4-release-20260807",
      "gen4-release-20260814",
      "gen4-release-20260821",
  ]
  assert advance_module._window("gen4-release-20260814", 4) == [
      "gen4-release-20260724",
      "gen4-release-20260731",
      "gen4-release-20260807",
      "gen4-release-20260814",
  ]


def test_running_task_details_reports_elapsed_timeout_and_worker(monkeypatch):
  class TaskAccessor:

    @staticmethod
    def query(query):
      assert query == {"job_id": 100}
      return [{
          "id": 1000002,
          "signature": "38216327",
          "status": 2,
          "task_runs": [{
              "assign_time": "2026-08-30T23:01:47.285Z",
              "timeout_sec": 18000,
              "worker_name": "worker-1",
              "worker_ip": "192.0.2.1",
              "version": 1,
          }],
      }, {
          "id": 1000003,
          "signature": "38216328",
          "status": 3,
      }]

  class OrionTask:
    RUNNING = 2

  class Regions:
    CN = "cn"

  class TrailRegionMgr:

    def __init__(self, region, is_pre):
      assert region == "cn"
      assert is_pre is False

    def __enter__(self):
      return self

    def __exit__(self, *_):
      return None

  class FixedDatetime(datetime):

    @classmethod
    def now(cls, tz=None):
      return cls(2026, 8, 30, 23, 31, 47, 285000,
                 tzinfo=timezone.utc)

  monkeypatch.setattr(
      advance_module,
      "_load_orion_status_api",
      lambda: (TaskAccessor, None, OrionTask, Regions, TrailRegionMgr),
  )
  monkeypatch.setattr(advance_module, "datetime", FixedDatetime)

  assert _RUNNING_TASK_DETAILS([100]) == [{
      "job_id": 100,
      "task_id": 1000002,
      "scenario_id": 38216327,
      "assigned_at": "2026-08-30T23:01:47.285000+00:00",
      "elapsed_seconds": 1800.0,
      "timeout_seconds": 18000,
      "elapsed_fraction_of_timeout": 0.1,
      "worker_name": "worker-1",
      "worker_ip": "192.0.2.1",
      "run_version": 1,
  }]


def test_advance_waits_without_launch_when_valid_job_is_active(
    tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text(json.dumps({
      "valid": {
          "job_id": 100,
          "target_release": "gen4-release-20260821",
          "scenario_count": 90,
      },
      "invalid": {
          "job_id": 99,
          "target_release": "gen4-release-20260821",
          "scenario_count": 90,
          "valid_for_metrics": False,
      },
  }), encoding="utf-8")
  monkeypatch.setattr(
      advance_module,
      "_status_by_job",
      lambda job_ids: {
          100: {"UNASSIGNED": 89, "RUNNING": 1},
      },
  )

  result = advance_module.advance(
      manifest_path=tmp_path / "unused.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result == {
      "action": "wait",
      "active_jobs": [{
          "job_id": 100,
          "status": {"UNASSIGNED": 89, "RUNNING": 1},
      }],
      "running_tasks": [],
  }


def test_advance_stops_on_unresolved_launch_intent(tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text(json.dumps({
      "pending-key": {
          "job_id": None,
          "launch_state": "pending",
          "launch_requested_at": "2026-08-31T00:00:00+00:00",
      }
  }), encoding="utf-8")
  monkeypatch.setattr(
      advance_module,
      "_status_by_job",
      lambda job_ids: (_ for _ in ()).throw(
          AssertionError("must stop before querying jobs")),
  )

  result = advance_module.advance(
      manifest_path=tmp_path / "unused.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result["action"] == "stop"
  assert result["unresolved_launch_intents"][0][
      "registry_key"] == "pending-key"


def test_advance_stops_on_failure_before_treating_job_as_active(
    tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text(json.dumps({
      "valid": {
          "job_id": 100,
          "target_release": "gen4-release-20260821",
          "scenario_count": 90,
      }
  }), encoding="utf-8")
  monkeypatch.setattr(
      advance_module,
      "_status_by_job",
      lambda job_ids: {
          100: {"UNASSIGNED": 88, "RUNNING": 1, "FAILED": 1},
      },
  )
  monkeypatch.setattr(advance_module.time, "sleep", lambda seconds: None)

  result = advance_module.advance(
      manifest_path=tmp_path / "unused.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result["action"] == "stop"
  assert result["anomalous_jobs"][0]["status"]["FAILED"] == 1
  assert result["anomaly_confirmation"]["confirmed"] is True


def test_advance_does_not_stop_on_transient_failed_status(
    tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text(json.dumps({
      "valid": {
          "job_id": 100,
          "target_release": "gen4-release-20260821",
          "scenario_count": 90,
      }
  }), encoding="utf-8")
  observations = iter([
      {100: {"UNASSIGNED": 88, "RUNNING": 0, "FAILED": 1}},
      {100: {"UNASSIGNED": 88, "RUNNING": 1, "FAILED": 0}},
  ])
  monkeypatch.setattr(
      advance_module, "_status_by_job", lambda job_ids: next(observations))
  sleeps = []
  monkeypatch.setattr(
      advance_module.time, "sleep", lambda seconds: sleeps.append(seconds))

  result = advance_module.advance(
      manifest_path=tmp_path / "unused.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result == {
      "action": "wait",
      "active_jobs": [{
          "job_id": 100,
          "status": {"UNASSIGNED": 88, "RUNNING": 1, "FAILED": 0},
      }],
      "running_tasks": [],
  }
  assert sleeps == [5.0]


def test_advance_stops_active_job_on_incremental_quality_failure(
    tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text(json.dumps({
      "valid": {
          "job_id": 100,
          "target_release": "gen4-release-20260821",
          "scenario_count": 90,
          "binary_id": 1775147,
          "selected_manifest": "manifest.csv",
      }
  }), encoding="utf-8")
  status = {"UNASSIGNED": 88, "RUNNING": 1, "COMPLETED": 1}
  monkeypatch.setattr(
      advance_module, "_status_by_job", lambda job_ids: {100: status})

  class Regions:
    CN = "cn"

  monkeypatch.setattr(
      advance_module,
      "_load_orion_status_api",
      lambda: (None, lambda *_: "token", None, Regions, None),
  )
  monkeypatch.setattr(
      advance_module,
      "_validate_entry",
      lambda entry, token: {
          "job_id": 100,
          "incremental_gate_passed": False,
          "quality": {"simulator_cache_hits": 1},
      },
  )

  result = advance_module.advance(
      manifest_path=tmp_path / "unused.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result["action"] == "stop"
  assert result["reason"] == "active job failed incremental quality gate"
  assert result["anomalous_jobs"] == [{
      "job_id": 100,
      "status": status,
      "validation": {
          "job_id": 100,
          "incremental_gate_passed": False,
          "quality": {"simulator_cache_hits": 1},
      },
  }]


def test_validate_entry_rejects_terminal_result_with_manifest_count_mismatch(
    tmp_path, monkeypatch):
  manifest = tmp_path / "manifest.csv"
  pd.DataFrame({"scenario_id": range(90)}).to_csv(manifest, index=False)
  monkeypatch.setattr(
      advance_module,
      "inspect_job_configuration",
      lambda job_ids, binary_id, scenario_ids: {
          "gate_passed": True,
          "expected_scenario_count": len(scenario_ids),
      },
  )
  monkeypatch.setattr(
      advance_module,
      "validate",
      lambda job_ids, manifest_path, output_path, token: {
          "is_terminal_and_complete": True,
          "manifest_rows": 89,
          "quality": {"gate_passed_so_far": True},
          "completed": 89,
          "terminal_failed": 0,
          "mean_completed_duration_seconds": 1200.0,
          "median_completed_duration_seconds": 900.0,
          "p90_completed_duration_seconds": 1800.0,
          "p95_completed_duration_seconds": 2100.0,
          "max_completed_duration_seconds": 2400.0,
          "estimated_remaining_hours_at_concurrency_1": 0.3333333333,
          "completed_missing_dpe": 0,
          "completed_pending_dpe_grace": 0,
      },
  )

  result = advance_module._validate_entry({
      "job_id": 100,
      "binary_id": 1775147,
      "selected_manifest": str(manifest),
      "scenario_count": 90,
  }, "token")

  assert result["passed"] is False
  assert result["incremental_gate_passed"] is False
  assert result["manifest_matches_expected"] is False
  assert result["manifest_rows"] == 89
  assert result["expected_manifest_rows"] == 90
  assert result["mean_completed_duration_seconds"] == 1200.0
  assert result["median_completed_duration_seconds"] == 900.0
  assert result["p90_completed_duration_seconds"] == 1800.0
  assert result["p95_completed_duration_seconds"] == 2100.0
  assert result["max_completed_duration_seconds"] == 2400.0
  assert result["estimated_remaining_hours_at_concurrency_1"] == pytest.approx(
      1 / 3)


def test_advance_refreshes_status_after_incremental_validation(
    tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text(json.dumps({
      "valid": {
          "job_id": 100,
          "target_release": "gen4-release-20260821",
          "scenario_count": 90,
          "binary_id": 1775147,
          "selected_manifest": "manifest.csv",
      }
  }), encoding="utf-8")
  observations = iter([
      {100: {"UNASSIGNED": 81, "RUNNING": 1, "COMPLETED": 8}},
      {100: {"UNASSIGNED": 80, "RUNNING": 1, "COMPLETED": 9}},
  ])
  monkeypatch.setattr(
      advance_module, "_status_by_job", lambda job_ids: next(observations))

  class Regions:
    CN = "cn"

  monkeypatch.setattr(
      advance_module,
      "_load_orion_status_api",
      lambda: (None, lambda *_: "token", None, Regions, None),
  )
  checked = {
      "job_id": 100,
      "incremental_gate_passed": True,
      "completed": 9,
  }
  monkeypatch.setattr(
      advance_module, "_validate_entry", lambda entry, token: checked)

  result = advance_module.advance(
      manifest_path=tmp_path / "unused.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result == {
      "action": "wait",
      "active_jobs": [{
          "job_id": 100,
          "status": {"UNASSIGNED": 80, "RUNNING": 1, "COMPLETED": 9},
      }],
      "running_tasks": [],
      "incremental_validations": [checked],
  }


def test_advance_launches_only_missing_diagonal_after_cross_job_passes(
    tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text(json.dumps({
      "cross": {
          "job_id": 100,
          "target_release": "gen4-release-20260821",
          "source_releases": [
              "gen4-release-20260731",
              "gen4-release-20260807",
              "gen4-release-20260814",
          ],
          "scenario_count": 90,
          "sample_per_cohort": 10,
          "seed": "seed",
      }
  }), encoding="utf-8")
  monkeypatch.setattr(
      advance_module,
      "_status_by_job",
      lambda job_ids: {100: {"COMPLETED": 90}},
  )

  class Regions:
    CN = "cn"

  monkeypatch.setattr(
      advance_module,
      "_load_orion_status_api",
      lambda: (None, lambda *_: "token", None, Regions, None),
  )
  monkeypatch.setattr(
      advance_module,
      "_validate_entry",
      lambda entry, token: {"job_id": 100, "passed": True},
  )
  launches = []

  def launch(**kwargs):
    launches.append(kwargs)
    return {"job_id": 101}

  monkeypatch.setattr(advance_module, "build_and_maybe_launch", launch)

  result = advance_module.advance(
      manifest_path=tmp_path / "full.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result["action"] == "launch"
  assert result["already_covered"] == [
      "gen4-release-20260731",
      "gen4-release-20260807",
      "gen4-release-20260814",
  ]
  assert result["missing_releases"] == ["gen4-release-20260821"]
  assert len(launches) == 1
  assert launches[0]["source_releases"] == ["gen4-release-20260821"]
  assert launches[0]["max_concurrency"] == 1
  assert launches[0]["execute"] is True


def test_advance_finalizes_four_release_target_after_both_jobs_pass(
    tmp_path, monkeypatch):
  monkeypatch.chdir(tmp_path)
  registry = tmp_path / "jobs.json"
  common = {
      "target_release": "gen4-release-20260821",
      "sample_per_cohort": 10,
      "seed": "seed",
      "binary_id": 1775147,
  }
  registry.write_text(json.dumps({
      "cross": {
          **common,
          "job_id": 100,
          "source_releases": [
              "gen4-release-20260731",
              "gen4-release-20260807",
              "gen4-release-20260814",
          ],
          "scenario_count": 90,
      },
      "diagonal": {
          **common,
          "job_id": 101,
          "source_releases": ["gen4-release-20260821"],
          "scenario_count": 30,
      },
  }), encoding="utf-8")
  monkeypatch.setattr(
      advance_module,
      "_status_by_job",
      lambda job_ids: {
          100: {"COMPLETED": 90},
          101: {"COMPLETED": 30},
      },
  )

  class Regions:
    CN = "cn"

  monkeypatch.setattr(
      advance_module,
      "_load_orion_status_api",
      lambda: (None, lambda *_: "token", None, Regions, None),
  )
  monkeypatch.setattr(
      advance_module,
      "_validate_entry",
      lambda entry, token: {
          "job_id": entry["job_id"],
          "passed": True,
      },
  )
  manifest = pd.DataFrame({
      "scenario_id": range(120),
      "cohort": ["positive_auto"] * 120,
      "release": ["gen4-release-20260821"] * 120,
  })
  monkeypatch.setattr(
      advance_module, "select_manifest", lambda *args: (manifest.copy(), {}))
  finalized = []

  def finalize(**kwargs):
    finalized.append(kwargs)
    return {"quality_gate_passed": True}

  monkeypatch.setattr(advance_module, "finalize", finalize)

  result = advance_module.advance(
      manifest_path=tmp_path / "full.csv",
      registry_path=registry,
      metrics_path=tmp_path / "metrics.json",
      target_release="gen4-release-20260821",
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result["action"] == "finalize"
  assert result["desired_window"] == [
      "gen4-release-20260731",
      "gen4-release-20260807",
      "gen4-release-20260814",
      "gen4-release-20260821",
  ]
  assert result["job_ids"] == [100, 101]
  assert len(finalized) == 1
  assert finalized[0]["job_ids"] == [100, 101]
  assert finalized[0]["target_release"] == "gen4-release-20260821"
  assert finalized[0]["binary_id"] == 1775147
  assert finalized[0]["allow_partial"] is False


def test_advance_moves_to_previous_window_after_latest_target_is_published(
    tmp_path, monkeypatch):
  registry = tmp_path / "jobs.json"
  registry.write_text("{}", encoding="utf-8")
  metrics = tmp_path / "metrics.json"
  metrics.write_text(json.dumps({
      "targets": {
          "gen4-release-20260821": {"quality_gate_passed": True},
      },
  }), encoding="utf-8")
  monkeypatch.setattr(advance_module, "_status_by_job", lambda job_ids: {})

  class Regions:
    CN = "cn"

  monkeypatch.setattr(
      advance_module,
      "_load_orion_status_api",
      lambda: (None, lambda *_: "token", None, Regions, None),
  )
  launches = []

  def launch(**kwargs):
    launches.append(kwargs)
    return {"job_id": 102}

  monkeypatch.setattr(advance_module, "build_and_maybe_launch", launch)

  result = advance_module.advance(
      manifest_path=tmp_path / "full.csv",
      registry_path=registry,
      metrics_path=metrics,
      target_release=None,
      window_size=4,
      sample_per_cohort=10,
      seed="seed",
      execute=True,
      token=None,
  )

  assert result["action"] == "launch"
  assert result["target_release"] == "gen4-release-20260814"
  assert result["missing_releases"] == [
      "gen4-release-20260724",
      "gen4-release-20260731",
      "gen4-release-20260807",
      "gen4-release-20260814",
  ]
  assert launches[0]["target_release"] == "gen4-release-20260814"
  assert launches[0]["source_releases"] == result["missing_releases"]


def test_dashboard_refresh_stamp_written_only_after_completion(
    tmp_path, monkeypatch):
  metrics = tmp_path / "metrics.json"
  stamp = tmp_path / "stamp.json"
  metrics.write_text(json.dumps({
      "generated_at": "2026-08-31T00:00:00+00:00",
      "targets": {},
  }), encoding="utf-8")

  class Response:
    def __init__(self, payload):
      self._payload = payload

    def raise_for_status(self):
      return None

    def json(self):
      return self._payload

  monkeypatch.setattr(
      pipeline_module.requests,
      "post",
      lambda *args, **kwargs: Response({"job_id": "refresh-1"}),
  )
  monkeypatch.setattr(
      pipeline_module.requests,
      "get",
      lambda *args, **kwargs: Response({"status": "completed"}),
  )

  result = pipeline_module._refresh_dashboard_if_needed(
      metrics, stamp, "http://dashboard/api")

  assert result["generated_at"] == "2026-08-31T00:00:00+00:00"
  assert result["refresh_job_id"] == "refresh-1"
  assert json.loads(stamp.read_text(encoding="utf-8"))[
      "generated_at"] == "2026-08-31T00:00:00+00:00"
  assert pipeline_module._refresh_dashboard_if_needed(
      metrics, stamp, "http://dashboard/api") is None


def test_dashboard_refresh_tracks_online_artifact_without_binary_metrics(
    tmp_path, monkeypatch):
  binary_metrics = tmp_path / "missing-binary.json"
  online_metrics = tmp_path / "online.json"
  stamp = tmp_path / "stamp.json"
  online_metrics.write_text(json.dumps({
      "generated_at": "2026-08-31T01:18:00+00:00",
      "releases": {},
  }), encoding="utf-8")

  class Response:
    def __init__(self, payload):
      self._payload = payload

    def raise_for_status(self):
      return None

    def json(self):
      return self._payload

  monkeypatch.setattr(
      pipeline_module.requests,
      "post",
      lambda *args, **kwargs: Response({"job_id": "refresh-online"}),
  )
  monkeypatch.setattr(
      pipeline_module.requests,
      "get",
      lambda *args, **kwargs: Response({"status": "completed"}),
  )

  result = pipeline_module._refresh_dashboard_if_needed(
      binary_metrics,
      stamp,
      "http://dashboard/api",
      online_metrics,
  )

  assert result["artifact_generations"] == {
      "online_metrics": "2026-08-31T01:18:00+00:00",
  }
  assert pipeline_module._refresh_dashboard_if_needed(
      binary_metrics,
      stamp,
      "http://dashboard/api",
      online_metrics,
  ) is None


def test_dashboard_refresh_failure_is_audited_without_raising(
    tmp_path, monkeypatch):
  monkeypatch.setattr(
      pipeline_module,
      "_refresh_dashboard_if_needed",
      lambda *args: (_ for _ in ()).throw(ConnectionError("dashboard down")),
  )

  refreshed, error = pipeline_module._attempt_dashboard_refresh(
      tmp_path / "metrics.json",
      tmp_path / "stamp.json",
      "http://dashboard/api",
  )

  assert refreshed is None
  assert error["action"] == "dashboard_refresh_error"
  assert "dashboard down" in error["error"]
  assert "ConnectionError" in error["traceback"]


def test_pipeline_audit_log_is_jsonl(tmp_path, capsys):
  path = tmp_path / "audit" / "pipeline.jsonl"

  pipeline_module._emit({"action": "wait", "completed": 3}, path)
  pipeline_module._emit({"action": "launch", "job_id": 101}, path)

  rows = [json.loads(line) for line in path.read_text(
      encoding="utf-8").splitlines()]
  assert rows == [
      {"action": "wait", "completed": 3},
      {"action": "launch", "job_id": 101},
  ]
  assert '"action": "launch"' in capsys.readouterr().out


def test_parse_task_profile_annotations_keeps_execution_stages():
  html = """
  {"text": "unrelated", "x": "2026-08-31T00:00:00", "y": 1.0,
   "yref": "paper"}
  {"text": "Waiting COMPUTING<br>Running simulation",
   "x": "2026-08-31T00:01:00", "y": 1.0, "yref": "paper"}
  {"text": "Result evaluation", "x": "2026-08-31T00:02:00",
   "y": 1.0, "yref": "paper"}
  {"text": "__exit__<br>__end__", "x": "2026-08-31T00:03:00",
   "y": 1.0, "yref": "paper"}
  {"text": "__exit__<br>__end__", "x": "2026-08-31T00:03:00",
   "y": 1.0, "yref": "paper"}
  """

  assert pipeline_module._parse_task_profile_annotations(html) == [{
      "timestamp": "2026-08-31T00:01:00",
      "stage": "Waiting COMPUTING / Running simulation",
  }, {
      "timestamp": "2026-08-31T00:02:00",
      "stage": "Result evaluation",
  }, {
      "timestamp": "2026-08-31T00:03:00",
      "stage": "__exit__ / __end__",
  }]


def test_enrich_long_running_tasks_is_thresholded_and_best_effort(monkeypatch):
  calls = []

  def fetch(task_id):
    calls.append(task_id)
    if task_id == 2:
      raise ConnectionError("profile unavailable")
    return {"latest_stage": {"stage": "Running simulation"}}

  monkeypatch.setattr(pipeline_module, "_fetch_task_profile_summary", fetch)
  result = {
      "running_tasks": [{
          "task_id": 1,
          "elapsed_seconds": 1799,
      }, {
          "task_id": 2,
          "elapsed_seconds": 1800,
      }, {
          "task_id": 3,
          "elapsed_seconds": 1900,
      }],
  }

  pipeline_module._enrich_long_running_tasks(result, 1800)

  assert calls == [2, 3]
  assert "live_profile" not in result["running_tasks"][0]
  assert "profile unavailable" in result["running_tasks"][1][
      "live_profile_error"]
  assert result["running_tasks"][2]["live_profile"]["latest_stage"] == {
      "stage": "Running simulation",
  }


def test_cancel_anomalous_jobs_only_cancels_jobs_with_remaining_work(
    monkeypatch):
  calls = []

  class Response:
    is_success = True

  def cancel(region, job_ids, is_async, override_token):
    calls.append((region, job_ids, is_async, override_token))
    return Response()

  import types
  proxy_module = types.ModuleType("orion_client.api.proxy_client")
  proxy_module.cancel_orion_job_through_proxy = cancel
  config_module = types.ModuleType("orion_client.utils.config_utils")
  config_module.get_auth_token = lambda _, __: "token"
  regions_module = types.ModuleType("voy_data_utils.regions")

  class Regions:
    CN = "cn"

  regions_module.Regions = Regions
  monkeypatch.setitem(sys.modules, "orion_client.api.proxy_client", proxy_module)
  monkeypatch.setitem(sys.modules, "orion_client.utils.config_utils", config_module)
  monkeypatch.setitem(sys.modules, "voy_data_utils.regions", regions_module)

  result = pipeline_module._cancel_anomalous_jobs({
      "anomalous_jobs": [
          {
              "job_id": 102,
              "status": {"COMPLETED": 89, "FAILED": 1},
          },
          {
              "job_id": 101,
              "status": {"UNASSIGNED": 8, "RUNNING": 1, "FAILED": 1},
          },
          {
              "job_id": 101,
              "status": {"UNASSIGNED": 8, "RUNNING": 1, "FAILED": 1},
          },
      ],
  })

  assert result["action"] == "cancel_anomalous_jobs"
  assert result["job_ids"] == [101]
  assert calls == [("cn", [101], False, "token")]


def test_cancel_anomalous_jobs_is_noop_when_all_work_is_terminal(monkeypatch):
  result = pipeline_module._cancel_anomalous_jobs({
      "anomalous_jobs": [{
          "job_id": 102,
          "status": {"COMPLETED": 89, "FAILED": 1},
      }],
  })

  assert result is None
