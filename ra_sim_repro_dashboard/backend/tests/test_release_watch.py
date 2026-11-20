from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models import ReleaseSimulationBatch
from app.services import release_watch as watch, release_workflow as w
from app.services.release_cycle import validate_period

START = datetime(2026, 10, 16, 0, tzinfo=timezone.utc)
RELEASE = "gen4-release-20260924"


@pytest.fixture
def config():
    return {"contract": {"verified": True, "reference": "confirmed view", "view_id": 2410, "time_field": "issue_time"},
            "periods": [], "release_monitor": {"enabled": True},
            "simulation": {"driver_command": ["test"], "template_job_id": 456, "max_concurrency": 1000}}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def rows():
    return [{"issue_id": "cn1", "version": "1." + RELEASE + ".600", "ra_type": 2,
             "ra_merge_result": "成功", "issue_time": int((START - timedelta(days=2)).timestamp() * 1000)}]


def observe_day(config, rows, previous=None):
    state = previous or {}
    for step in range(97):
        state = watch.observe(state, RELEASE, rows, START + timedelta(minutes=15 * step), config)
    return state


def test_last_issue_age_ready_immediately_after_full_query(config, rows):
    initial = watch.observe({}, RELEASE, rows, START, config)
    assert initial["quiet_seconds"] == 2 * 86400
    assert initial["status"] == "ready"
    assert initial["rule"] == "issue_last_time_24h"
    assert watch.make_period(initial, rows)["cycle_end"] == "2026-10-14"


def test_exact_24_hour_boundary_includes_weekends(config, rows):
    friday = datetime(2026, 10, 16, 10, tzinfo=timezone.utc)  # Friday 18:00 Shanghai
    weekend_rows = [{**rows[0], "issue_time": int(friday.timestamp() * 1000)}]
    before = watch.observe({}, RELEASE, weekend_rows, friday + timedelta(days=1, seconds=-1), config)
    after = watch.observe({}, RELEASE, weekend_rows, friday + timedelta(days=1), config)
    assert before["status"] == "observing" and before["quiet_seconds"] == 86399
    assert after["status"] == "ready" and after["quiet_seconds"] == 86400
    assert datetime.fromisoformat(after["eligible_at"]) == friday + timedelta(days=1)
    assert validate_period(watch.make_period(after, weekend_rows), True)


def test_latest_timestamp_resets_but_old_backfill_or_labels_do_not(config, rows):
    state = observe_day(config, rows)
    now = START + timedelta(days=1, minutes=15)
    late = {**rows[0], "issue_id": "cn2", "issue_time": rows[0]["issue_time"] - 1000}
    for changed in ([*rows, late], [late], [{**rows[0], "ra_merge_result": "误触发"}]):
        result = watch.observe(state, RELEASE, changed, now, config)
        assert result["status"] == "ready"
        assert result["quiet_seconds"] >= 86400
    recent = {**late, "issue_time": int((now - timedelta(hours=1)).timestamp() * 1000)}
    result = watch.observe(state, RELEASE, [*rows, recent], now, config)
    assert result["status"] == "observing" and result["quiet_seconds"] == 3600


def test_gap_contract_change_and_new_release_use_actual_issue_time(config, rows):
    state = observe_day(config, rows)
    now = START + timedelta(days=1, hours=1)
    assert watch.observe(state, RELEASE, rows, now, config)["quiet_seconds"] == 73 * 3600
    changed = deepcopy(config)
    changed["contract"]["reference"] = "new"
    assert watch.observe(state, RELEASE, rows, now, changed)["quiet_seconds"] == 73 * 3600
    newer = "gen4-release-20261008"
    assert watch.observe(state, newer, [{**rows[0], "version": "1."+newer+".610"}], now, config)["quiet_seconds"] == 73 * 3600
    with pytest.raises(ValueError, match="回退"):
        watch.observe({**state, "release": newer}, RELEASE, rows, now, config)


def test_invalid_observations(config, rows):
    for invalid in ([], rows+rows, [{**rows[0], "issue_id": None}],
                    [{**rows[0], "issue_time": int((START+timedelta(days=1)).timestamp()*1000)}]):
        with pytest.raises(ValueError):
            watch.observe({}, RELEASE, invalid, START, config)


