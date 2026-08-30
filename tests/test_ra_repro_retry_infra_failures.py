import json

from scripts import ra_repro_retry_infra_failures as retry_module


def test_execute_batches_multiple_tasks_for_same_job(monkeypatch, tmp_path):
  calls = []
  tasks = {
      101: {
          "id": 101,
          "signature": 201,
          "status": 4,
          "outcome": "Executor script returned 135",
      },
      102: {
          "id": 102,
          "signature": 202,
          "status": 4,
          "outcome": "Disk quota exceeded",
      },
  }

  class FakeJobAccessor:
    @staticmethod
    def get(job_id):
      assert job_id == 7
      return {"state": 3}

  class FakeTaskAccessor:
    @staticmethod
    def query(query):
      return [tasks[query["id"]]]

  class FakeResponse:
    is_success = True
    message = "accepted"

  def fake_retry_job_impl(**kwargs):
    calls.append(kwargs)
    return FakeResponse()

  class FakeOrionJob:
    class State:
      @staticmethod
      def Name(_):
        return "COMPLETED"

  class FakeOrionTask:
    class Status:
      @staticmethod
      def Name(_):
        return "FAILED"

  class FakeRegions:
    CN = "CN"

  class FakeTrailRegionMgr:
    def __init__(self, *_args, **_kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *_args):
      return False

  monkeypatch.setattr(
      retry_module,
      "_load_api",
      lambda: (FakeJobAccessor, FakeTaskAccessor, fake_retry_job_impl,
               lambda *_args: "token", FakeOrionJob, FakeOrionTask,
               FakeRegions, FakeTrailRegionMgr),
  )

  ledger_path = tmp_path / "ledger.json"
  ledger_path.write_text(
      json.dumps({
          "101": {"job_id": 7, "task_id": 101, "scenario_id": 201},
          "102": {"job_id": 7, "task_id": 102, "scenario_id": 202},
      }),
      encoding="utf-8",
  )

  result = retry_module.retry(ledger_path, execute=True)

  assert len(calls) == 1
  assert calls[0]["job_id"] == 7
  assert calls[0]["task_ids"] == [101, 102]
  assert [row["action"] for row in result["results"]] == [
      "retried", "retried"
  ]
  persisted = json.loads(ledger_path.read_text(encoding="utf-8"))
  assert persisted["101"]["status"] == "retry_submitted"
  assert persisted["102"]["status"] == "retry_submitted"
  assert persisted["101"]["retry_submitted_at"] == persisted["102"][
      "retry_submitted_at"]


def test_validation_failure_requires_matching_ledger_class():
  sigsegv = "CppException: SIGSEGV"
  invariant = (
      "CppException: Check failed: "
      "seed.confirm_timestamp() < current_timestamp")

  assert retry_module._is_allowlisted(
      {"failure_class": "simulator_shutdown_sigsegv"}, sigsegv)
  assert retry_module._is_allowlisted(
      {"failure_class": "planner_timestamp_invariant"}, invariant)
  assert not retry_module._is_allowlisted({}, sigsegv)
  assert not retry_module._is_allowlisted(
      {"failure_class": "planner_timestamp_invariant"}, sigsegv)
