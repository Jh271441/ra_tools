"""Formal-role publication invariants using real SQLite transactions and fake Trail."""
import copy
import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pytest

from ra_triage_dashboard.app.db import Database, LabelAnnotationConflictError, AnnotationConflictError
from ra_triage_dashboard.app.db_parts.role_version_tasks import sampled
from ra_triage_dashboard.app.human_label_policy import FIELDS, PRIORITY, allocate_role_pairs, effective_metric_label
from ra_triage_dashboard.app.human_publisher import HumanPublisher, qualified_capabilities
from ra_triage_dashboard.app.version_review_tasks import version_tasks, version_task_detail, version_task_baseline_ids


@pytest.fixture
def db(tmp_path):
    database=Database(tmp_path/'test.sqlite');database.init()
    for name in ['jasperchen','liangxianghui','yupuxue','zhangxuzhao','observer']:
        database.set_access_user(username=name,role='admin',actor='test')
    rid=database.ensure_version_stream('20261106','test')
    ids=['cn'+str(i) for i in range(1,61)]
    database.append_version_predictions(run_id=rid,rows=[dict(issue_id=i,model_label='误触发',model_confidence=.7,
        model_extra=dict(software_version='1.gen4-release-20261106.1')) for i in ids])
    policy=dict(sampling_policy='version_probability_v3',seed='a'*64)
    result=database.append_version_campaign_members(family='20261106',policy=policy,issue_ids=ids,current_target_ids=ids,batch_key='first',actor='test')
    database.ingest_version_dataset(family='20261106',policy=policy,items=[dict(issue_id=i,
        software_version='1.gen4-release-20261106.1',state='published',is_target=True,is_low=True,
        is_sample=sampled(policy['seed'],'20261106',i),binding=result['bindings'][i]) for i in ids],batch_key='packet',actor='test')
    database.refresh_human_publications(delay=0)
    yield database
    database.close()


def choose(db,cohort='low'):
    row=next(r for r in db.version_dataset_gallery_rows('release-20261106-odd2') if r['binding']['cohort']==cohort)
    return row['issue_id'], row['binding']


def context(db,iid,actor):
    human=db.human_label_context(iid)
    return db.combined_review_context(issue_id=iid,campaign_id=human['scope']['campaign_id'],reviewer=actor)


def submit(db,iid,actor,label='误触发',ctx=None,key=None,campaign_id=None):
    ctx=ctx or context(db,iid,actor)
    if not ctx['assigned']:
        return db.submit_review_case_label(issue_id=iid,reviewer=actor,reviewer_source='test',reviewer_verified=True,
            expected_output=label,tags=[],rationale='advisory opinion',expected_case_revision_id=ctx['case_revision_id'],
            expected_label_state_fingerprint=ctx['label_state_fingerprint'])
    return db.submit_combined_review(issue_id=iid,campaign_id=campaign_id or ctx['campaign']['id'],
        model_run_id=ctx['campaign']['evaluation_run_id'],reviewer=actor,reviewer_source='test',reviewer_verified=True,
        model_review_status='completed',reason='test review',missing_evidence=[],expected_output=label,tags=[],rationale='test label',
        expected_model_review_storage_id=ctx['model_review_storage_id'],expected_case_revision_id=ctx['case_revision_id'],
        expected_label_state_fingerprint=ctx['label_state_fingerprint'],idempotency_key=key or uuid4().hex)


def admit(db,iid,actor):
    ctx=db.human_label_context(iid);cid=ctx['scope']['campaign_id']
    with db.connect() as c:revision=c.execute('SELECT config_revision FROM issue_work_splits WHERE id=?',(cid,)).fetchone()['config_revision']
    return db.update_campaign_assignment(campaign_id=cid,issue_id=iid,action='assign',actor='jasperchen',actor_source='test',actor_verified=True,
        expected_revision=revision,idempotency_key=uuid4().hex,assignee=actor,assignment_kind='cross',reason='formally review objection')


def publication(db,iid,lane='rd'):
    with db.connect() as c:return dict(c.execute('SELECT * FROM human_publications WHERE issue_id=? AND lane=?',(iid,lane)).fetchone())


