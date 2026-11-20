from copy import deepcopy
import pytest
from test_release_workflow import db, config, population, scenarios
from app.models import ReleaseSimulationBatch
from app.services import release_workflow as w


def setup(db,config,monkeypatch):
    rows=population();rows[0]['ra_merge_result']='误触发'
    scenes=scenarios()
    real_sync=w.sync_once
    def sync(*args,**kwargs):
        return real_sync(db,config,lambda *a:rows,lambda *a:scenes)
    monkeypatch.setattr(w,'sync_once',sync)
    snapshot=sync()
    calls=[]
    def driver(cfg,action,payload):
        calls.append((action,payload))
        for change in payload['changes']:
            next(s for s in scenes if s['scenario_id']==change['scenario_id'])['scenario_labels']=change['after_labels']
        return {'ready':True,'verified_count':len(payload['changes']),'request_hash':w.digest(payload),'audit_path':'test-audit'}
    monkeypatch.setattr(w,'driver_call',driver)
    return snapshot,scenes,calls


def test_no_missing_bags_still_reconciles_gt_before_first_plan(db,config,monkeypatch):
    snapshot,scenes,calls=setup(db,config,monkeypatch)
    before=deepcopy(snapshot.payload)
    w.prepare_missing_scenes(db,config)
    plan=w.make_plan(db,config)
    assert [c[0] for c in calls]==['reconcile_labels']
    assert plan['scenarios'][0]['cohort']=='negative_auto'
    assert snapshot.payload==before
    assert w.get_state(db,'scenario_labels:'+snapshot.release)['count']==1
    w.prepare_missing_scenes(db,config)
    assert len(calls)==1


@pytest.mark.parametrize('status,payload',[('running',{'job_id':99}),('complete',{'job_id':99}),('submission_uncertain',{})])
def test_submitted_or_uncertain_batches_keep_original_labels(db,config,monkeypatch,status,payload):
    snapshot,scenes,calls=setup(db,config,monkeypatch)
    db.add(ReleaseSimulationBatch(fingerprint='frozen',release=snapshot.release,status=status,payload=payload));db.commit()
    assert w.reconcile_preparation_labels(db,config,snapshot) is snapshot
    assert calls==[]
    with pytest.raises(ValueError,match='label'):
        w.make_plan(db,config)
