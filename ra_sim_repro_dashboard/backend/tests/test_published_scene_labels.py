from copy import deepcopy
import pytest
from test_release_workflow import db
from app.services import published_scene_labels as sync

RELEASE = 'gen4-release-20261106'
BASE = 'ra_repro_full_20261109_20261106'
PERIOD = dict(release=RELEASE, scenario_creation_label=BASE, verified=True)


def test_published_diff_includes_existing_drift_and_is_idempotent():
    issues = [{'issue_id': 'cn456', 'ra_type': 2, 'ra_merge_result': '误触发'}]
    scene = dict(scenario_id='123', issue_id='cn456', scenario_revision=0, start_timestamp=10, end_timestamp=20)
    live = [{**scene, 'scenario_labels': [BASE, BASE+'_'+RELEASE, BASE+'_positive_auto', BASE+'_AutoTrigger', '#456', 'custom']}]
    change, = sync.plan_changes(issues, [scene], live, PERIOD)
    assert set(change['before_labels'])-set(change['after_labels']) == {BASE+'_positive_auto'}
    assert set(change['after_labels'])-set(change['before_labels']) == {BASE+'_negative_auto'}
    live[0]['scenario_labels'] = change['after_labels']
    assert sync.plan_changes(issues, [scene], live, PERIOD) == []
    restored = [dict(issues[0], ra_merge_result='无需协助')]
    assert sync.plan_changes(restored, [scene], live, PERIOD)[0]['cohort']=='positive_auto'
    with pytest.raises(ValueError, match='input_changed'):
        sync.plan_changes(issues, [dict(scene, scenario_revision=1)], live, PERIOD)
    with pytest.raises(ValueError, match='trigger change'):
        sync.plan_changes([dict(restored[0],ra_type=3)], [scene], live, PERIOD)


def test_published_sync_updates_current_view_but_keeps_history(db, monkeypatch):
    from types import SimpleNamespace
    from app.models import ReleaseIssueSnapshot
    from app.services import release_workflow as w
    from app.services.auto_triage_metrics import _snapshot

    w.put_state(db, 'settings', {'mode':'auto'})
    issue = dict(issue_id='cn123', ra_type=2, ra_merge_result='误触发')
    frozen = dict(issue_id='cn123', scenario_id='1', scenario_revision=0, start_timestamp=10, end_timestamp=20)
    live = [{**frozen, 'scenario_labels':[BASE, BASE+'_'+RELEASE, BASE+'_positive_auto', BASE+'_AutoTrigger', '#123']}]
    original = ReleaseIssueSnapshot(release=RELEASE, period_hash='period',
        payload={'period': PERIOD,'scenarios':deepcopy(live),'population_complete':True})
    db.add(original);db.commit()
    batch = SimpleNamespace(release=RELEASE, fingerprint='job-fingerprint', payload={'job_id':1234, 'scenario_label':BASE})
    monkeypatch.setattr(sync,'effective_publication',lambda *_:{'label_revision':{'revision_key':'rev'}})
    monkeypatch.setattr(sync,'standard_inputs',lambda *_:([issue], [frozen], {}, {}))
    monkeypatch.setattr(w,'fetch_scenarios',lambda *_:deepcopy(live))
    calls=[]
    def apply(cfg,action,payload):
        calls.append(action)
        live[0]['scenario_labels'] = payload['changes'][0]['after_labels']
        return {'ready':True, 'request_hash':w.digest(payload),'verified_count':1,'audit_path':'audit.json'}
    monkeypatch.setattr(w,'driver_call',apply)
    state = dict(status='idle',revision_key='rev',applied_source_hash='approved')
    sync.synchronize(db, {}, batch, {**state,'status':'queued'})
    assert calls==[]
    sync.synchronize(db, {}, batch, state)
    sync.synchronize(db, {}, batch, state)
    assert calls==['reconcile_labels']
    assert original.payload['scenarios'][0]['scenario_labels'] != live[0]['scenario_labels']
    assert _snapshot(db, RELEASE).payload['scenarios'][0]['scenario_labels']==live[0]['scenario_labels']
    receipt=w.get_state(db,'scene_cohort_sync:'+RELEASE)
    assert receipt['changed_count']==0 and receipt['last_write']['verified_count']==1
