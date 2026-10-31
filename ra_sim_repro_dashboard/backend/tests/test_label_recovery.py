from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch
from app.services import label_cycle, label_recovery, release_workflow as w
from app.services.result_publication import effective_publication, publication, reconcile_publications
from test_release_workflow import db, config, scene_labels
from test_issue_tolerance import setup
from test_release_backfill import export, running


@pytest.fixture
def labelled(db, config, monkeypatch):
    rows, scenes, _, sync = setup(db, config, monkeypatch, failed=0, total=201)
    rows.append({'issue_id':'new', 'ra_type':2, 'ra_merge_result':'未填写'})
    for index, row in enumerate(rows):
        row.update(trip_id='trip-'+row['issue_id'], ra_start_timestamp=1000+index,
                   trip_start_time=0, trip_end_time=10000)
    sync()
    calls = []
    def driver(cfg, action, payload):
        calls.append(action)
        if action == 'prepare_scenes':
            scenes.append({'issue_id':'new', 'scenario_id':'900', 'scenario_labels':scene_labels('positive_auto')})
            return {'ready':True, 'failed':0, 'failures':[]}
        if action == 'preflight':
            return {'fingerprint':payload['fingerprint'], 'ready':True}
        if action == 'submit':
            return {'fingerprint':payload['fingerprint'], 'job_id':100 + calls.count('submit')}
        if action == 'poll':
            return {'fingerprint':payload['fingerprint'], 'job_id':payload['job_id'],
                    'status':'audited', 'execution_export':export(payload, payload['job_id'])}
        if action == 'contract':
            return {'job_id':payload['job_id'], 'execution_contract_hash':'runtime-123'}
        raise AssertionError(action)
    monkeypatch.setattr(w, 'driver_call', driver)
    monkeypatch.setattr(w, 'fetch_scenarios', lambda period:deepcopy(scenes))
    plan = w.make_plan(db, config)
    base = w.queue_plan(db, plan['fingerprint'], config)
    w.execute_batch(db, base, config)
    w.poll_batches(db, config)
    assert publication(base)
    source = next(s.payload for s in db.scalars(select(ReleaseIssueSnapshot))
                  if w.population_identity(s.payload) == base.payload['population_hash'])
    w.put_state(db, 'settings', {'mode':'auto'})
    changed = deepcopy(rows)
    changed[-1]['ra_merge_result'] = '成功'
    return base, source, changed, calls


def start(db, config, labelled):
    base, source, rows, calls = labelled
    now = datetime.now(timezone.utc)
    fetcher = lambda *_:(base.release, rows)
    first = label_cycle.refresh_release(db, config, base, now=now, fetcher=fetcher)
    assert first['status'] == 'queued'
    due = now + timedelta(seconds=label_cycle.MERGE_SECONDS)
    value = label_cycle.refresh_release(db, config, base, now=due, fetcher=fetcher)
    return value, due, fetcher


def test_incremental_label_recovery_updates_metrics_and_resumes_without_duplicate(db, config, labelled):
    base, source, rows, calls = labelled
    original = deepcopy(base.payload)
    value, due, fetcher = start(db, config, labelled)
    assert value['status'] == 'recovering', value
    assert value['pending_count'] == 0 and value['change_count'] == 1
    assert value['recovery']['missing_count'] == 1 and value['recovery']['job_id'] == 102
    partial = effective_publication(db, base)
    assert partial['publication']['issue_count'] == 202
    assert partial['publication']['quality_level'] == 'normal'
    assert partial['publication']['excluded_issue_ids'] == ['new']
    child = db.scalars(select(ReleaseSimulationBatch).where(ReleaseSimulationBatch.fingerprint != base.fingerprint)).one()
    assert [s['scenario_id'] for s in child.payload['scenarios']] == ['900']
    assert child.payload['template_job_id'] == base.payload['job_id']
    label_cycle.refresh_release(db, config, base, now=due+timedelta(minutes=1), fetcher=fetcher)
    assert calls.count('submit') == 2
    w.poll_batches(db, config)
    assert child.status == 'complete'
    result = label_cycle.refresh_release(db, config, base, now=due+timedelta(hours=1), fetcher=fetcher)
    assert result['status'] == 'updated' and result['recovery']['missing_count'] == 0, result
    metrics = effective_publication(db, base)
    assert metrics['eligible'] == 202 and metrics['tp'] == 202
    assert metrics['publication']['source_job_ids'] == [101, 102]
    assert base.payload == original
    before = len(calls)
    label_cycle.refresh_release(db, config, base, now=due+timedelta(hours=2), fetcher=fetcher)
    assert len(calls) == before
    child.payload = {**child.payload, 'results':{}}
    db.commit()
    assert 'label_revision' not in effective_publication(db, base)


def test_manual_and_changed_physical_inputs_do_not_submit(db, config, labelled):
    base, source, rows, calls = labelled
    w.put_state(db, 'settings', {'mode':'manual'})
    value, due, fetcher = start(db, config, labelled)
    assert value['status'] == 'paused' and calls.count('submit') == 1
    w.put_state(db, 'settings', {'mode':'auto'})
    rows[0]['trip_id'] = 'changed'
    result = label_cycle.refresh_release(db, config, base, now=due, fetcher=fetcher)
    assert result['reason'] == 'input_changed'
    assert calls.count('submit') == 1