class Trail:
    def __init__(self):self.values={};self.writes=[];self.fail_read=False;self.timeout_after_write=False;self.after_write=None;self.reads=0
    def fetch(self,ids):
        self.reads+=1
        if self.fail_read:raise TimeoutError()
        return {i:copy.deepcopy(self.values.setdefault(i,{f:None for f in FIELDS.values()})) for i in ids}
    def update(self,lane,values):
        self.writes.append((lane,dict(values)))
        for i,v in values.items():self.values[i][FIELDS[lane]]=v
        if self.after_write:self.after_write()
        if self.timeout_after_write:raise TimeoutError()


def test_allocation_independent_balanced_and_append_stable(db):
    allocations=allocate_role_pairs([str(i) for i in range(1000)],sampled=True,seed='a'*64)
    counts=Counter(p for r in allocations for p in r['assignees'])
    assert set(counts.values())=={500}
    pairs=Counter(tuple(r['assignees']) for r in allocations)
    assert len(pairs)==4 and max(pairs.values())-min(pairs.values())<=2
    rows=db.version_dataset_gallery_rows('release-20261106-odd2')
    assert len(rows)==len({r['issue_id'] for r in rows})==60
    tasks=version_tasks(db);assert len(tasks)==2 and sum(t['total_count'] for t in tasks)==60
    for task in tasks:
        detail=version_task_detail(db,task['split_id'])
        assert detail['split_id']==task['split_id']
        assert version_task_baseline_ids(db,task['split_id'])==['version-20261106']
    result=db.append_version_campaign_members(family='20261106',policy=dict(sampling_policy='version_probability_v3',seed='a'*64),
        issue_ids=[r['issue_id'] for r in rows],current_target_ids=[r['issue_id'] for r in rows],batch_key='first',actor='test')
    assert result['added']==0
    assert {i['issue_id']:i['binding']['assignees'] for i in rows}=={i['issue_id']:i['binding']['assignees'] for i in db.version_dataset_gallery_rows('release-20261106-odd2')}
    # A genuinely new packet preserves old owners and balances cumulative quotas.
    rid=rows[0]['binding']['run_id'];fresh_ids=['cn'+str(i) for i in range(61,101)]
    db.append_version_predictions(run_id=rid,rows=[dict(issue_id=i,model_label='误触发',model_confidence=.7,
        model_extra=dict(software_version='1.gen4-release-20261106.1')) for i in fresh_ids])
    policy=dict(sampling_policy='version_probability_v3',seed='a'*64)
    added=db.append_version_campaign_members(family='20261106',policy=policy,issue_ids=fresh_ids,
        current_target_ids=[r['issue_id'] for r in rows]+fresh_ids,batch_key='second',actor='test')
    assert added['added']==40
    for row in rows:assert added['bindings'][row['issue_id']]['assignees']==row['binding']['assignees']
    db.ingest_version_dataset(family='20261106',policy=policy,items=[dict(issue_id=i,
        software_version='1.gen4-release-20261106.1',state='published',is_target=True,is_low=True,
        is_sample=sampled(policy['seed'],'20261106',i),binding=added['bindings'][i]) for i in fresh_ids],batch_key='second-packet',actor='test')
    assert len(db.version_dataset_gallery_rows('release-20261106-odd2'))==100
    for cohort in ['sampling','low']:
        counts=Counter(p for b in added['bindings'].values() if b['cohort']==cohort for p in b['assignees'])
        assert abs(counts['jasperchen']-counts['liangxianghui'])<=1
        if cohort=='sampling':assert abs(counts['yupuxue']-counts['zhangxuzhao'])<=1


@pytest.mark.parametrize('cohorts',[[],['sampling'],['sampling','low']])
def test_append_receipt_keeps_pinned_single_task_cron_compatible(tmp_path,cohorts):
    database=Database(tmp_path/'legacy-cron.sqlite');database.init()
    try:
        for name in ['jasperchen','liangxianghui','yupuxue','zhangxuzhao']:
            database.set_access_user(username=name,role='admin',actor='test')
        family='20261106';policy=dict(sampling_policy='version_probability_v3',seed='a'*64)
        ids=[next('cn'+str(i) for i in range(1,61) if sampled(policy['seed'],family,'cn'+str(i))==(cohort=='sampling')) for cohort in cohorts]
        rid=database.ensure_version_stream(family,'test')
        database.append_version_predictions(run_id=rid,rows=[dict(issue_id=i,model_label='误触发',model_confidence=.7,
            model_extra=dict(software_version='1.gen4-release-20261106.1')) for i in ids])
        args=dict(family=family,policy=policy,issue_ids=ids,current_target_ids=ids,batch_key='legacy-cron-packet',actor='test')
        result=database.append_version_campaign_members(**args)
        # The deployed bridge reads this exact key before TE/media callbacks.
        assert result['campaign_id']==(result['campaign_ids'][0] if len(cohorts)==1 else '')
        assert len(result['campaign_ids'])==len(cohorts)
        assert set(result['bindings'])==set(ids)
        for cohort,iid in zip(cohorts,ids):
            assert result['bindings'][iid]['campaign_id'].endswith('-'+cohort)
            assert len(result['bindings'][iid]['assignees'])==(2 if cohort=='sampling' else 1)
        repeated=database.append_version_campaign_members(**args)
        assert repeated['added']==0 and repeated['campaign_id']==result['campaign_id']
        assert repeated['bindings']==result['bindings']
    finally:database.close()


