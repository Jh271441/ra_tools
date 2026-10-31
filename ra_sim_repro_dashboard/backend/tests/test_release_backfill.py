from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from app.models import ReleaseSimulationBatch
from app.services import release_workflow as w, release_backfill as lane, release_resume as resume
from app.services.result_publication import publication, effective_publication
from app.services.result_integration import TRIGGER
from test_release_workflow import db, config, scene_labels
from test_issue_tolerance import setup


def export(plan, jid):
    scenes=plan['scenarios']
    return {'job_id':jid,'execution_contract_hash':'runtime-123',**{k:plan[k] for k in ('release','binary_id','population_hash')},
        'progress':{'job_id':jid,'state':'COMPLETED','total':len(scenes),'completed':len(scenes),
                    'failed':0,'cancelled':0,'running':0,'queued':0,'unknown':0},'quality':{'quality':{}},
        'rows':[{**s,'task_id':f'{jid}-{s["scenario_id"]}','task_status':3,'task_outcome':'Done',
            'argument_hash':f'args-{s["scenario_id"]}','simulator_cache_hit':False,
            'inference_log_count':1,'dpe_output_count':1,'output_bag_count':1,
            'failed_evaluation_count':0,'unexpected_warning_count':0,TRIGGER:1} for s in scenes]}


@pytest.fixture
def running(db,config,monkeypatch):
    rows,scenes,receipt,sync=setup(db,config,monkeypatch,failed=4,total=201)
    w.prepare_missing_scenes(db,config)
    plan=w.make_plan(db,config)
    calls=[]
    def driver(cfg,action,payload):
        calls.append((action,payload.get('fingerprint')))
        if action=='prepare_scenes':
            return {'ready':False,'failed':len(receipt['failures']),'failures':receipt['failures']}
        if action=='preflight':return {'fingerprint':payload['fingerprint'],'ready':True}
        if action=='submit':return {'fingerprint':payload['fingerprint'],'job_id':100+sum(a=='submit' for a,_ in calls)}
        if action=='receipt':return {'fingerprint':payload['fingerprint'],'job_id':payload.get('job_id')}
        if action=='poll':return {'fingerprint':payload['fingerprint'],'job_id':payload['job_id'],
            'status':'audited','execution_export':export(payload,payload['job_id'])}
        raise AssertionError(action)
    monkeypatch.setattr(w,'driver_call',driver)
    batch=w.queue_plan(db,plan['fingerprint'],config)
    w.execute_batch(db,batch,config)
    w.put_state(db,'settings',{'mode':'auto'})
    return batch,rows,scenes,receipt,sync,calls


def test_additive_mapping_does_not_invalidate_running_frozen_job(db,config,running):
    batch,_,scenes,_,sync,_=running
    scenes.append({'issue_id':'0','scenario_id':'900','scenario_labels':scene_labels('positive_auto')})
    sync()
    assert lane.frozen_snapshot_valid(db,batch)
    w.poll_batches(db,config)
    assert batch.status=='complete' and publication(batch)
    assert '900' not in batch.payload['results']


def test_source_changes_still_block_import(db,config,running):
    batch,rows,_,_,sync,_=running
    rows[0]['ra_merge_result']='失败';sync()
    w.poll_batches(db,config)
    assert batch.status=='running' and not batch.payload.get('result_import')
    assert batch.payload['last_poll_error']


def test_partial_recovery_only_submits_new_scene_and_merges_ledger(db,config,running):
    batch,_,scenes,receipt,sync,calls=running
    w.poll_batches(db,config)
    original=deepcopy(batch.payload)
    assert publication(batch)['publication']['quality_level']=='degraded'
    scenes.append({'issue_id':'0','scenario_id':'900','scenario_labels':scene_labels('positive_auto')})
    receipt['failures']=[f for f in receipt['failures'] if f['issue_id']!='0']
    now=datetime.now(timezone.utc)
    value=lane.refresh_release(db,config,batch,now=now)
    assert value['status']=='simulating',value
    child=db.get(ReleaseSimulationBatch,value['fingerprint'])
    assert [s['scenario_id'] for s in child.payload['scenarios']]==['900']
    assert len(batch.payload['scenarios'])==197 and batch.payload==original
    lane.refresh_release(db,config,batch,now=now,force=True)
    assert sum(a=='submit' for a,_ in calls)==2
    w.poll_batches(db,config)
    assert child.status=='complete'
    value=lane.refresh_release(db,config,batch,now=now+timedelta(minutes=1))
    assert value['status']=='waiting_bags' and value['pending_count']==3,value
    metrics=effective_publication(db,batch)
    assert metrics['publication']['valid_issue_count']==198
    assert metrics['publication']['issue_count']==201
    assert metrics['publication']['source_job_ids']==[101,102]
    assert metrics['eligible']==198 and metrics['backfill_revision']
    assert batch.payload==original
    count=len(calls)
    lane.refresh_release(db,config,batch,now=now+timedelta(hours=1))
    assert len(calls)==count
    child.payload={**child.payload,'results':{}};db.commit()
    assert 'backfill_revision' not in effective_publication(db,batch)


def test_resume_uncertain_submission_never_launches_again(db,config,running,monkeypatch):
    batch,_,_,_,_,calls=running
    batch.status='submission_uncertain';db.commit()
    monkeypatch.setattr(w,'effective_config',lambda _:config)
    value=resume.request(db,batch.release,batch.fingerprint)
    assert resume.request(db,batch.release,batch.fingerprint)==value
    before=sum(a=='submit' for a,_ in calls)
    resume.process_requests(db,config)
    assert sum(a=='submit' for a,_ in calls)==before
    assert batch.status=='complete'
    assert resume.public_state(db,batch.release)['status']=='complete'


def test_resume_rejects_changed_checkpoint_and_manual_mode(db,config,running,monkeypatch):
    batch,*_=running
    monkeypatch.setattr(w,'effective_config',lambda _:config)
    with pytest.raises(ValueError,match='checkpoint_changed'):
        resume.request(db,batch.release,'stale')
    w.put_state(db,'settings',{'mode':'manual'})
    with pytest.raises(ValueError,match='manual_mode'):
        resume.request(db,batch.release,batch.fingerprint)


def test_changed_actual_runtime_cannot_merge_recovery(db,config,running):
    batch,_,scenes,receipt,_,_=running
    w.poll_batches(db,config)
    scenes.append({'issue_id':'0','scenario_id':'900','scenario_labels':scene_labels('positive_auto')})
    receipt['failures']=[f for f in receipt['failures'] if f['issue_id']!='0']
    value=lane.refresh_release(db,config,batch)
    child=db.get(ReleaseSimulationBatch,value['fingerprint'])
    w.poll_batches(db,config)
    child.payload={**child.payload,'result_import':{**child.payload['result_import'],'execution_contract_hash':'changed-runtime'}}
    db.commit()
    result=lane.refresh_release(db,config,batch,force=True)
    assert result['status']=='blocked' and result['reason']=='execution_contract_changed'
    metrics=effective_publication(db,batch)
    assert metrics['publication']['valid_issue_count']==197
    assert metrics['publication']['source_job_ids']==[101]