def test_waiting_bags_uses_six_hour_retry_and_keeps_partial_revision(db, config, labelled, monkeypatch):
    base, source, rows, calls = labelled
    driver = w.driver_call
    def missing(cfg, action, payload):
        if action == 'prepare_scenes':
            calls.append(action)
            return {'ready':False, 'failed':1, 'failures':[{'issue_id':'new','reason':'missing_bag'}]}
        return driver(cfg, action, payload)
    monkeypatch.setattr(w, 'driver_call', missing)
    value, due, fetcher = start(db, config, labelled)
    assert value['recovery']['status'] == 'waiting_bags'
    assert effective_publication(db, base)['publication']['issue_count'] == 202
    label_cycle.refresh_release(db, config, base, now=due+timedelta(hours=1), fetcher=fetcher)
    assert calls.count('prepare_scenes') == 1
    label_cycle.refresh_release(db, config, base, now=due+timedelta(hours=6), fetcher=fetcher)
    assert calls.count('prepare_scenes') == 2 and calls.count('submit') == 1


def test_legacy_runtime_is_audited_once_and_runtime_drift_cannot_merge(db, config, labelled, monkeypatch):
    base, source, rows, calls = labelled
    # A historical runtime audit is stored separately; primary receipts are immutable.
    base.payload = {**base.payload, 'result_import':{k:v for k,v in base.payload['result_import'].items() if k != 'execution_contract_hash'}}
    db.commit()
    assert label_recovery.contract(db, config, base) == 'runtime-123'
    assert label_recovery.contract(db, config, base) == 'runtime-123'
    assert calls.count('contract') == 1
    reconcile_publications(db, config)
    original = deepcopy(base.payload)
    value, due, fetcher = start(db, config, labelled)
    w.poll_batches(db, config)
    child = db.get(ReleaseSimulationBatch, value['recovery']['fingerprint'])
    child.payload = {**child.payload, 'result_import':{**child.payload['result_import'], 'execution_contract_hash':'other'}}
    db.commit()
    result = label_cycle.refresh_release(db, config, base, now=due+timedelta(hours=1), fetcher=fetcher)
    assert result['reason'] == 'execution_contract_changed'
    assert base.payload == original and calls.count('submit') == 2


def test_unknown_gt_during_recovery_and_manual_queue_cannot_launch(db, config, labelled):
    base, source, rows, calls = labelled
    value, due, fetcher = start(db, config, labelled)
    child = db.get(ReleaseSimulationBatch, value['recovery']['fingerprint'])
    # Simulate a persisted queue before its first external submission.
    child.status = 'queued'; db.commit()
    w.put_state(db, 'settings', {'mode':'manual'})
    before = calls.count('submit')
    w.execute_batch(db, child, config)
    assert child.status == 'queued' and calls.count('submit') == before
    w.put_state(db, 'settings', {'mode':'auto'})
    rows[0]['ra_merge_result'] = 'unknown'
    result = label_cycle.refresh_release(db, config, base, now=due+timedelta(hours=1), fetcher=fetcher)
    assert result['reason'] == 'unknown_labels' and calls.count('submit') == before
    w.put_state(db, 'release_observation:' + base.release, {'issues':rows})
    with pytest.raises(ValueError, match='unknown_labels'):
        w.execute_batch(db, child, config)
    assert calls.count('submit') == before


def test_label_revision_keeps_regular_backfill_and_tracks_later_results(db, config, running, monkeypatch):
    from app.services import release_backfill
    base, rows, scenes, receipt, sync, calls = running
    monkeypatch.setattr(w, 'fetch_scenarios', lambda period:deepcopy(scenes))
    w.poll_batches(db, config)
    original = deepcopy(base.payload)
    scenes.append({'issue_id':'0', 'scenario_id':'900', 'scenario_labels':scene_labels('positive_auto')})
    receipt['failures'] = [f for f in receipt['failures'] if f['issue_id'] != '0']
    now = datetime.now(timezone.utc)
    release_backfill.refresh_release(db, config, base, now=now)
    w.poll_batches(db, config)
    release_backfill.refresh_release(db, config, base, now=now+timedelta(minutes=1))
    assert effective_publication(db, base)['eligible'] == 198

    changed = deepcopy(rows); changed[0]['ra_merge_result'] = '误触发'
    fetcher = lambda *_:(base.release, changed)
    label_cycle.refresh_release(db, config, base, now=now, fetcher=fetcher)
    due = now+timedelta(hours=6)
    state = label_cycle.refresh_release(db, config, base, now=due, fetcher=fetcher)
    assert state.get('reason') is None, state.get('reason')
    assert state['status'] == 'recovering', state
    metrics = effective_publication(db, base)
    assert metrics['eligible'] == 198 and metrics['fp'] == 1
    assert metrics['publication']['source_job_ids'] == [101, 102]
    assert sum(action == 'submit' for action, _ in calls) == 2

    # A later regular recovery must not invalidate or shrink the GT revision.
    scenes.append({'issue_id':'1', 'scenario_id':'901', 'scenario_labels':scene_labels('positive_auto')})
    receipt['failures'] = [f for f in receipt['failures'] if f['issue_id'] != '1']
    release_backfill.refresh_release(db, config, base, now=due+timedelta(minutes=2))
    w.poll_batches(db, config)
    release_backfill.refresh_release(db, config, base, now=due+timedelta(minutes=3))
    label_cycle.refresh_release(db, config, base, now=due+timedelta(minutes=4), fetcher=fetcher)
    metrics = effective_publication(db, base)
    assert metrics['eligible'] == 199 and metrics['fp'] == 1
    assert metrics['publication']['source_job_ids'] == [101, 102, 103]
    assert base.payload == original


