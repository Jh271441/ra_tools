from copy import deepcopy
import sys
from types import SimpleNamespace
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


@pytest.mark.parametrize('drift', [None, 'arguments', 'population', 'runtime'])
def test_legacy_contract_audit_uses_actual_tasks_without_results(monkeypatch, drift):
    from contextlib import nullcontext
    import scripts.ra_release_orion_driver as driver
    import scripts.ra_repro_launch_full_orion as launch
    p = plan(); p['job_id'] = 789
    p['scenarios'].append({'scenario_id':'100', 'issue_id':'issue2', 'cohort':'positive_auto'})
    args = {'--scenario-id':'99', '--binary-id':'123', '--simulator-cache':'disabled',
            '--enable-dpe':'', '--sim-exec-args':' --sim_aligned_mode'}
    tasks = [{'signature':'99', 'task_args':args}, {'signature':'100', 'task_args':{**args, '--scenario-id':'100'}}]
    metadata = {'cluster':'prod_gen4', 'runtime_reference':'runtime-A'}
    if drift == 'arguments': tasks[1]['task_args']['--other-flag'] = 'changed'
    if drift == 'population': tasks[1]['signature'] = '101'
    if drift == 'runtime': metadata['runtime_reference'] = None
    monkeypatch.setattr(launch, '_load_api', lambda:(SimpleNamespace(get=lambda _:metadata),
        SimpleNamespace(query=lambda _:tasks), SimpleNamespace(SCENARIO_ID='--scenario-id'),
        None, None, None, None, None, SimpleNamespace(CN='cn'), lambda *_a,**_k:nullcontext()))
    if drift:
        with pytest.raises(ValueError): driver.execution_contract(p)
    else:
        result = driver.dispatch('contract', p)
        assert result == {'job_id':789, 'execution_contract_hash':driver.digest({
            'arguments':[driver.digest({k:v for k,v in args.items() if k != '--scenario-id'})],
            'runtime_reference':'runtime-A', 'binary_id':123, 'cluster':'prod_gen4'})}


@pytest.mark.parametrize("drift", [None, "labels", "version", "start_timestamp", "source", "coverage"])
def test_live_scenario_guard_checks_metadata_before_build(monkeypatch, drift):
    from scripts.ra_release_orion_driver import verify_live_labels
    label = "ra_repro_full_20261008_20260918"
    target = {"scenario_id": "99", "issue_id": "cn123", "cohort": "negative_auto",
              "scenario_revision": 1, "start_timestamp": 100, "end_timestamp": 200}
    row = {"id": 99, "version": 1, "start_timestamp": 100, "end_timestamp": 200,
           "labels": [label, label + "_gen4-release-20260918", label + "_negative_auto", label + "_AutoTrigger", "#123"]}
    value = {"release": "gen4-release-20260918", "period": {"release": "gen4-release-20260918"},
             "scenario_label": label, "scenarios": [target]}
    if drift == "labels":
        row["labels"].append("ra_repro_cycle_20261008_0918")
    elif drift == "source":
        row["labels"][-1] = "#124"
    elif drift in ("version", "start_timestamp"):
        row[drift] += 1
    response = {"msg": "success", "data": {"total": 0 if drift == "coverage" else 1, "res": [row]}}
    monkeypatch.setitem(sys.modules, "ra_api.scenario_api", SimpleNamespace(
        trail_api=SimpleNamespace(send_request=lambda *a: response),
        ScenarioURL=SimpleNamespace(query=SimpleNamespace(value="read-only-query"))))
    monkeypatch.setitem(sys.modules, "ra_api.sim_result_api", SimpleNamespace(
        SimResultClient=lambda: SimpleNamespace(_app_token="test")))
    if drift:
        with pytest.raises(ValueError):
            verify_live_labels(value)
    else:
        verify_live_labels(value)


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


@pytest.mark.parametrize('state,finished,total,ready', [
    ('RUNNING', 1, 2, False),  # one failed task alongside an active retry
    ('RUNNING', 2, 2, False),  # scheduler has not finalized the job yet
    ('COMPLETED', 1, 2, False),
    ('COMPLETED', 2, 2, True),
    ('COMPLETED', 0, 0, False),
    ('CANCELLED', 2, 2, False),
])
def test_final_audit_waits_for_job_and_entire_population(state, finished, total, ready):
    from scripts.ra_release_orion_driver import ready_for_audit
    assert ready_for_audit(dict(state=state, finished=finished, total=total)) is ready