def test_failure_blocks_but_recovery_uses_last_issue_time(db, config, rows):
    state = observe_day(config, rows)
    w.put_state(db, "release_monitor", state)
    def failed(_):
        raise RuntimeError("query failed")
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=failed)
    assert result["status"] == "source_error"
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1, minutes=15), activity_fetcher=lambda _: (RELEASE, rows))
    assert result["quiet_seconds"] == 3 * 86400 + 900


def test_period_guard_and_full_namespace(config, rows):
    state = observe_day(config, rows)
    period = watch.make_period(state, rows)
    assert period["scenario_creation_label"] == "ra_repro_full_20261014_20260924"
    assert validate_period(period, True)
    broken = {**period, "observed_at": period["quiet_since"]}
    with pytest.raises(ValueError, match="24小时"):
        validate_period(broken, True)
    existing = {"scenario_query_labels": ["ra_repro_full_20261010_20260924"]}
    assert watch.make_period(state, rows, existing)["scenario_creation_label"] == existing["scenario_query_labels"][0]


def configure_pipeline(monkeypatch, db, config, rows, *, timeout=False):
    state = observe_day(config, rows)
    w.put_state(db, "release_monitor", state)
    w.put_state(db, "settings", {"mode": "auto"})
    original_sync = w.sync_once
    def scenes(period):
        label = period['scenario_creation_label']
        return [{"scenario_id": "1", "issue_id": "cn1", "scenario_labels": [
            label, label+'_'+RELEASE, label+'_positive_auto', label+'_AutoTrigger']}]
    def sync(db, config, *, release=None):
        return original_sync(db, config, lambda *_: rows, scenes, release=release)
    monkeypatch.setattr(w, "sync_once", sync)
    calls = []
    def driver(config, action, payload):
        calls.append(action)
        if action == 'lookup_binary':
            return {"binary_id": 123, "binary_commit": "commit", "binary_evidence": "verified", "target_road_version": rows[0]['version']}
        if action == 'submit' and timeout:
            raise TimeoutError()
        return {"ready": True, "fingerprint": payload['fingerprint'], "job_id": 99}
    monkeypatch.setattr(w, 'driver_call', driver)
    return calls


@pytest.mark.parametrize('timeout', [False, True])
def test_pipeline_once_across_restart_and_no_retry(db, config, rows, monkeypatch, timeout):
    calls = configure_pipeline(monkeypatch, db, config, rows, timeout=timeout)
    fetch = lambda _: (RELEASE, rows)
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=fetch)
    assert result['status'] == ('submission_uncertain' if timeout else 'running')
    assert calls == ['lookup_binary', 'preflight', 'submit']
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1, minutes=15), activity_fetcher=fetch)
    assert result['status'] == 'already_submitted'
    assert calls.count('submit') == 1
    batch = db.scalars(select(ReleaseSimulationBatch)).one()
    batch.status = 'failed'; db.commit()
    watch.monitor_tick(db, config, now=START+timedelta(days=1, minutes=30), activity_fetcher=fetch)
    assert calls.count('submit') == 1


def test_manual_mode_observes_without_launch(db, config, rows, monkeypatch):
    w.put_state(db, 'release_monitor', observe_day(config, rows))
    monkeypatch.setattr(w, 'driver_call', Mock(side_effect=AssertionError('must not launch')))
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=lambda _: (RELEASE, rows))
    assert result['status'] == 'ready_manual'


def test_new_issue_during_preparation_does_not_launch(db, config, rows, monkeypatch):
    calls = configure_pipeline(monkeypatch, db, config, rows)
    observations = iter([(RELEASE, rows), (RELEASE, [*rows, {**rows[0], 'issue_id': 'cn2'}])])
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=lambda _: next(observations))
    assert result['status'] == 'ready'
    assert 'submit' not in calls
    assert not db.scalars(select(ReleaseSimulationBatch)).all()


def test_existing_manual_batch_never_duplicated(db, config, rows, monkeypatch):
    configure_pipeline(monkeypatch, db, config, rows)
    db.add(ReleaseSimulationBatch(fingerprint='old', release=RELEASE, status='complete', payload={'job_id': 88}))
    db.commit()
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=lambda _: (RELEASE, rows))
    assert result['status'] == 'already_submitted'
    assert result['batches'][0]['job_id'] == 88