def test_older_compact_monitor_is_superseded_by_verified_full_input(db, config, labelled):
    base, source, rows, calls = labelled
    state, due, fetcher = start(db, config, labelled)
    child = db.get(ReleaseSimulationBatch, state['recovery']['fingerprint'])
    compact = [{k:v for k,v in row.items() if k not in label_recovery.INPUT_FIELDS[3:]} for row in rows]
    w.put_state(db, 'release_observation:'+base.release,
        {'issues':compact, 'observed_at':(due-timedelta(minutes=1)).isoformat()})
    assert label_recovery.source_valid(db, child)
    w.put_state(db, 'release_observation:'+base.release,
        {'issues':compact, 'observed_at':(due+timedelta(minutes=1)).isoformat()})
    assert not label_recovery.source_valid(db, child)
    changed = deepcopy(rows); changed[0]['trip_id'] = 'different-trip'
    w.put_state(db, 'release_observation:'+base.release,
        {'issues':changed, 'observed_at':(due+timedelta(minutes=1)).isoformat()})
    assert not label_recovery.source_valid(db, child)


def test_applied_labels_reach_issue_details_with_audited_job_and_pagination(db, config, labelled, monkeypatch):
    from app.services.release_watch import activity_identity
    base, source, rows, calls = labelled
    # Reclassify an existing successful trigger, and retain an untriggered value.
    rows[0]['ra_merge_result'] = '误触发'
    state, due, fetcher = start(db, config, labelled)
    driver = w.driver_call
    def untriggered_child(cfg, action, payload):
        value = driver(cfg, action, payload)
        if action == 'poll' and payload['job_id'] == 102:
            from app.services.result_integration import TRIGGER
            value['execution_export']['rows'][0][TRIGGER] = 0
        return value
    monkeypatch.setattr(w, 'driver_call', untriggered_child)
    w.poll_batches(db, config)
    label_cycle.refresh_release(db, config, base, now=due+timedelta(hours=1), fetcher=fetcher)
    monkeypatch.setattr(w, 'effective_config', lambda _: config)
    w.put_state(db, 'release_observation:'+base.release,
        {'issues':deepcopy(rows), 'activity_hash':activity_identity(rows,'issue_time'),
         'observed_at':datetime.now(timezone.utc).isoformat()})
    w.put_state(db, 'release_monitor:'+base.release,
        {'release':base.release,'population_changed_after_submission':True})
    # The public list previously routed every applied GT revision to "collecting".
    result = w.list_issues(db, base.release, query='new')
    assert result['status'] == 'ready' and result['total'] == 1
    assert result['items'][0]['scenario_id'] == '900'
    assert result['items'][0]['job_id'] == 102
    assert result['items'][0]['precision_label'] == 'FN'
    assert result['items'][0]['sim_triggered'] is False
    old = w.list_issues(db, base.release, query='"issue_id": "0"')['items'][0]
    assert old['source_result'] == '误触发' and old['precision_label'] == 'FP'
    assert old['job_id'] == 101 and old['simulation_status'] == 'result_ready'
    assert w.list_issues(db, base.release, page=2, page_size=10)['total'] == len(rows)
    assert len(w.list_issues(db, base.release, page=2, page_size=10)['items']) == 10
    assert w.list_issues(db, base.release, label='fabricated')['total'] == 0
    before = len(calls)
    assert w.list_issues(db, base.release, query='900')['total'] == 1
    assert len(calls) == before  # A detail GET must never call the driver/upstream.
    # A newer unapplied edit or changed physical input must not reuse stale labels.
    later = deepcopy(rows); later[-1]['ra_merge_result'] = '误触发'
    w.put_state(db, 'release_observation:'+base.release, {'issues':later})
    assert w.list_issues(db, base.release, query='new')['items'][0]['sim_triggered'] is None
    later = deepcopy(rows); later[-1]['trip_id'] = 'changed'
    w.put_state(db, 'release_observation:'+base.release, {'issues':later})
    assert w.list_issues(db, base.release, query='new')['items'][0]['sim_triggered'] is None
    w.put_state(db, 'release_observation:'+base.release, {'issues':deepcopy(rows)})
    child = db.get(ReleaseSimulationBatch, state['recovery']['fingerprint'])
    child.payload = {**child.payload, 'results':{}}
    db.commit()
    assert w.list_issues(db, base.release, query='new')['status'] == 'collecting'