def test_single_owner_advisory_does_not_block_then_formal_admission_retracts(db,tmp_path):
    iid,b=choose(db);owner=b['assignee'];trail=Trail();publisher=HumanPublisher(db,tmp_path,trail,enabled=True)
    submit(db,iid,owner);publisher.tick(force_ids=[iid]);assert publication(db,iid)['sync_state']=='synced'
    before=publication(db,iid)
    submit(db,iid,'observer','无需协助');publisher.tick(force_ids=[iid])
    assert publication(db,iid)['generation']==before['generation']
    assert len(trail.writes)==1 and publication(db,iid)['objection_count']==1
    admit(db,iid,'observer');publisher.tick(force_ids=[iid])
    assert publication(db,iid)['conclusion']=='conflict'
    assert trail.values[iid][FIELDS['rd']] is None
    assert trail.writes[-1][1]=={iid:None}
    assert context(db,iid,owner)['progress']['case_label_acknowledged']


def test_supplement_cannot_complete_owners_task(db):
    iid,b=choose(db);submit(db,iid,'observer')
    assert db.human_label_context(iid)['lanes']['rd']['state']=='pending'
    assert not context(db,iid,b['assignee'])['progress']['case_label_acknowledged']


def test_two_required_same_role_wait_agree_and_conflict(db):
    iid,b=choose(db);admit(db,iid,'observer')
    submit(db,iid,b['assignee']);assert db.human_label_context(iid)['lanes']['rd']['state']=='pending'
    submit(db,iid,'observer');assert db.human_label_context(iid)['lanes']['rd']['state']=='resolved'
    submit(db,iid,'observer','无需协助');assert db.human_label_context(iid)['lanes']['rd']['state']=='conflict'


def test_independent_role_submissions_do_not_invalidate_each_others_drafts(db,tmp_path):
    iid,b=choose(db,'sampling');rd,te=b['assignees']
    rd_ctx=context(db,iid,rd);te_ctx=context(db,iid,te)
    submit(db,iid,rd,ctx=rd_ctx);submit(db,iid,te,'无需协助',ctx=te_ctx)
    human=db.human_label_context(iid)
    assert human['lanes']['rd']['label']=='误触发' and human['lanes']['te']['label']=='无需协助'
    trail=Trail();HumanPublisher(db,tmp_path,trail,enabled=True).tick(force_ids=[iid])
    assert trail.values[iid][FIELDS['rd']]=='误触发' and trail.values[iid][FIELDS['te']]=='无需协助'
    assert next(r for r in db.version_dataset_gallery_rows('release-20261106-odd2') if r['issue_id']==iid)['review_submitted']
    with pytest.raises((LabelAnnotationConflictError,AnnotationConflictError)):submit(db,iid,rd,'正确触发',ctx=rd_ctx)


def test_role_edits_preserve_historical_vote_and_assignment_role(db):
    iid,b=choose(db);submit(db,iid,b['assignee'])
    db.set_access_user(username=b['assignee'],role='admin',actor='test',annotation_role='te')
    assert db.human_label_context(iid)['lanes']['rd']['state']=='resolved'
    submit(db,iid,b['assignee'],'无需协助')
    assert db.human_label_context(iid)['lanes']['rd']['state']=='pending'