def test_source_query_full_release_has_no_cutoff(monkeypatch, config, rows):
    older = {**rows[0], 'issue_id':'old', 'version':'1.gen4-release-20260918.578'}
    monkeypatch.setattr(watch, 'fetch_recent_releases', lambda _: [older, *rows])
    monkeypatch.setattr(watch, 'trail_credentials', lambda: ('id', 'token'))
    queried=[]
    monkeypatch.setattr(watch, 'complete_query', lambda url, body, *args: queried.append(body) or rows)
    assert watch.fetch_activity(config) == (RELEASE, rows)
    assert not any(f['attr_id']=='issue_time' for f in queried[0]['query_attrs'])


def test_queued_recovery_requires_fresh_observation(db, config, rows, monkeypatch):
    calls = configure_pipeline(monkeypatch, db, config, rows)
    real_execute = w.execute_batch
    monkeypatch.setattr(w, 'execute_batch', lambda db, batch, config, **kwargs: batch)
    fetch = lambda _: (RELEASE, rows)
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=fetch)
    assert result['status'] == 'queued'
    monkeypatch.setattr(w, 'execute_batch', real_execute)
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1, minutes=15), activity_fetcher=fetch)
    assert result['status'] == 'running'
    assert calls.count('submit') == 1


def test_preflight_failure_never_submits(db, config, rows, monkeypatch):
    calls = configure_pipeline(monkeypatch, db, config, rows)
    real_driver = w.driver_call
    monkeypatch.setattr(w, 'driver_call', lambda c,a,p: {'ready': False} if a == 'preflight' else real_driver(c,a,p))
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=lambda _: (RELEASE,rows))
    assert result['status'] == 'preflight_failed'
    watch.monitor_tick(db, config, now=START+timedelta(days=1, minutes=15), activity_fetcher=lambda _: (RELEASE,rows))
    assert 'submit' not in calls


def test_tick_routes_watch_without_legacy_auto_submission(db, config, monkeypatch, tmp_path):
    from contextlib import nullcontext
    w.put_state(db, 'settings', {'mode':'auto'})
    monkeypatch.setattr(w, 'SessionLocal', lambda: nullcontext(db))
    monkeypatch.setattr(w, 'effective_config', lambda _: config)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'lock'))
    calls=[]
    monkeypatch.setattr(watch, 'monitor_releases', lambda *_: calls.append('watch'))
    monkeypatch.setattr(w, 'sync_once', lambda *_: None)
    monkeypatch.setattr(w, 'poll_batches', lambda *_: calls.append('poll'))
    monkeypatch.setattr(w, 'refresh_catalog', lambda *_: calls.append('catalog'))
    monkeypatch.setattr(w, 'prepare_missing_scenes', Mock(side_effect=AssertionError('legacy auto submit')))
    monkeypatch.setattr(w, 'queue_plan', Mock(side_effect=AssertionError('legacy auto submit')))
    w.run_tick()
    assert calls == ['watch','catalog','poll']


@pytest.mark.parametrize("rule", ["issue_inactivity_24h", "issue_last_time_24h"])
def test_catalog_discovers_missing_release_without_replacing_watcher_population(db, config, monkeypatch, rule):
    from app.services import release_catalog as catalog
    frozen = {"release": "gen4-release-20260918", "verified": True,
              "completion_rule": rule, "activity_hash": "frozen"}
    missing = {"release": RELEASE, "verified": True, "status": "completed"}
    config = {**config, "discover_cycles": True, "periods": [frozen]}
    w.put_state(db, 'catalog', {"periods": [frozen]})
    monkeypatch.setattr(catalog, 'fetch_recent_releases', lambda _: [])
    monkeypatch.setattr(catalog, 'infer_completed_cycles', lambda *_: (
        [{"release": frozen['release'], "verified": True}, missing], []))
    driver = Mock(return_value={"binary_id": 123, "binary_commit": "commit"})
    monkeypatch.setattr(w, 'driver_call', driver)
    w.refresh_catalog(db, config)
    periods = {p['release']: p for p in w.get_state(db, 'catalog')['periods']}
    assert periods[frozen['release']] == frozen
    assert periods[RELEASE]['binary_id'] == 123
    driver.assert_called_once_with(config, 'lookup_binary', missing)
    assert db.scalars(select(ReleaseSimulationBatch)).all() == []


