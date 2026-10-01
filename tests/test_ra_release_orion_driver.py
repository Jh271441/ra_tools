from copy import deepcopy
import pytest
from scripts.ra_release_orion_driver import (
    digest,
    validate_plan,
    replay_arguments,
    check_task,
    submit,
)


def plan():
    value = {
        "release": "gen4-release-20260904",
        "period": {"verified": True, "binary_evidence": "release registry receipt"},
        "binary_id": 123,
        "template_job_id": 456,
        "issues": [],
        "simulation": {
            "cluster": "prod_gen4",
            "max_concurrency": 1,
            "cache": "disabled",
            "dpe": True,
            "recovery_mode": "baseline",
        },
        "scenarios": [
            {"scenario_id": "99", "issue_id": "issue1", "cohort": "negative_auto"}
        ],
    }
    return {**value, "fingerprint": digest(value)}


def rehash(value):
    value["fingerprint"] = digest(
        {k: v for k, v in value.items() if k != "fingerprint"}
    )
    return value


def test_verified_immutable_plan_required():
    value = plan()
    validate_plan(value)
    value["binary_id"] = 777
    with pytest.raises(ValueError, match="fingerprint"):
        validate_plan(value)
    rehash(value)
    value["period"]["verified"] = False
    rehash(value)
    with pytest.raises(ValueError, match="boundaries"):
        validate_plan(value)


def test_duplicate_population_or_unknown_truth_rejected():
    value = plan()
    value["scenarios"].append(deepcopy(value["scenarios"][0]))
    rehash(value)
    with pytest.raises(ValueError):
        validate_plan(value)
    value = plan()
    value["scenarios"][0]["cohort"] = "unknown"
    rehash(value)
    with pytest.raises(ValueError):
        validate_plan(value)


def test_baseline_keeps_aligned_mode_and_removes_experimental_flags():
    old = "--sim_aligned_mode --sim_state_recovery_level 3 --planning_enable_sim_assist_stuck_independent_replay --warmup=3"
    baseline = replay_arguments(old, "baseline")
    assert "--sim_aligned_mode" in baseline and "--warmup=3" in baseline
    assert (
        "sim_state_recovery_level" not in baseline
        and "independent_replay" not in baseline
    )
    controlled = replay_arguments(old, "level4-independent")
    assert controlled.count("--sim_state_recovery_level=4") == 1


def test_job_runtime_gates():
    args = {
        "--binary-id": "123",
        "--simulator-cache": "disabled",
        "--enable-dpe": "",
        "--sim-exec-args": "--sim_aligned_mode",
    }
    check_task(args, 123, "baseline")
    for key, value in [
        ("--binary-id", "124"),
        ("--simulator-cache", "enabled"),
        ("--sim-exec-args", "--sim_state_recovery_level=4"),
    ]:
        mutated = {**args, key: value}
        with pytest.raises(ValueError):
            check_task(mutated, 123, "baseline")


def test_driver_persists_before_launch_and_refuses_ambiguous_retry(
    tmp_path, monkeypatch
):
    import scripts.ra_release_orion_driver as driver

    def launch(*args, **kwargs):
        assert (tmp_path / (plan()["fingerprint"] + ".json")).exists()
        raise TimeoutError()

    monkeypatch.setattr(
        driver,
        "build_job",
        lambda _: (
            object(),
            {"priority": 2, "runtime_reference": "test"},
            launch,
            "test-auth",
        ),
    )
    with pytest.raises(TimeoutError):
        submit(plan(), tmp_path)
    with pytest.raises(ValueError, match="uncertain"):
        submit(plan(), tmp_path)


def test_driver_duplicate_submission_returns_same_receipt(tmp_path, monkeypatch):
    import scripts.ra_release_orion_driver as driver

    calls = []

    def launch(*args, **kwargs):
        calls.append(kwargs)
        return 888

    monkeypatch.setattr(
        driver,
        "build_job",
        lambda _: (
            object(),
            {"priority": 2, "runtime_reference": "test"},
            launch,
            "test-auth",
        ),
    )
    assert submit(plan(), tmp_path)["job_id"] == 888
    assert submit(plan(), tmp_path)["job_id"] == 888
    assert len(calls) == 1 and calls[0]["max_concurrency"] == 1


def test_requested_concurrency_is_validated_and_sent_to_orion(tmp_path, monkeypatch):
    import scripts.ra_release_orion_driver as driver

    value = plan()
    value["simulation"]["max_concurrency"] = 1000
    rehash(value)
    validate_plan(value)
    calls = []

    def launch(*args, **kwargs):
        calls.append(kwargs)
        return 12345

    monkeypatch.setattr(
        driver,
        "build_job",
        lambda _: (
            object(),
            {"priority": 2, "runtime_reference": "test"},
            launch,
            "test-auth",
        ),
    )
    submit(value, tmp_path)
    assert calls[0]["max_concurrency"] == 1000
    for invalid in [0, 1001, True, "1000", 1.5]:
        value = plan()
        value["simulation"]["max_concurrency"] = invalid
        rehash(value)
        with pytest.raises(ValueError):
            validate_plan(value)


def test_high_submission_uses_explicit_priority_and_keeps_legacy_default(
    tmp_path, monkeypatch
):
    import sys
    from types import SimpleNamespace
    import scripts.ra_release_orion_driver as driver

    monkeypatch.setitem(
        sys.modules,
        "orion_protos.orion_job_pb2",
        SimpleNamespace(
            OrionJob=SimpleNamespace(
                Priority=SimpleNamespace(
                    Value=lambda value: {"NORMAL": 2, "HIGH": 1}[value]
                )
            )
        ),
    )
    value = plan()
    value["simulation"]["priority"] = "HIGH"
    value["simulation"]["max_concurrency"] = 1000
    rehash(value)
    validate_plan(value)
    calls = []

    def launch(*args, **kwargs):
        calls.append(kwargs)
        return 999

    monkeypatch.setattr(
        driver,
        "build_job",
        lambda _: (
            object(),
            {"priority": 2, "runtime_reference": "test"},
            launch,
            "test-auth",
        ),
    )
    submit(value, tmp_path)
    assert calls[0]["priority"] == 1 and calls[0]["max_concurrency"] == 1000
    assert driver.launch_priority({}, 2) == 2
    value["simulation"]["priority"] = "RESERVED"
    rehash(value)
    with pytest.raises(ValueError):
        validate_plan(value)


def test_live_progress_keeps_failed_cancelled_and_unknown_separate():
    from scripts.ra_release_orion_driver import summarize_progress

    names = {
        0: "UNKNOWN_STATUS",
        1: "UNASSIGNED",
        2: "RUNNING",
        3: "COMPLETED",
        4: "FAILED",
        5: "CANCELLED",
    }
    tasks = [
        {"id": i, "signature": str(i), "status": status}
        for i, status in enumerate([1, 1, 2, 3, 4, 5, 0])
    ]
    result = summarize_progress(
        99,
        {"state": 1, "num_total_tasks": 7, "finish_time": "1971-01-01T00:00:00Z"},
        tasks,
        names.__getitem__,
        lambda _: "RUNNING",
    )
    assert (
        result["queued"],
        result["running"],
        result["completed"],
        result["failed"],
        result["cancelled"],
        result["unknown"],
    ) == (2, 1, 1, 1, 1, 1)
    assert result["finished"] == 3 and result["percent"] == 42.86
    assert result["finished_at"] is None and len(result["failures"]) == 2
    with pytest.raises(ValueError, match="Incomplete"):
        summarize_progress(
            99, {"num_total_tasks": 8}, tasks, names.__getitem__, lambda _: "RUNNING"
        )