def test_existing_final_adjudication_binds_only_formal_sources(db,tmp_path):
    iid,b=choose(db);submit(db,iid,b['assignee']);human=db.human_label_context(iid)
    result=db.adjudicate_issue_label(baseline_scope=human['scope']['baseline_scope'],issue_id=iid,expected_output='正确触发',rationale='explicit decision',
        actor='jasperchen',actor_source='test',actor_verified=True,expected_source_fingerprint=human['source_fingerprint'])
    trail=Trail();p=HumanPublisher(db,tmp_path,trail,enabled=True);p.tick(force_ids=[iid])
    assert trail.values[iid][FIELDS['arbitrated']]=='成功'
    submit(db,iid,'observer','无需协助');p.tick(force_ids=[iid])
    assert db.human_label_context(iid)['lanes']['arbitrated']['state']=='resolved'
    projection=db.project_issue_label_states(human['scope']['baseline_scope'],[iid])[iid]
    assert projection['decision']['id']==result['decision']['id'] and not projection['decision']['stale']
    submit(db,iid,b['assignee'],'无需协助');p.tick(force_ids=[iid])
    assert publication(db,iid,'arbitrated')['conclusion']=='stale'
    assert trail.values[iid][FIELDS['arbitrated']] is None


def test_write_timeout_reads_before_retry_and_restart_recovery(db,tmp_path):
    iid,b=choose(db);submit(db,iid,b['assignee']);trail=Trail();trail.timeout_after_write=True
    p=HumanPublisher(db,tmp_path,trail,enabled=True);p.tick(force_ids=[iid])
    assert len(trail.writes)==1 and publication(db,iid)['sync_state']=='synced'
    submit(db,iid,b['assignee'],'正确触发');trail.after_write=lambda:setattr(trail,'fail_read',True)
    p.tick(force_ids=[iid]);assert publication(db,iid)['sync_state']=='unverified'
    trail.fail_read=False;trail.after_write=None
    HumanPublisher(db,tmp_path,trail,enabled=True).tick()
    assert len(trail.writes)==2 and publication(db,iid)['sync_state']=='synced'


def test_newer_submission_during_remote_io_is_compensated(db,tmp_path):
    iid,b=choose(db);submit(db,iid,b['assignee']);trail=Trail()
    def change():trail.after_write=None;submit(db,iid,b['assignee'],'无需协助')
    trail.after_write=change;p=HumanPublisher(db,tmp_path,trail,enabled=True);p.tick(force_ids=[iid])
    assert publication(db,iid)['sync_state']=='pending'
    p.tick(force_ids=[iid]);assert trail.values[iid][FIELDS['rd']]=='无需协助'
    assert publication(db,iid)['sync_state']=='synced'


def test_external_equal_value_never_gives_clear_ownership(db,tmp_path):
    iid,b=choose(db);submit(db,iid,b['assignee']);trail=Trail();trail.fetch([iid]);trail.values[iid][FIELDS['rd']]='误触发'
    p=HumanPublisher(db,tmp_path,trail,enabled=True);p.tick(force_ids=[iid])
    assert publication(db,iid)['sync_state']=='same' and not publication(db,iid)['owned']
    admit(db,iid,'observer');submit(db,iid,'observer','正确触发');p.tick(force_ids=[iid])
    assert not trail.writes and trail.values[iid][FIELDS['rd']]=='误触发'


def test_external_change_and_disable_fail_closed(db,tmp_path):
    iid,b=choose(db);submit(db,iid,b['assignee']);trail=Trail()
    p=HumanPublisher(db,tmp_path,trail);p.tick(force_ids=[iid]);assert not trail.writes and not trail.reads
    p.enabled=True;p.tick(force_ids=[iid]);trail.values[iid][FIELDS['rd']]='无需协助'
    submit(db,iid,b['assignee'],'正确触发');p.tick(force_ids=[iid])
    assert publication(db,iid)['sync_state']=='needs_recheck' and len(trail.writes)==1


def test_scope_invalidation_is_durable(db,tmp_path):
    iid,b=choose(db);submit(db,iid,b['assignee']);trail=Trail();p=HumanPublisher(db,tmp_path,trail,enabled=True);p.tick(force_ids=[iid])
    with db.connect() as c:c.execute('UPDATE human_label_scopes SET active=0 WHERE issue_id=?',(iid,))
    db.refresh_human_publications(delay=0);p.tick()
    assert trail.values[iid][FIELDS['rd']] is None