def test_discovery_windows_have_no_gaps_and_fail_on_out_of_range(config, monkeypatch):
    from app.services import release_catalog as catalog
    windows = []
    monkeypatch.setattr(catalog, 'trail_credentials', lambda: ('app','token'))
    def query(url, body, *args):
        window = next(f['val'] for f in body['query_attrs'] if f['attr_id'] == 'issue_time')
        windows.append(window)
        return []
    monkeypatch.setattr(catalog,'complete_query',query)
    assert catalog.fetch_recent_releases(config) == []
    assert len(windows) == 9
    assert all(a['max'] + 1 == b['min'] for a,b in zip(windows,windows[1:]))
    assert all(w['max'] - w['min'] < 7*86400000 for w in windows)
    monkeypatch.setattr(catalog,'complete_query',lambda *args: [{'issue_id':'x','issue_time':0}])
    with pytest.raises(ValueError,match='时间窗口'):
        catalog.fetch_recent_releases(config)


def test_new_release_keeps_previous_observer_and_submits_it_once(db, config, rows, monkeypatch):
    calls = configure_pipeline(monkeypatch, db, config, rows)
    newer = "gen4-release-20261016"
    new_rows = [{**rows[0], "issue_id": "new", "version": "1." + newer + ".610", "issue_time": int((START + timedelta(days=1)).timestamp()*1000)}]
    fetches = []
    def fetch(_, release):
        fetches.append(release)
        return release, rows if release == RELEASE else new_rows
    for minutes in (0, 15):
        watch.monitor_releases(db, config, now=START+timedelta(days=1, minutes=minutes),
                               discovery_fetcher=lambda _: rows+new_rows, activity_fetcher=fetch)
    assert calls.count("submit") == 1
    assert w.get_state(db, "release_monitor:" + RELEASE)["status"] == "already_submitted"
    assert w.get_state(db, "release_monitor:" + newer)["status"] == "observing"
    assert w.get_state(db, "release_monitor")["release"] == newer
    assert fetches.count(RELEASE) == 3  # two observations plus pre-submit recheck


def test_catch_up_uses_old_issue_age_and_failure_is_isolated(db, config, rows):
    old = observe_day(config, rows)
    w.put_state(db, "release_monitor:" + RELEASE, old)
    newer = "gen4-release-20261016"
    new_rows = [{**rows[0], "version": "1." + newer + ".610"}]
    w.put_state(db, "release_monitor", watch.observe({}, newer, new_rows, START+timedelta(days=2), config))
    def fetch(_, release):
        if release == newer:
            raise RuntimeError("upstream unavailable")
        return release, rows
    watch.monitor_releases(db, config, now=START+timedelta(days=2),
                           discovery_fetcher=lambda _: new_rows, activity_fetcher=fetch)
    assert w.get_state(db, "release_monitor:" + RELEASE)["quiet_seconds"] == 4 * 86400
    assert w.get_state(db, "release_monitor:" + newer)["status"] == "source_error"
    assert w.get_state(db, "release_observation:" + RELEASE)["issues"]
    assert not db.scalars(select(ReleaseSimulationBatch)).all()


def test_discovery_recovers_intermediate_releases_without_replaying_archive(db, config, rows):
    older = "gen4-release-20260821"
    middle = "gen4-release-20261009"
    newer = "gen4-release-20261016"
    populations = {r: [{**rows[0], "version": "1." + r + ".610"}] for r in [older, RELEASE, middle, newer]}
    w.put_state(db, "release_monitor", watch.observe({}, RELEASE, rows, START, config))
    called = []
    def fetch(_, release):
        called.append(release)
        return release, populations[release]
    watch.monitor_releases(db, config, now=START+timedelta(minutes=15),
                           discovery_fetcher=lambda _: sum(populations.values(), []), activity_fetcher=fetch)
    assert called == [RELEASE, middle, newer]
    assert w.get_state(db, "release_monitor:" + middle)["issue_count"] == 1