@pytest.mark.parametrize('task_status,job_state,grace,expected', [
    (4, 1, 0, 'running'),
    (2, 2, 0, 'running'),
    (3, 2, 1, 'verifying'),
    (3, 2, 0, 'audited'),
    (4, 2, 0, 'audited'),
])
def test_poll_preserves_retry_and_dpe_wait_then_exports_all_terminal_rows(
    monkeypatch, task_status, job_state, grace, expected
):
    import contextlib
    import pandas as pd
    import scripts.ra_release_orion_driver as driver
    import scripts.ra_repro_launch_full_orion as launcher
    import scripts.ra_repro_validate_orion as validator
    import ra_api.sim_result_api as result_api
    value = {**plan(), 'job_id': 88, 'population_hash': 'population'}
    args = {'--binary-id': '123', '--simulator-cache': 'disabled', '--enable-dpe': ''}
    task = {'id': 8899, 'signature': '99', 'status': task_status, 'task_args': args}
    metadata = {'state': job_state, 'cluster': 'prod_gen4', 'max_concurrency': 1,
                'num_total_tasks': 1, 'priority': 2}
    monkeypatch.setattr(launcher, '_load_api', lambda: (
        SimpleNamespace(get=lambda _: metadata), SimpleNamespace(query=lambda _: [task]),
        None, None, None, lambda *_: 'test', None, None, SimpleNamespace(CN='cn'),
        lambda *a, **k: contextlib.nullcontext()))
    monkeypatch.setitem(sys.modules, 'orion_protos.orion_job_pb2', SimpleNamespace(
        OrionJob=SimpleNamespace(CANCELLED=3, Priority=SimpleNamespace(Name=lambda _: "NORMAL"), State=SimpleNamespace(Name=lambda n: {1:'RUNNING',2:'COMPLETED'}[n]))))
    monkeypatch.setitem(sys.modules, 'orion_protos.orion_task_pb2', SimpleNamespace(
        OrionTask=SimpleNamespace(Status=SimpleNamespace(Name=lambda n: {2:'RUNNING',3:'COMPLETED',4:'FAILED'}[n]))))
    calls=[]
    def query(*_):
        calls.append(True)
        return pd.DataFrame([dict(scenario_id=99, task_id=8899, task_status=task_status)])
    monkeypatch.setattr(validator, '_query_orion', query)
    monkeypatch.setattr(validator, '_summarize', lambda *_: dict(
        terminal=1, completed_pending_dpe_grace=grace, quality={}))
    monkeypatch.setattr(result_api, 'SimResultClient', lambda: SimpleNamespace(
        query_all_pages=lambda *a, **k: pd.DataFrame([{'scenario_id':99,validator._TRIGGER_METRIC:float('nan')}])) )
    result=driver.poll(value)
    assert result['status']==expected
    assert bool(calls) is (expected!='running')
    if expected=='audited':
        row=result['execution_export']['rows'][0]
        assert row['argument_hash']==digest(args)
        assert row[validator._TRIGGER_METRIC] is None
        assert row['task_status']==task_status


def test_native_runtime_is_explicit_and_preserves_server_credentials(tmp_path, monkeypatch):
    from scripts.run_native_release_driver import command_environment
    from types import SimpleNamespace
    monkeypatch.setattr('scripts.run_native_release_driver.pwd.getpwuid', lambda uid: SimpleNamespace(pw_dir='/home/service', pw_name='service'))
    repo = tmp_path / 'source'
    (repo / 'scripts').mkdir(parents=True)
    (repo / 'scripts/ra_release_orion_driver.py').touch()
    python = tmp_path / 'python'
    python.touch()
    config = dict(repo_root=str(repo), python=str(python), python_paths=[str(tmp_path)], state_dir=str(tmp_path/'state'))
    command, env = command_environment(config, {'HTTPS_PROXY':'test-proxy', 'ORION_TOKEN':'test-secret', 'PYTHONPATH':'unrelated','PYTHONHOME':'wrong','PYTHONUSERBASE':'wrong','HOME':'/root','USER':'root','LOGNAME':'root','XDG_CACHE_HOME':'/root/.cache','XDG_CONFIG_HOME':'/root/.config'})
    assert command == [str(python),str(repo/'scripts/ra_release_orion_driver.py')]
    assert 'HTTPS_PROXY' not in env
    assert 'PYTHONHOME' not in env and 'PYTHONUSERBASE' not in env
    assert env['PYTHONNOUSERSITE'] == '1'
    assert env['HOME'] == '/home/service' and env['USER'] == env['LOGNAME'] == 'service'
    assert 'XDG_CACHE_HOME' not in env and 'XDG_CONFIG_HOME' not in env
    assert env['ORION_TOKEN'] == 'test-secret'
    assert env['PYTHONPATH'] == str(repo)+':'+str(tmp_path)
    assert env['RELEASE_DRIVER_STATE_DIR'] == str(tmp_path/'state')
    config['python_paths'] = [str(tmp_path/'missing')]
    with pytest.raises(ValueError, match='incomplete'):
        command_environment(config, {})


def test_native_driver_reuses_existing_auth_file_without_persisting_token(tmp_path):
    import json
    from scripts.run_native_release_driver import command_environment
    repo=tmp_path/'source';(repo/'scripts').mkdir(parents=True);(repo/'scripts/ra_release_orion_driver.py').touch()
    python=tmp_path/'python';python.touch()
    auth=tmp_path/'orion.conf';original=json.dumps({'version':1,'auth':{'CN':'fixture-token'}});auth.write_text(original)
    config={'python':str(python),'repo_root':str(repo),'python_paths':[],'state_dir':str(tmp_path/'state'),'auth_config':str(auth)}
    _,env=command_environment(config,{})
    assert env['ORION_TOKEN']=='fixture-token'
    assert auth.read_text()==original and 'ORION_TOKEN' not in config
    _,env=command_environment(config,{'ORION_TOKEN':'explicit-token'})
    assert env['ORION_TOKEN']=='explicit-token'
