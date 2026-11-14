from copy import deepcopy
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from app.models import ReleaseWorkflowState
from app.services import evaluation_pipeline as p, metric_profiles as profiles, auto_triage_metrics as at, release_workflow as w
from app.services import evaluation_samples as samples
from app.services.release_cycle import digest
from test_auto_triage_metrics import db, prepared, RELEASE


def seed(prepared, monkeypatch):
    db, snapshot, batch, labels = prepared
    at.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    samples.migrate(db)
    monkeypatch.setattr(w, 'effective_config', lambda db: {'simulation': {'driver_command': ['stub']}})
    value = p.recalculate(db, RELEASE)
    return db, snapshot, batch, labels, value


def test_builtin_matches_verified_sql_and_never_submits(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    old = at.report(db, RELEASE)['result']['metrics']
    for metric, key in [('online_precision', 'online_precision'), ('online_recall', 'online_recall'), ('precision','precision'),('recall','recall')]:
        assert value['metrics'][metric] == old[key]
    assert value['metrics']['counts'] == { 'precision_numerator': old['precision_auto_tp'], 'precision_denominator': old['precision_denominator'], 'recall_numerator': old['recall_auto_tp'], 'recall_denominator': old['recall_denominator'] }
    assert value['metrics']['available'] is False
    assert p.board(db, RELEASE)['plan']['prepare_count'] == 1
    assert p.recalculate(db, RELEASE)['revision_key'] == value['revision_key']
    assert not p.rows(db, 'evexecution:')


def test_warmup_change_invalidates_reuse_without_changing_historical_metrics(prepared, monkeypatch):
    db, snapshot, batch, labels, original = seed(prepared, monkeypatch)
    before_batch, before_snapshot = deepcopy(batch.payload), deepcopy(snapshot.payload)
    assert original['metrics']['covered'] > 0
    monkeypatch.setattr(w, 'effective_config', lambda db: {
        'simulation': {'driver_command': ['stub'], 'warmup_ms_by_release': {RELEASE: 15000}}})
    assert p.board(db, RELEASE)['stale']
    revised = p.recalculate(db, RELEASE)
    assert revised['revision_key'] != original['revision_key']
    assert revised['specification']['simulation']['warmup_ms'] == 15000
    assert revised['metrics']['covered'] == 0
    assert revised['metrics']['counts'] == original['metrics']['counts']
    assert revised['metrics']['recall'] is None and revised['metrics']['covered_recall'] is None
    assert not revised['lineage']
    assert not p.board(db, RELEASE)['stale']
    assert p.board(db, RELEASE)['plan']['manual_start_required']
    assert batch.payload == before_batch and snapshot.payload == before_snapshot
    assert w.get_state(db, original['revision_key'])['metrics'] == original['metrics']
    assert not p.rows(db, 'evexecution:')


def test_new_warmup_reuses_only_its_own_audited_execution(prepared, monkeypatch):
    db, snapshot, batch, labels, original = seed(prepared, monkeypatch)
    monkeypatch.setattr(w, 'effective_config', lambda db: {
        'simulation': {'driver_command': ['stub'], 'warmup_ms_by_release': {RELEASE: 15000}}})
    revised = p.recalculate(db, RELEASE)
    source = revised['payload']
    scene = next(s for s in source['scenarios'] if s['issue_id'] == 'a')
    issue = next(i for i in source['issues'] if i['issue_id'] == 'a')
    execution = {'id': 'new-warmup', 'status': 'complete', 'job_id': 9000,
                 'created_at': p.now(), 'plan': {**revised['specification'], 'release': RELEASE,
                    'scenarios': [scene], 'issues': [issue]},
                 'results': {scene['scenario_id']: {'sim_triggered': False}},
                 'export': {'execution_contract_hash': 'warmup-runtime'}}
    execution['audit_hash'] = p.execution_audit_hash(execution)
    w.put_state(db, 'evexecution:' + execution['id'], execution)
    updated = p.recalculate(db, RELEASE)
    assert updated['metrics']['covered'] == 1
    assert set(updated['lineage']) == {scene['scenario_id']}
    assert updated['lineage'][scene['scenario_id']]['job_id'] == 9000
    row = next(r for r in updated['rows'] if r['issue_id'] == 'a')
    assert row['sim_triggered'] is False and row['result_status'] == 'reused'
    assert original['metrics']['covered'] > 1
    assert w.get_state(db, original['revision_key'])['metrics'] == original['metrics']


def test_native_feature_policy_makes_a_separate_manual_plan(prepared, monkeypatch):
    db, snapshot, batch, labels, original = seed(prepared, monkeypatch)
    monkeypatch.setattr(w, 'effective_config', lambda db: {
        'simulation': {'driver_command': ['stub'], 'feature_history_by_release': {RELEASE: 'release-native'}}})
    assert p.board(db, RELEASE)['stale']
    revised = p.recalculate(db, RELEASE)
    assert revised['specification']['simulation']['feature_history'] == 'release-native'
    assert revised['metrics']['counts'] == original['metrics']['counts']
    assert revised['metrics']['covered'] == 0 and not revised['lineage']
    assert p.board(db, RELEASE)['plan']['manual_start_required']
    assert w.get_state(db, original['revision_key'])['metrics'] == original['metrics']
    assert not p.rows(db, 'evexecution:')


@pytest.mark.parametrize('missing_bag', [False, True])
def test_parameter_change_keeps_scene_preparation_but_requires_new_results(prepared, monkeypatch, missing_bag):
    db, snapshot, batch, labels, original = seed(prepared, monkeypatch)
    issue = next(i for i in original['payload']['issues'] if i['issue_id'] == 'c')
    scene = {'scenario_id': 's-c', 'issue_id': 'c', 'scenario_revision': 1,
             'start_timestamp': 0, 'end_timestamp': 10000}
    p.save_preparation(db, original, [issue], {
        'ready': not missing_bag, 'prepared': 0 if missing_bag else 1, 'failed': int(missing_bag),
        'scenarios': [] if missing_bag else [scene],
        'failures': [{'issue_id': 'c', 'reason': 'missing_bag'}] if missing_bag else []})
    monkeypatch.setattr(w, 'effective_config', lambda db: {
        'simulation': {'driver_command': ['stub'], 'warmup_ms_by_release': {RELEASE: 15000},
                       'feature_history_by_release': {RELEASE: 'release-native'}}})
    revised = p.recalculate(db, RELEASE)
    assert revised['metrics']['covered'] == 0 and not revised['lineage']
    row = next(r for r in revised['rows'] if r['issue_id'] == 'c')
    if missing_bag:
        assert row['result_status'] == 'missing_bag' and row['scenario_ids'] == []
    else:
        assert row['scenario_ids'] == ['s-c'] and row['result_status'] == 'missing_result'
        assert next(s for s in revised['payload']['scenarios'] if s['issue_id'] == 'c') == scene
    assert revised['preparations'] and not p.rows(db, 'evexecution:')
    assert w.get_state(db, original['revision_key'])['metrics'] == original['metrics']


def test_scene_preparation_does_not_cross_binary_or_input_contracts():
    original = {'period': {'case_start': '2026-10-16'}, 'binary_id': 123, 'driver_revision': 'v1',
                'simulation': {'recovery_mode': 'baseline'}}
    changed = deepcopy(original)
    changed['simulation'].update(warmup_ms=15000, feature_history='release-native')
    assert p.same_scene_preparation(original, changed)
    changed['binary_id'] = 124
    assert not p.same_scene_preparation(original, changed)
    changed['binary_id'] = 123
    changed['period']['case_start'] = '2026-10-17'
    assert not p.same_scene_preparation(original, changed)


@pytest.mark.parametrize('warmup', [-1, 60001, True, '15000'])
def test_invalid_warmup_configuration_cannot_create_new_revision(prepared, monkeypatch, warmup):
    db, snapshot, batch, labels, original = seed(prepared, monkeypatch)
    monkeypatch.setattr(w, 'effective_config', lambda db: {
        'simulation': {'driver_command': ['stub'], 'warmup_ms_by_release': {RELEASE: warmup}}})
    with pytest.raises(ValueError, match='simulation_warmup_invalid'):
        p.recalculate(db, RELEASE)
    assert p.current_revision(db, RELEASE)['revision_key'] == original['revision_key']
    assert not p.rows(db, 'evexecution:')


@pytest.mark.parametrize('label,expected', [(None,(0,0)),('',(0,1)),('正确触发',(0,1)),('成功',(1,1))])
def test_rules_retain_null_empty_and_literal_label(label, expected):
    flags = profiles.membership(profiles.DEFAULT_CONFIG, 2, label)
    assert (flags['precision_numerator'], flags['precision_denominator']) == expected
    if label == '正确触发':
        assert flags['recall_numerator'] == 1


def test_profile_preview_publish_reprojects_without_execution(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    original_batch, original_snapshot = deepcopy(batch.payload), deepcopy(snap.payload)
    config = deepcopy(profiles.DEFAULT_CONFIG)
    config['label']['mapping'] = {'正确触发': '成功'}
    draft = profiles.draft(db, config, 'Explicit mapping', 'Reviewed mapping')
    preview = p.preview(db, draft['id'], RELEASE)
    assert preview['changed_labels'] == 1
    assert preview['metrics']['counts']['precision_numerator'] == value['metrics']['counts']['precision_numerator'] + 1
    monkeypatch.setattr(at.warehouse,'fetch',lambda *a, **k: pytest.fail('Publication must use its verified preview'))
    published = profiles.publish(db, draft['id'], preview['preview_hash'])
    assert published['status'] == 'published' and profiles.get(db)['id'] == published['id']
    view = p.board(db, RELEASE, published['id'])
    assert view['revision']['metrics'] == preview['metrics']
    assert view['plan']['manual_start_required']
    again = p.recalculate(db, RELEASE, published['id'])
    assert again['metrics'] == preview['metrics']
    assert batch.payload == original_batch and snap.payload == original_snapshot
    assert not p.rows(db, 'evexecution:')
    assert profiles.get(db, 'auto_triage_sql_v2')['config']['label']['mapping'] == {}


def test_invalid_rules_and_publish_without_preview(db):
    config = deepcopy(profiles.DEFAULT_CONFIG)
    config['memberships']['precision_denominator']['exclude'].append('成功')
    with pytest.raises(ValueError, match='numerator_outside'):
        profiles.validate(config)
    config = deepcopy(profiles.DEFAULT_CONFIG)
    config['sql'] = 'drop table issues'
    with pytest.raises(ValueError, match='schema'):
        profiles.validate(config)
    draft = profiles.draft(db, profiles.DEFAULT_CONFIG, 'Draft', 'reason')
    with pytest.raises(ValueError, match='preview_required'):
        profiles.publish(db, draft['id'], 'missing')


def test_range_isolation_and_no_primary_job(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    assert not p.board(db, RELEASE, date_start='2026-01-01', date_end='2026-01-02')['revision']
    monkeypatch.setattr(at, '_base', lambda *_: None)
    fresh = p.recalculate(db, RELEASE, 'auto_triage_sql_v2')
    assert fresh['metrics']['eligible'] == value['metrics']['eligible']
    assert fresh['metrics']['covered'] == 0
    assert p.board(db, RELEASE)['plan']['gap_count'] == fresh['metrics']['eligible']
    assert not p.rows(db, 'evexecution:')


def test_stale_plan_and_manual_exclusion_block_before_side_effect(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    plan = p.board(db, RELEASE)['plan']
    changed = deepcopy(snap.payload)
    changed['issues'][0]['ra_start_timestamp'] += 1
    snap.payload = changed
    db.commit()
    with pytest.raises(ValueError, match='plan_stale'):
        p.start(db, plan['id'])
    assert not p.rows(db, 'evstart:')


def test_user_exclusion_remains_in_road_counts_and_blocks_start(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    changed = deepcopy(snap.payload)
    changed['issues'][0]['evaluation_exclusion'] = {'approved_by': 'user', 'reason': 'review'}
    snap.payload = changed
    db.commit()
    at.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    revision = p.recalculate(db, RELEASE)
    assert revision['metrics']['counts'] == value['metrics']['counts']
    plan = p.board(db, RELEASE)['plan']
    assert plan['review_count'] == 1
    with pytest.raises(ValueError, match='requires_user_review'):
        p.start(db, plan['id'])


def test_source_failure_retains_prior_revision(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    monkeypatch.setattr(at.warehouse, 'fetch', lambda *a, **k: (_ for _ in ()).throw(ValueError('dashboard_login_required')))
    with pytest.raises(ValueError, match='offline_sample_update_required'):
        p.recalculate(db, RELEASE, refresh_labels=True)
    assert p.board(db, RELEASE)['revision']['revision_key'] == value['revision_key']


def test_execution_signal_requires_every_scenario(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    row = deepcopy(next(r for r in value['rows'] if r['issue_id'] == 'a'))
    row.update(result_status='missing_result', sim_triggered=None)
    m = p.summarize([row], profiles.DEFAULT_CONFIG)
    assert m['covered'] == 0 and m['precision'] is None and m['recall'] is None


def test_paired_road_counts_exclude_exactly_the_uncovered_issues():
    rows = [
        {'ra_type': 2, 'auto_label': '成功', 'result_status': 'reused', 'sim_triggered': True},
        {'ra_type': 2, 'auto_label': '误触发', 'result_status': 'reused', 'sim_triggered': False},
        {'ra_type': 3, 'auto_label': '成功', 'result_status': 'reused', 'sim_triggered': True},
        {'ra_type': 3, 'auto_label': '成功', 'result_status': 'missing_result', 'sim_triggered': None},
        {'ra_type': 2, 'auto_label': '成功', 'result_status': 'missing_scenario', 'sim_triggered': None},
    ]
    m = p.summarize(rows, profiles.DEFAULT_CONFIG)
    assert (m['covered'], m['eligible'], m['road_matches']) == (3, 5, 1)
    assert m['covered_source_counts'] == {'precision_numerator': 1, 'precision_denominator': 2,
                                          'recall_numerator': 1, 'recall_denominator': 2}
    assert m['counts'] == {'precision_numerator': 2, 'precision_denominator': 3,
                           'recall_numerator': 2, 'recall_denominator': 4}
    assert m['covered_repro_rate'] == 1/3 and m['covered_precision'] == m['covered_recall'] == 1
    assert not m['available'] and m['precision'] is m['recall'] is m['sim_repro_rate'] is None


def test_paired_precision_and_recall_keep_literal_correct_trigger_membership():
    m = p.summarize([{'ra_type': 2, 'auto_label': '正确触发', 'result_status': 'reused', 'sim_triggered': True}], profiles.DEFAULT_CONFIG)
    assert m['covered_source_counts'] == m['counts'] == m['sim_counts']
    assert m['counts']['precision_numerator'] == 0 and m['counts']['recall_numerator'] == 1
    assert m['available'] and m['precision'] == 0 and m['recall'] == m['sim_repro_rate'] == 1


def test_audit_mutation_marks_revision_stale(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    changed = deepcopy(batch.payload)
    changed['results']['s-a']['sim_triggered'] = not changed['results']['s-a']['sim_triggered']
    batch.payload = changed; db.commit()
    assert p.board(db, RELEASE)['stale']


def test_profile_change_and_page_reads_do_not_query_or_submit(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    monkeypatch.setattr(at.warehouse, 'fetch', lambda *a, **k: pytest.fail('GET must not query upstream'))
    assert p.board(db, RELEASE)['revision']
    assert p.issue_page(db, RELEASE, page_size=10)['total'] == len(labels)
    assert p.issue_page(db, RELEASE, query='a')['total'] == 1
    with pytest.raises(ValueError, match='pagination'):
        p.issue_page(db, RELEASE, page_size=200)


def test_publish_rejects_changed_preview_basis(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    draft = profiles.draft(db, profiles.DEFAULT_CONFIG, 'draft', 'reason')
    preview = p.preview(db, draft['id'], RELEASE)
    _, _, _, key = p.context(db, RELEASE)
    w.put_state(db, key, {**w.get_state(db,key), 'revision_key': 'evrevision:missing'})
    with pytest.raises(ValueError, match='plan_stale'):
        profiles.publish(db, draft['id'], preview['preview_hash'])


def executable(prepared, monkeypatch):
    db, snap, batch, labels, _ = seed(prepared, monkeypatch)
    changed = deepcopy(snap.payload)
    changed['period'].update(status='completed', verified=True, cycle_end='2026-10-22', evidence='verified',
                             binary_id=456, template_job_id=123, binary_evidence='verified')
    snap.payload = changed
    bp = deepcopy(batch.payload); bp['period'] = changed['period']; batch.payload = bp
    db.commit()
    at.recalculate(db, RELEASE, fetcher=lambda _: deepcopy(labels))
    revision = p.recalculate(db, RELEASE)
    return db, snap, batch, labels, revision


def test_manual_start_is_durable_and_idempotent(prepared, monkeypatch, tmp_path):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    plan = p.board(db, RELEASE)['plan']
    first = p.start(db, plan['id'])
    assert first['status'] == 'preparing' and first['simulation_submitted'] is False
    assert p.start(db, plan['id']) == first
    assert len(p.rows(db, 'evstart:')) == 1


def test_preparation_preflight_and_submit_reuse_frozen_plan(prepared, monkeypatch, tmp_path):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    plan = p.board(db, RELEASE)['plan']
    started = p.start(db, plan['id'])
    calls = []
    def driver(config, action, body):
        calls.append(action)
        if action == 'prepare_scenes':
            assert {i['issue_id'] for i in body['issues']} == {'c'}
            return {'ready': True, 'prepared':1, 'failed':0, 'failures':[], 'scenarios': [{'scenario_id': '999', 'issue_id':'c','scenario_revision':1,'start_timestamp':0,'end_timestamp':10000}]}
        if action == 'preflight':
            assert body['execution_schema'] == 'physical_v2'
            assert body['scenarios'][0]['cohort'] == 'source_manual'
            return {'ready':True,'fingerprint':body['fingerprint'],'execution_contract_hash':'runtime'}
        if action == 'submit':
            assert p.rows(db,'evexecution:')[0]['status'] == 'submitting'
            return {'fingerprint':body['fingerprint'],'job_id':9999}
        pytest.fail(action)
    monkeypatch.setattr(w, 'driver_call', driver)
    result = p.execute_start(db, started)
    assert calls == ['prepare_scenes','preflight','submit']
    assert result['job_id'] == 9999 and result['status'] == 'running'
    # Restart may re-run preparation safely, but never submits a persisted execution twice.
    again = p.execute_start(db, started)
    assert calls.count('submit') == 1 and again['id'] == result['id']


def test_uncertain_submission_only_reads_receipt(prepared, monkeypatch, tmp_path):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    started = p.start(db, p.board(db, RELEASE)['plan']['id'])
    def driver(config, action, body):
        if action == 'prepare_scenes':
            return {'ready':True,'prepared':1,'failed':0,'failures':[],'scenarios':[{'scenario_id':'999','issue_id':'c','scenario_revision':1,'start_timestamp':0,'end_timestamp':10000}]}
        if action == 'preflight':
            return {'ready':True,'fingerprint':body['fingerprint'],'execution_contract_hash':'runtime'}
        if action == 'submit':
            raise TimeoutError('ambiguous')
        if action == 'receipt':
            return {'job_id':None}
        pytest.fail(action)
    monkeypatch.setattr(w,'driver_call',driver)
    execution = p.execute_start(db, started)
    assert execution['status'] == 'submission_uncertain'
    p.poll_execution(db,execution)
    assert p.rows(db,'evexecution:')[0]['status'] == 'submission_uncertain'


def test_runtime_change_fails_before_submit(prepared, monkeypatch, tmp_path):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    started = p.start(db, p.board(db, RELEASE)['plan']['id'])
    def driver(config,action,body):
        if action == 'prepare_scenes':
            return {'ready':True,'prepared':1,'failed':0,'failures':[],'scenarios':[{'scenario_id':'999','issue_id':'c','scenario_revision':1,'start_timestamp':0,'end_timestamp':10000}]}
        if action == 'preflight':
            return {'ready':True,'fingerprint':body['fingerprint'],'execution_contract_hash':'different'}
        pytest.fail('Unexpected side effect: '+action)
    monkeypatch.setattr(w,'driver_call',driver)
    with pytest.raises(ValueError,match='execution_contract_changed'):
        p.execute_start(db, started)


def test_full_import_reprojects_physical_signal_and_not_old_truth(prepared, monkeypatch, tmp_path):
    db,snap,batch,labels,revision = executable(prepared,monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    row = next(r for r in revision['rows'] if r['issue_id']=='c')
    issue = next(r for r in revision['payload']['issues'] if r['issue_id']=='c')
    plan = {**revision['specification'],'release':RELEASE,'population_hash':'pop','scenarios':[{'scenario_id':'999','issue_id':'c','cohort':'source_manual','scenario_revision':1,'start_timestamp':0,'end_timestamp':10000}], 'issues':[issue], 'fingerprint':'id'}
    execution = {'id':'test','created_at':p.now(),'plan':plan,'context':revision['context'],'status':'running','job_id':9999,'preflight':{'execution_contract_hash':'runtime'}}
    exported = {'job_id':9999,'release':RELEASE,'binary_id':456,'population_hash':'pop','execution_contract_hash':'runtime',
                'progress':{'job_id':9999,'state':'COMPLETED','total':1,'completed':1,'failed':0,'cancelled':0},'rows':[{'scenario_id':999,'issue_id':'c','cohort':'source_manual','task_id':'task-999','argument_hash':'hash','task_status':3,'task_outcome':'Done','simulator_cache_hit':False,
                  'inference_log_count':1,'dpe_output_count':1,'output_bag_count':1,'failed_evaluation_count':0,'unexpected_warning_count':0,p.TRIGGER:1}]}
    def driver(config,action,body):
        if action=='progress': return {'state':'COMPLETED'}
        if action=='poll': return {'execution_export':exported}
        pytest.fail(action)
    monkeypatch.setattr(w,'driver_call',driver)
    p.poll_execution(db,execution)
    after = p.current_revision(db,**revision['context'])
    assert after['metrics']['available']
    assert after['metrics']['covered'] == after['metrics']['eligible']
    assert next(r for r in after['rows'] if r['issue_id']=='c')['sim_triggered'] is True


def test_api_validates_and_has_read_only_get(prepared,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.api.evaluation_routes import router
    db,_,_,_,_ = seed(prepared,monkeypatch)
    app=FastAPI(); app.include_router(router); app.dependency_overrides[get_db]=lambda:db
    client=TestClient(app)
    assert client.get('/api/dashboard/evaluation/board',params={'release':RELEASE}).status_code==200
    assert client.get('/api/dashboard/evaluation/issues',params={'release':RELEASE,'page_size':200}).status_code==422
    assert not p.rows(db,'evexecution:')


def test_queued_start_revalidates_before_scene_creation(prepared, monkeypatch, tmp_path):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    started = p.start(db, p.board(db, RELEASE)['plan']['id'])
    changed = deepcopy(snap.payload)
    changed['issues'][0]['ra_start_timestamp'] += 1
    snap.payload = changed; db.commit()
    monkeypatch.setattr(w, 'driver_call', lambda *a: pytest.fail('Stale plan caused a side effect'))
    with pytest.raises(ValueError, match='plan_stale'):
        p.execute_start(db, started)


def test_ordinary_submit_waits_for_independent_physical_execution(prepared, monkeypatch, tmp_path):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    p.start(db, p.board(db, RELEASE)['plan']['id'])
    batch.status = 'queued'; db.commit()
    monkeypatch.setattr(w, 'driver_call', lambda *a: pytest.fail('Shared physical lane submitted twice'))
    assert w.execute_batch(db, batch, {}).status == 'queued'


def test_standard_collectors_reuse_physical_result_with_audit(prepared, monkeypatch):
    from app.services import release_backfill, label_recovery
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    issue = deepcopy(next(i for i in revision['payload']['issues'] if i['issue_id'] == 'a'))
    scene = deepcopy(next(s for s in batch.payload['scenarios'] if s['issue_id'] == 'a'))
    changed = deepcopy(batch.payload)
    changed['results'].pop(str(scene['scenario_id']))
    batch.payload = changed; db.commit()
    plan = {**revision['specification'], 'release':RELEASE, 'issues':[issue],
            'scenarios':[{**scene, 'cohort':'source_auto'}]}
    exported = {'execution_contract_hash':'runtime', 'rows':[{'scenario_id':scene['scenario_id']}]}
    execution = {'id':'shared', 'status':'complete','created_at':p.now(),'job_id':9999,'plan':plan,
                 'results':{str(scene['scenario_id']):{'sim_triggered':False}},'export':exported,'audit_hash':digest(exported)}
    execution['audit_hash'] = p.execution_audit_hash(execution)
    w.put_state(db, 'evexecution:shared', execution)
    for collector in (lambda: release_backfill.collect_results(db,batch,batch.payload),
                      lambda: label_recovery.collect(db,batch,batch.payload['scenarios'])):
        results, lineage = collector()
        assert results[str(scene['scenario_id'])]['sim_triggered'] is False
        assert lineage[str(scene['scenario_id'])]['execution_id'] == 'shared'
        assert p.binding_valid(db, lineage[str(scene['scenario_id'])])
    execution['export']['changed'] = True
    w.put_state(db, 'evexecution:shared', execution)
    assert not p.binding_valid(db, lineage[str(scene['scenario_id'])])
    assert str(scene['scenario_id']) not in release_backfill.collect_results(db,batch,batch.payload)[0]


def test_board_hashes_shared_receipt_once_and_rechecks_next_read(prepared, monkeypatch):
    db, snap, batch, labels, value = seed(prepared, monkeypatch)
    binding = next(b for b in value['lineage'].values() if b.get('fingerprint'))
    value['lineage'] = {str(i): deepcopy(binding) for i in range(100)}
    w.put_state(db, value['revision_key'], value)
    original = at.audit_hash
    calls = []
    def counted(payload):
        calls.append(payload)
        return original(payload)
    monkeypatch.setattr(at, 'audit_hash', counted)
    assert not p.board(db, RELEASE)['stale']
    assert len(calls) == 1
    changed = deepcopy(batch.payload)
    changed['results']['s-a']['sim_triggered'] = not changed['results']['s-a']['sim_triggered']
    batch.payload = changed
    db.commit()
    assert p.board(db, RELEASE)['stale']
    assert len(calls) == 2


def test_comparison_builds_catalogue_once(prepared, monkeypatch):
    db, _, _, _, revision = seed(prepared, monkeypatch)
    original, calls = at.versions, []
    def catalogue(db):
        calls.append(True)
        return original(db)
    monkeypatch.setattr(at, 'versions', catalogue)
    result = p.comparison(db, **{k:v for k,v in revision['context'].items() if k != 'release'})
    assert len(calls) == 1
    assert result['versions'][0]['revision']['metrics'] == revision['metrics']


def test_cached_get_revalidates_after_execution_changes(prepared, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.api.evaluation_routes import router
    db, _, batch, _, revision = seed(prepared, monkeypatch)
    original, calls = p.board, []
    def board(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(p, 'board', board)
    app=FastAPI(); app.include_router(router); app.dependency_overrides[get_db]=lambda:db
    client=TestClient(app)
    query=revision['context']
    assert client.get('/api/dashboard/evaluation/board',params=query).json()['stale'] is False
    assert client.get('/api/dashboard/evaluation/board',params=query).json()['stale'] is False
    assert len(calls) == 1
    payload=deepcopy(batch.payload)
    payload['results']['s-a']['sim_triggered'] = not payload['results']['s-a']['sim_triggered']
    batch.payload=payload; db.commit()
    assert client.get('/api/dashboard/evaluation/board',params=query).json()['stale'] is True
    assert len(calls) == 2


def test_partial_preparation_preserves_population_and_requires_new_manual_plan(prepared, monkeypatch, tmp_path):
    db, snap, batch, labels, _ = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    original_batch = deepcopy(batch.payload)
    payload = deepcopy(snap.payload)
    payload['scenarios'] = [s for s in payload['scenarios'] if s['issue_id'] != 'g']
    snap.payload = payload; db.commit()
    revision = p.recalculate(db, RELEASE)
    plan = p.board(db, RELEASE)['plan']
    assert plan['prepare_count'] == plan['runnable_count'] == 2
    def prepare(config, action, body):
        assert action == 'prepare_scenes'  # No preflight or submission after partial preparation.
        return {'ready':False, 'prepared':1, 'failed':1,
                'scenarios':[{'scenario_id':'999','issue_id':'c','scenario_revision':0,'start_timestamp':0,'end_timestamp':10000}],
                'failures':[{'issue_id':'g','reason':'missing_bag'}]}
    monkeypatch.setattr(w, 'driver_call', prepare)
    started = p.start(db, plan['id'])
    outcome = p.execute_start(db, started)
    assert outcome['status'] == 'plan_updated'
    assert not p.rows(db, 'evexecution:')
    updated = p.current_revision(db, RELEASE)
    new_plan = p.board(db, RELEASE)['plan']
    assert new_plan['id'] != plan['id']
    assert (new_plan['gap_count'], new_plan['runnable_count'], new_plan['blocked_count']) == (2,1,1)
    assert (new_plan['prepare_count'], new_plan['simulate_count'], new_plan['review_count']) == (0,1,0)
    assert updated['metrics']['counts'] == revision['metrics']['counts']
    assert updated['source_count'] == revision['source_count']
    assert updated['metrics']['precision'] is None and updated['metrics']['recall'] is None
    missing = next(r for r in updated['rows'] if r['issue_id'] == 'g')
    assert missing['result_status'] == 'missing_bag' and missing['sim_triggered'] is None
    assert batch.payload == original_batch
    # A separately reviewed manual start submits only the available Issue.
    w.put_state(db, 'evstart:'+started['id'], {**started, 'status':'plan_updated'})
    def submit(config, action, body):
        assert {i['issue_id'] for i in body['issues']} == {'c'}
        if action == 'preflight': return {'ready':True,'fingerprint':body['fingerprint'],'execution_contract_hash':'runtime'}
        assert action == 'submit'
        return {'fingerprint':body['fingerprint'],'job_id':9999}
    monkeypatch.setattr(w, 'driver_call', submit)
    result = p.execute_start(db, p.start(db, new_plan['id']))
    assert result['job_id'] == 9999
    assert p.rows(db, 'evstart:')[0]['plan_id'] == plan['id']
    # A new offline sample snapshot clears the deferral, while verified scenes remain reusable.
    dashboard = {**updated['source']['dashboard'], 'sample_snapshot_id':'new-offline-import'}
    physical = deepcopy(updated['payload'])
    deferred, _ = p.prepared_inputs(db, updated['context'], dashboard, physical, updated['specification'])
    assert not deferred
    receipt = p.rows(db,'evpreparation:')[0]
    receipt['scenarios'][0]['end_timestamp'] += 1
    w.put_state(db,'evpreparation:'+receipt['id'][:48],receipt)
    assert p.board(db, RELEASE)['stale']


@pytest.mark.parametrize('bad', ['omitted','overlap','duplicate','counts'])
def test_partial_preparation_receipt_must_cover_exact_original_inputs(prepared, monkeypatch, bad):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    issue = next(i for i in revision['payload']['issues'] if i['issue_id'] == 'c')
    receipt = {'ready':True, 'prepared':1, 'failed':0, 'failures':[],
               'scenarios':[{'scenario_id':'999','issue_id':'c','scenario_revision':1,'start_timestamp':0,'end_timestamp':10000}]}
    if bad == 'omitted': receipt['scenarios'] = []
    if bad == 'overlap': receipt['failures'] = [{'issue_id':'c','reason':'missing_bag'}]
    if bad == 'duplicate': receipt['scenarios'] *= 2
    if bad == 'counts': receipt['prepared'] = 2
    with pytest.raises(ValueError, match='receipt_invalid'):
        p.save_preparation(db, revision, [issue], receipt)
    assert not p.rows(db,'evpreparation:')


def test_failed_attempt_is_retained_when_manually_retried(prepared, monkeypatch, tmp_path):
    db, _, _, _, _ = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    plan = p.board(db, RELEASE)['plan']
    first = p.start(db, plan['id'])
    failed = {**first, 'status':'failed', 'error':'scene_preparation_failed'}
    w.put_state(db,'evstart:'+first['id'],failed)
    retried = p.start(db, plan['id'])
    assert retried['previous_attempts'] == [failed]


@pytest.mark.parametrize('legacy_failure', [False, True])
def test_failed_preflight_keeps_manual_retry_available_without_a_submit_intent(prepared, monkeypatch, tmp_path, legacy_failure):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    monkeypatch.setenv('RELEASE_WORKFLOW_LOCK', str(tmp_path/'workflow.lock'))
    plan=p.board(db,RELEASE)['plan']
    p.start(db,plan['id'])
    calls=[];ready=False;bodies=[]
    def driver(config,action,body):
        calls.append(action)
        if action=='prepare_scenes':
            return {'ready':True,'prepared':1,'failed':0,'failures':[],'scenarios':[{'scenario_id':'999','issue_id':'c','scenario_revision':0,'start_timestamp':0,'end_timestamp':10000}]}
        if action=='preflight':
            bodies.append(deepcopy(body))
            return {'ready':ready,'fingerprint':body['fingerprint'],'execution_contract_hash':'runtime'}
        if action=='submit':
            assert p.rows(db,'evexecution:')[0]['status']=='submitting'
            return {'fingerprint':body['fingerprint'],'job_id':9999}
        pytest.fail('Unexpected side effect: '+action)
    monkeypatch.setattr(w,'driver_call',driver)
    monkeypatch.setattr(p,'SessionLocal',lambda: db)
    p.tick()
    failed=p.rows(db,'evstart:')[0]
    assert failed['status']=='failed' and failed['error']=='preflight_failed'
    assert not p.rows(db,'evexecution:') and 'submit' not in calls
    if legacy_failure:
        body=bodies[0];identifier=body['fingerprint'][:48]
        w.put_state(db,'evexecution:'+identifier,{'id':identifier,'created_at':p.now(),'status':'preflight_failed',
            'plan':body,'context':plan['context'],'plan_id':plan['id'],'simulation_submitted':False,
            'preflight_failures':[{'error':'preflight_failed','reconciled':True}]})
    ready=True
    retry=p.start(db,plan['id'])
    assert retry['previous_attempts'][-1]['error']=='preflight_failed'
    result=p.execute_start(db,retry)
    assert result['status']=='running' and result['job_id']==9999
    assert len(p.rows(db,'evexecution:'))==1 and calls.count('submit')==1
    assert p.execute_start(db,retry)['id']==result['id'] and calls.count('submit')==1
    if legacy_failure: assert result['preflight_failures'][0]['reconciled'] is True
