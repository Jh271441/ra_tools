from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import pytest
from sqlalchemy import select
from app.models import ReleaseIssueSnapshot, ReleaseWorkflowState
from app.services import label_cycle as lane, release_workflow as w
from app.services.result_publication import reconcile_publications, publication, effective_publication
from app.services.release_cycle import resolve_current
from test_result_publication import data, ready_for_auto


@pytest.fixture
def prepared(data):
    db,batch,_ = ready_for_auto(data)
    reconcile_publications(db,{})
    for snap in db.scalars(select(ReleaseIssueSnapshot)):
        snap.payload = {**snap.payload, 'population_complete':True}
    db.commit()
    source = next(s.payload for s in db.scalars(select(ReleaseIssueSnapshot)) if w.population_identity(s.payload)==batch.payload['population_hash'])
    w.put_state(db,'settings',{'mode':'auto'})
    return db,batch,source


def test_merge_window_immutable_idempotent_revert(prepared):
    db,batch,source = prepared
    original = deepcopy(batch.payload)
    rows = deepcopy(source['issues']); rows[0]['ra_merge_result']='out_of_scope'
    now = datetime(2026,10,24,tzinfo=timezone.utc)
    fetch = lambda *_: (batch.release,rows)
    first = lane.refresh_release(db,{},batch,now=now,fetcher=fetch)
    assert first['status']=='queued'
    rows[2]['ra_merge_result']='成功'
    second = lane.refresh_release(db,{},batch,now=now+timedelta(minutes=45),fetcher=fetch)
    assert second['next_process_at']==first['next_process_at']
    result = lane.refresh_release(db,{},batch,now=now+timedelta(seconds=lane.MERGE_SECONDS),fetcher=fetch)
    # 199/200 is exactly 99.5%; must remain blocked by the strict budget.
    assert result['status']=='blocked' and result['reason']=='coverage_gate'
    rows[0]['ra_merge_result']='误触发'
    result = lane.refresh_release(db,{},batch,now=now+timedelta(seconds=lane.MERGE_SECONDS),fetcher=fetch)
    assert result['status']=='updated'
    key = result['revision_key']
    assert effective_publication(db,batch)['label_revision']['revision_key']==key
    assert effective_publication(db,batch)['quality_gate_passed']==publication(batch)['quality_gate_passed']
    again = lane.refresh_release(db,{},batch,now=now+timedelta(seconds=lane.MERGE_SECONDS+lane.CHECK_SECONDS*4),fetcher=fetch)
    assert again['status']=='idle' and again['revision_key']==key
    assert len([s for s in db.scalars(select(ReleaseWorkflowState)) if s.key.startswith('label_revision:')])==1
    assert batch.payload==original
    lane.refresh_release(db,{},batch,now=now+timedelta(seconds=lane.MERGE_SECONDS+lane.CHECK_SECONDS*5),fetcher=lambda *_:(batch.release,source['issues']))
    assert effective_publication(db,batch)==publication(batch)
    assert w.get_state(db,'label_cycle:'+batch.release)['applied_at'] is None


def test_input_change_missing_results_unknown(prepared):
    _,batch,source = prepared
    rows=deepcopy(source['issues']);rows[0]['version']='changed'
    assert lane.plan_revision(batch.payload,source,rows)['reason']=='input_changed'
    rows=deepcopy(source['issues']);rows[0]['ra_merge_result']='unknown'
    assert lane.plan_revision(batch.payload,source,rows)['reason']=='unknown_labels'
    rows=deepcopy(source['issues']);rows[0]['ra_merge_result']='误触发'
    p=deepcopy(batch.payload);del p['results']['1']
    assert lane.plan_revision(p,source,rows)['reason']=='missing_results'
    plan=lane.plan_revision(batch.payload,source,rows)
    assert plan['excluded_issue_ids']==['i2']
    assert plan['coverage']['issue_coverage']==200/201


def test_pure_gt_revision_projects_existing_issue_results(prepared):
    from app.services.label_issue_view import applied_rows
    db,batch,source = prepared
    rows = deepcopy(source['issues']); rows[0]['ra_merge_result'] = '误触发'
    now = datetime.now(timezone.utc)
    fetch = lambda *_: (batch.release,rows)
    lane.refresh_release(db,{},batch,now=now,fetcher=fetch)
    state = lane.refresh_release(db,{},batch,now=now+timedelta(hours=6),fetcher=fetch)
    assert state['status'] == 'updated'
    assert 'lineage' not in w.get_state(db,state['revision_key'])
    result = applied_rows(db,batch.release,{'issues':rows})
    assert result is not None
    projected = next(r for r in result if r['issue_id'] == rows[0]['issue_id'])
    signal = batch.payload['results'][projected['scenario_id']]['sim_triggered']
    assert projected['precision_label'] == ('FP' if signal else 'TN')
    assert projected['job_id'] == batch.payload['job_id']