def test_discovery_failure_still_observes_known_release(db, config, rows):
    w.put_state(db, "release_monitor", watch.observe({}, RELEASE, rows, START, config))
    def fail(_):
        raise RuntimeError("discovery failed")
    watch.monitor_releases(db, config, now=START+timedelta(minutes=15), discovery_fetcher=fail,
                           activity_fetcher=lambda _, release: (release, rows))
    assert w.get_state(db, "release_monitor")["quiet_seconds"] == 2 * 86400 + 900
    assert w.get_state(db, "release_monitor_discovery")["status"] == "source_error"


def test_legacy_period_keeps_original_continuous_observation_guard(config, rows):
    state = observe_day(config, rows)
    period = watch.make_period(state, rows)
    period.update(completion_rule="issue_inactivity_24h", quiet_since=START.isoformat())
    assert validate_period(period, True)
    period["quiet_since"] = (START + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="24小时"):
        validate_period(period, True)


def test_scene_preparation_state_and_timeout_are_actionable(db, config, rows, monkeypatch):
    import subprocess
    configure_pipeline(monkeypatch, db, config, rows)
    def slow_prepare(db, config, **kwargs):
        assert w.get_state(db, 'release_monitor')['status'] == 'preparing_scenes'
        error = subprocess.TimeoutExpired(['driver'], 1800)
        error.action = 'prepare_scenes'
        raise error
    monkeypatch.setattr(w, 'prepare_missing_scenes', slow_prepare)
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=lambda _: (RELEASE, rows))
    assert result['status'] == 'blocked'
    assert result['error_code'] == 'driver_timeout'
    assert result['error_action'] == 'prepare_scenes'
    assert not db.scalars(select(ReleaseSimulationBatch)).all()


@pytest.mark.parametrize('action,seconds', [('prepare_scenes',1800),('poll',600),('submit',120),('lookup_binary',120)])
def test_driver_timeout_budget_is_scoped(config, monkeypatch, action, seconds):
    import subprocess
    def run(command, **kwargs):
        assert kwargs['timeout'] == seconds
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(w.subprocess, 'run', run)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        w.driver_call(config, action, {})
    assert caught.value.action == action


def test_missing_bag_records_exact_issue_and_never_queues_partial_batch(db, config, rows, monkeypatch):
    configure_pipeline(monkeypatch, db, config, rows)
    failure = {'prepared': 1855, 'failed': 1, 'failures': [{'issue_id':'cn123','reason':'missing_bag'}]}
    def fail(*args, **kwargs):
        raise w.ScenePreparationError({**failure, 'error':'1 scenes could not be prepared'})
    monkeypatch.setattr(w, 'prepare_missing_scenes', fail)
    result = watch.monitor_tick(db, config, now=START+timedelta(days=1), activity_fetcher=lambda _: (RELEASE, rows))
    assert result['error_code'] == 'scene_preparation_failed'
    assert result['preparation'] == failure
    assert not db.scalars(select(ReleaseSimulationBatch)).all()


def test_hourly_source_throttle_preserves_job_polling(db, config, monkeypatch, tmp_path):
    from contextlib import nullcontext
    monkeypatch.setattr(w,'SessionLocal',lambda: nullcontext(db))
    monkeypatch.setattr(w,'effective_config',lambda _: config)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK',str(tmp_path/'hourly-lock'))
    calls=[]
    monkeypatch.setattr(watch,'monitor_releases',lambda *_:calls.append('watch'))
    monkeypatch.setattr(w,'refresh_catalog',lambda *_:calls.append('catalog'))
    monkeypatch.setattr(w,'sync_once',lambda *_:calls.append('sync'))
    monkeypatch.setattr(w,'poll_batches',lambda *_:calls.append('poll'))
    w.tick();w.tick()
    assert calls==['watch','catalog','sync','poll','poll']
    w.put_state(db,'source_poll',{'started_at':(datetime.now(timezone.utc)-timedelta(hours=1,seconds=1)).isoformat()})
    w.tick()
    assert calls[-4:]==['watch','catalog','sync','poll']