def test_withdrawal_and_suppression_recompute_without_deleting_history(db,tmp_path):
    iid,b=choose(db);owner=b['assignee'];saved=submit(db,iid,owner)
    trail=Trail();publisher=HumanPublisher(db,tmp_path,trail,enabled=True);publisher.tick(force_ids=[iid])
    withdrawn=db.create_label_revision(issue_id=iid,expected_output='',tags=[],evidence_gaps=[],rationale='Withdraw my label',
        is_excluded=False,author=owner,author_source='test',author_verified=True,expected_previous_revision_id=saved['case_revision_id'])
    db.refresh_human_publications(delay=0);publisher.tick()
    assert publication(db,iid)['conclusion']=='pending' and trail.values[iid][FIELDS['rd']] is None
    # Suppressing an imported/replaced revision restores the preceding effective head.
    with db.connect() as conn:
        scope=db.human_label_context(iid,connection=conn)['scope']['baseline_scope']
        conn.execute("""INSERT INTO label_import_batches(id,baseline_scope,name,source_type,migration_version,status,
            source_inventory_sha256,imported_by,created_at,imported_at)
            VALUES('suppression-test',?,'test','legacy_model_review','test','imported',?,'test','2026-11-12T00:00:00Z','2026-11-12T00:00:00Z')""",(scope,'a'*64))
        conn.execute("INSERT INTO label_import_suppressed_revisions(batch_id,revision_id,created_at) VALUES('suppression-test',?,'2026-11-12T00:00:00Z')",(withdrawn['id'],))
    db.refresh_human_publications(delay=0);publisher.tick()
    assert trail.values[iid][FIELDS['rd']]=='误触发'
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM label_revisions WHERE label_case_id=?',(withdrawn['label_case_id'],)).fetchone()['n']==2