def test_wait_manual_disabled_stale_audit(prepared,monkeypatch):
    db,batch,source=prepared
    now=datetime(2026,10,24,tzinfo=timezone.utc)
    rows=deepcopy(source['issues']);rows[0]['ra_merge_result']='误触发'
    fetch=lambda *_:(batch.release,rows)
    unchanged=lane.refresh_release(db,{},batch,now=now,fetcher=lambda *_:(batch.release,source['issues']))
    assert unchanged['status']=='idle' and unchanged['revision_key'] is None
    lane.refresh_release(db,{},batch,now=now,fetcher=fetch)
    w.put_state(db,'settings',{'mode':'manual'})
    assert lane.refresh_release(db,{},batch,now=now+timedelta(seconds=lane.MERGE_SECONDS),fetcher=fetch)['status']=='paused'
    w.put_state(db,'settings',{'mode':'auto'})
    assert lane.refresh_release(db,{'result_publication':{'enabled':False}},batch,now=now+timedelta(seconds=lane.MERGE_SECONDS),fetcher=fetch)['status']=='paused'
    lane.refresh_release(db,{},batch,now=now+timedelta(seconds=lane.MERGE_SECONDS),fetcher=fetch)
    monkeypatch.setenv('LABEL_REFRESH_ENABLED','1')
    assert lane.public_state(db,batch.release,now+timedelta(seconds=lane.MERGE_SECONDS+lane.CHECK_SECONDS*4))['reason']=='stale'
    base=publication(batch)
    batch.payload={**batch.payload,'binary_id':999}
    assert lane.revision_metrics(db,batch,base)==base


def test_current_switch_observed_and_future():
    p={'release':'1009','cycle_end':'2026-10-22','case_start':'2026-10-09T00:00:00+08:00','case_end_exclusive':'2026-10-22T00:00:01+08:00','last_issue_at':'2026-10-22T00:00:00+08:00','observed_at':'2026-10-23T00:00:00+08:00','status':'completed','verified':True,'evidence':'observed','completion_rule':'issue_last_time_24h'}
    config={'contract':{'verified':True,'reference':'test','time_field':'issue_time'},'periods':[p]}
    assert resolve_current(config,date(2026,10,24))['current_version']=='1009'
    config['periods'].append({**p,'release':'1016','status':'running','cycle_end':'2026-10-23'})
    assert resolve_current(config,date(2026,10,24))['current_version']=='1009'
    p['observed_at']='2026-10-24T23:00:00-08:00'
    assert resolve_current(config,date(2026,10,24))['current_version'] is None
    p['observed_at']='2026-10-23T00:00:00'
    assert resolve_current(config,date(2026,10,24))['current_version'] is None


def test_hourly_freshness_and_reuse(prepared, monkeypatch):
    db,batch,source=prepared
    now=datetime(2026,10,24,tzinfo=timezone.utc)
    monkeypatch.setenv('LABEL_REFRESH_ENABLED','1')
    lane.refresh_release(db,{},batch,now=now,fetcher=lambda *_:(batch.release,source['issues']))
    assert lane.public_state(db,batch.release,now+timedelta(hours=2))['status']=='idle'
    assert lane.public_state(db,batch.release,now+timedelta(hours=3,seconds=1))['reason']=='stale'
    identity=lane.activity_identity(source['issues'],'issue_time')
    from app.services.label_recovery import INPUT_FIELDS
    observed = [{**row, **{k:row.get(k) for k in INPUT_FIELDS}} for row in source['issues']]
    w.put_state(db,'release_observation:'+batch.release, {'release':batch.release,'observed_at':now.isoformat(),'issues':observed,'activity_hash':identity})
    w.put_state(db,'release_monitor:'+batch.release, {'status':'already_submitted','activity_hash':identity,'contract_hash':lane.digest({})})
    calls=[]
    monkeypatch.setattr(lane,'fetch_activity',lambda *_: (calls.append('fetch') or (batch.release,source['issues'])))
    assert lane.fetch_observed_activity(db,{},batch.release,now+timedelta(minutes=59))[1]==observed
    assert calls==[]
    lane.fetch_observed_activity(db,{},batch.release,now+timedelta(hours=1))
    assert calls==['fetch']
    lane.fetch_observed_activity(db,{'contract':{'time_field':'different'}},batch.release,now)
    assert calls==['fetch','fetch']


def test_compact_monitor_requires_one_complete_query(prepared, monkeypatch):
    db, batch, source = prepared
    now = datetime.now(timezone.utc)
    identity = lane.activity_identity(source['issues'], 'issue_time')
    compact = [{k:row.get(k) for k in ('issue_id','issue_time','version','ra_type','ra_merge_result')}
               for row in source['issues']]
    w.put_state(db, 'release_observation:'+batch.release,
        {'release':batch.release, 'observed_at':now.isoformat(), 'issues':compact, 'activity_hash':identity})
    w.put_state(db, 'release_monitor:'+batch.release,
        {'status':'already_submitted', 'activity_hash':identity, 'contract_hash':lane.digest({})})
    calls = []
    full = [{**row, 'trip_id':'trip-'+row['issue_id'], 'ra_start_timestamp':1000}
            for row in source['issues']]
    monkeypatch.setattr(lane, 'fetch_activity', lambda *_:(calls.append('fetch') or (batch.release,full)))
    target, rows = lane.fetch_observed_activity(db, {}, batch.release, now)
    assert target == batch.release and calls == ['fetch']
    assert all(row['trip_id'] and row['ra_start_timestamp'] == 1000 for row in rows)