@pytest.mark.parametrize('sdk_scheme', ['http', 'https'])
def test_http_budget_covers_every_query_page_and_write(monkeypatch, sdk_scheme):
    from types import SimpleNamespace
    from ra_triage_dashboard.app import human_publisher as worker,rd_results
    clock=[100.0];events=[]
    monkeypatch.setattr(worker.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(worker.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    response=SimpleNamespace(raise_for_status=lambda:None)
    class Transport:
        client=SimpleNamespace(_post_headers=lambda url:{})
        def send_request(self,url,data,timeout=None):
            assert url==worker.QUERY_ENDPOINT
            events.append((clock[0],'read'));return response
    class Adapter:
        client=Transport()
        def fetch(self,ids):
            # Pagination inside the reused SDK must not bypass the rate limit.
            for page in range(2):self.client.send_request(worker.QUERY_ENDPOINT.replace('https://',sdk_scheme+'://',1),dict(page=page))
            return [dict(issue_id=i,**{f:None for f in FIELDS.values()}) for i in ids]
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            events.append((clock[0],'write'))
            assert url==worker.ENDPOINT and kwargs['json']['issue_info']=={'cn1':{FIELDS['te']:None}}
            assert not self.trust_env and not kwargs['allow_redirects']
            return response
    monkeypatch.setattr(rd_results,'adapter',lambda root:Adapter())
    monkeypatch.setattr('requests.Session',Session)
    client=worker.HumanTrailClient('unused',dict(fields={f:{} for f in FIELDS.values()}))
    client.fetch(['cn1']);client.update('te',{'cn1':None});client.fetch(['cn1'])
    assert len(events)==5 and all(b[0]-a[0]>=1 for a,b in zip(events,events[1:]))
    for ids in [[],['cn1','cn1'],['../../cn1'],['cn1']*21]:
        with pytest.raises(ValueError):client.fetch(ids)
    for lane,values in [('rd',{'bad':None}),('auto',{'cn1':'成功'}),('rd',{'cn1':''})]:
        with pytest.raises(ValueError):client.update(lane,values)
    for url in ['https://other.example/paladin/issue/pool/query/',worker.QUERY_ENDPOINT+'?redirect=1',worker.ENDPOINT]:
        with pytest.raises(ValueError):client.delegate.client.send_request(url,{})
    assert len(events)==5


def test_null_priority_and_capability_gate(tmp_path):
    from ra_triage_dashboard.app.human_publisher import ENDPOINT
    values={f:None for f in PRIORITY};values['ra_result']='TO';assert effective_metric_label(values)['field']=='ra_result'
    for field in reversed(PRIORITY):
        values[field]=field;assert effective_metric_label(values)['field']==field
    values[PRIORITY[0]]='';assert effective_metric_label(values)['value']==''
    del values[PRIORITY[0]];assert effective_metric_label(values)['state']=='unknown'
    with pytest.raises(ValueError):qualified_capabilities(None)
    path=tmp_path/'receipt.json';path.write_text('{}');path.chmod(0o600)
    with pytest.raises(ValueError):qualified_capabilities(path)
    receipt=dict(endpoint=ENDPOINT,qualified=True,evidence=[{'synthetic':True}],priority=list(PRIORITY),priority_verified=True,
                 external_metrics_verified=False,fields={field:dict(values=['成功','误触发','无需协助'],null_clear=True,metric_null_fallback=False) for field in FIELDS.values()})
    path.write_text(json.dumps(receipt))
    assert qualified_capabilities(path)['external_metrics_verified'] is False
    for invalid in [dict(priority_verified=False),dict(priority=list(reversed(PRIORITY)))]:
        path.write_text(json.dumps(dict(receipt,**invalid)))
        with pytest.raises(ValueError):qualified_capabilities(path)
    receipt['fields'][FIELDS['rd']]['null_clear']=False
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):qualified_capabilities(path)


def test_manual_queue_preview_commit_stale_and_idempotent(db):
    from ra_triage_dashboard.app.human_publication_queue import preview,enqueue
    iid,b=choose(db);submit(db,iid,b['assignee'])
    args=dict(lane='rd',issue_ids=[iid],datasets=['release-20261106-odd2'],actor='jasperchen')
    first=preview(db,**args)
    submit(db,iid,b['assignee'],'正确触发')
    with pytest.raises(ValueError,match='changed'):enqueue(db,request_id=first['id'],actor='jasperchen')
    second=preview(db,**args)
    assert enqueue(db,request_id=second['id'],actor='jasperchen')['queued']==1
    assert enqueue(db,request_id=second['id'],actor='jasperchen')['replayed']
    with pytest.raises(ValueError):enqueue(db,request_id=second['id'],actor='observer')
    with pytest.raises(ValueError):preview(db,**{**args,'datasets':['release-20261113-odd2']})
    expired=preview(db,**args)
    with db.connect() as conn:conn.execute('UPDATE human_publication_requests SET expires_at=0 WHERE id=?',(expired['id'],))
    with pytest.raises(ValueError,match='expired'):enqueue(db,request_id=expired['id'],actor='jasperchen')


def test_recovery_backoff_is_bounded_and_blocks_duplicate_writes(db,tmp_path,monkeypatch):
    import ra_triage_dashboard.app.human_publisher as worker
    iid,b=choose(db);submit(db,iid,b['assignee']);trail=Trail()
    trail.after_write=lambda:setattr(trail,'fail_read',True)
    p=HumanPublisher(db,tmp_path,trail,enabled=True);p.tick(force_ids=[iid])
    initial_writes=len(trail.writes)
    clock=[2000000000.0];monkeypatch.setattr(worker.time,'time',lambda:clock[0])
    for n in range(5):
        p.tick();reads=trail.reads;p.tick();assert trail.reads==reads
        clock[0]+=4000
    reads=trail.reads
    for _ in range(4):clock[0]+=4000;p.tick()
    assert trail.reads==reads and len(trail.writes)==initial_writes
    assert publication(db,iid)['sync_state']=='needs_recheck'


def test_failed_transaction_has_no_vote_or_work_and_shared_lock_serializes(db,tmp_path):
    iid,b=choose(db)
    with db.connect() as conn:before=conn.execute('SELECT COUNT(*) AS n FROM label_revisions').fetchone()['n']
    with pytest.raises(RuntimeError):
        with db._write_lock,db.connect() as conn:
            db._human_dirty(conn,iid)
            raise RuntimeError('rollback')
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM label_revisions').fetchone()['n']==before
        assert conn.execute('SELECT 1 FROM human_label_dirty WHERE issue_id=?',(iid,)).fetchone() is None
    submit(db,iid,b['assignee']);trail=Trail();p=HumanPublisher(db,tmp_path,trail,enabled=True)
    with p.lock() as acquired:
        assert acquired
        assert HumanPublisher(db,tmp_path,trail,enabled=True).tick(force_ids=[iid])['state']=='busy'
    assert not trail.writes


def test_legacy_rd_publication_cannot_bypass_formal_roles(db):
    from ra_triage_dashboard.app.rd_results import local_rows,classify
    iid,b=choose(db);submit(db,iid,b['assignee'])
    row=local_rows(db,[iid])[iid]
    assert row['human_managed'] and classify(row,{FIELDS['rd']:None})=='blocked'


def test_manual_routes_auth_flags_pagination_and_no_remote_io(db,monkeypatch):
    from fastapi import FastAPI,HTTPException
    from ra_triage_dashboard.tests.test_rd_results import AsgiClient
    from types import SimpleNamespace
    from ra_triage_dashboard.app.routers import human_publications as routes
    monkeypatch.setattr(routes,'database',db)
    monkeypatch.setattr(routes,'settings',SimpleNamespace(human_label_write_enabled=False,human_label_capabilities_file=None))
    actor=SimpleNamespace(username='jasperchen')
    monkeypatch.setattr(routes,'_writer_identity',lambda req:actor)
    monkeypatch.setattr(routes,'_admin_identity',lambda req:actor)
    app=FastAPI();app.include_router(routes.router);client=AsgiClient(app)
    url='/api/human-publications?baselines=version-20261106'
    response=client.get(url);assert response.status_code==200 and response.json()['total']==60
    assert client.get(url+'&page=0').status_code==409
    assert client.get(url+'&page_size=200').status_code==409
    iid,b=choose(db);submit(db,iid,b['assignee'])
    body=dict(lane='rd',baselines='version-20261106',issue_ids=[iid])
    assert client.post('/api/human-publications/preview',json=body).status_code==403
    headers={'X-RA-Triage-Request':'dashboard'}
    # The marker helper is tested separately; verify this route does invoke it.
    monkeypatch.setattr(routes,'has_same_origin_mutation_marker',lambda req:req.headers.get('X-RA-Triage-Request')=='dashboard')
    response=client.post('/api/human-publications/preview',json=body,headers=headers);assert response.status_code==200
    assert client.post('/api/human-publications/commit',json=dict(request_id=response.json()['id'],confirmed=True),headers=headers).status_code==403
    def denied(req):raise HTTPException(403,'denied')
    monkeypatch.setattr(routes,'_admin_identity',denied)
    assert client.post('/api/human-publications/preview',json=body,headers=headers).status_code==403


def test_audited_legacy_cutover_preserves_votes_owners_links_and_does_not_backfill(tmp_path,monkeypatch):
    from ra_triage_dashboard.app.human_label_migration import migration_plan,apply_migration,arm_migrated_sources
    database=Database(tmp_path/'legacy.sqlite');database.init()
    try:
        for person in ['jasperchen','liangxianghui','yupuxue','zhangxuzhao','legacy_rd']:
            database.set_access_user(username=person,role='admin',actor='test')
        rid=database.ensure_version_stream('20261106','test');ids=['cn'+str(i) for i in range(1,41)]
        database.append_version_predictions(run_id=rid,rows=[dict(issue_id=i,model_label='误触发',model_confidence=.7,
            model_extra=dict(software_version='1.gen4-release-20261106.1')) for i in ids])
        with database.connect() as c:scope=c.execute('SELECT baseline_scope FROM issues WHERE issue_id=?',(ids[0],)).fetchone()['baseline_scope']
        database.set_labeling_scope_state(baseline_scope=scope,status='active',policy_version='legacy',source_inventory_sha256='a'*64,updated_by='test')
        ws=database.create_review_workset(baseline_scope=scope,issue_ids=ids,selection_source_run_id=rid,created_by='test')
        snap=database.create_label_result_snapshot(workset_id=ws['id'],created_by='test',allow_partial=True)
        owners={i:['jasperchen','liangxianghui'][n%2] for n,i in enumerate(ids)}
        owners[ids[-1]]='legacy_rd'
        old=database.create_campaign(spec=dict(purpose='model_review',workflow_mode='model_review_and_case_label',evaluation_run_id=rid,
            workset_id=ws['id'],name='legacy 1106',reference_type='label_result_snapshot',reference_id=snap['id'],
            members=[dict(issue_id=i,assignees=[owners[i]]) for i in ids]),actor='jasperchen',actor_source='test',actor_verified=True,idempotency_key='old')['campaign']
        policy=dict(sampling_policy='version_probability_v3',seed='a'*64)
        database.ingest_version_dataset(family='20261106',policy=policy,items=[dict(issue_id=i,software_version='1.gen4-release-20261106.1',
            state='published',is_target=True,is_low=True,is_sample=sampled(policy['seed'],'20261106',i),
            binding=dict(run_id=rid,campaign_id=old['id'],assignee=owners[i])) for i in ids],batch_key='legacy-packet',actor='test')
        ctx=database.combined_review_context(issue_id=ids[0],campaign_id=old['id'],reviewer=owners[ids[0]])
        saved=submit(database,ids[0],owners[ids[0]],ctx=ctx,key='legacy-submit')
        with database.connect() as c:
            c.execute('DELETE FROM human_vote_roles')
            votes_before=[dict(r) for r in c.execute('SELECT * FROM label_revisions').fetchall()]
            models_before=[dict(r) for r in c.execute('SELECT * FROM model_review_revisions').fetchall()]
        did='release-20261106-odd2';plan=migration_plan(database,did)
        assert not plan['blocked'] and len(plan['missing_role_evidence'])==1
        with pytest.raises(ValueError,match='classification'):
            apply_migration(database,dataset_id=did,expected_fingerprint=plan['fingerprint'],backup_sha256='a'*64,actor='jasperchen')
        with database.connect() as c:c.execute("UPDATE issue_work_splits SET campaign_name='inventory drift' WHERE id=?",(old['id'],))
        with pytest.raises(ValueError,match='inventory changed'):
            apply_migration(database,dataset_id=did,expected_fingerprint=plan['fingerprint'],backup_sha256='a'*64,actor='jasperchen',historical_role='rd')
        with database.connect() as c:c.execute('UPDATE issue_work_splits SET campaign_name=? WHERE id=?',(old['name'],old['id']))
        event=database._version_event
        def fail_receipt(conn,did,key,action,detail,actor):
            if action=='role_task_cutover':raise RuntimeError('Simulated receipt failure')
            return event(conn,did,key,action,detail,actor)
        with monkeypatch.context() as patch:
            patch.setattr(database,'_version_event',fail_receipt)
            with pytest.raises(RuntimeError,match='receipt failure'):
                apply_migration(database,dataset_id=did,expected_fingerprint=plan['fingerprint'],backup_sha256='a'*64,actor='jasperchen',historical_role='rd')
        assert migration_plan(database,did)['fingerprint']==plan['fingerprint']
        with database.connect() as c:assert c.execute('SELECT COUNT(*) AS n FROM human_version_tasks').fetchone()['n']==0
        receipt=apply_migration(database,dataset_id=did,expected_fingerprint=plan['fingerprint'],backup_sha256='a'*64,actor='jasperchen',historical_role='rd')
        assert not receipt['historical_publication_armed']
        assert apply_migration(database,dataset_id=did,expected_fingerprint=plan['fingerprint'],backup_sha256='a'*64,actor='jasperchen',historical_role='rd')['replayed']
        after=database.combined_review_context(issue_id=ids[0],campaign_id=old['id'],reviewer=owners[ids[0]])
        assert after['model_review_storage_id']==saved['model_review_storage_id'] and after['progress']['case_label_acknowledged']
        assert after['campaign']['id']!=old['id']
        with database.connect() as c:
            assert [dict(r) for r in c.execute('SELECT * FROM label_revisions').fetchall()]==votes_before
            assert [dict(r) for r in c.execute('SELECT * FROM model_review_revisions').fetchall()]==models_before
            assert c.execute('SELECT lifecycle FROM issue_work_splits WHERE id=?',(old['id'],)).fetchone()['lifecycle']=='superseded'
        assert submit(database,ids[0],owners[ids[0]],ctx=ctx,key='legacy-submit')['duplicate']
        # New requests through archived case URLs also replay in their redirected task.
        new=submit(database,ids[0],owners[ids[0]],'无需协助',ctx=after,key='redirect-submit',campaign_id=old['id'])
        replay=submit(database,ids[0],owners[ids[0]],'无需协助',ctx=after,key='redirect-submit',campaign_id=old['id'])
        assert replay['duplicate'] and replay['submission_group_id']==new['submission_group_id']
        for row in database.version_dataset_gallery_rows(did):assert row['binding']['assignee']==owners[row['issue_id']]
        trail=Trail();publisher=HumanPublisher(database,tmp_path,trail,enabled=True)
        publisher.tick(force_ids=ids);assert not trail.writes
        arm_migrated_sources(database,dataset_id=did,source_fingerprint=plan['fingerprint'],actor='jasperchen')
        publisher.tick(force_ids=ids);assert trail.writes
        assert len(version_tasks(database))==2
    finally:database.close()
