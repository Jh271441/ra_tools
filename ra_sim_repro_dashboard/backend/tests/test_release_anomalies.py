from copy import deepcopy
from types import SimpleNamespace
from test_release_workflow import config, db, seed
from app.models import ReleaseIssueSnapshot
from app.services import release_workflow as w
from app.services.release_watch import activity_identity
from app.services.release_anomalies import population_changes, collection_anomalies
from sqlalchemy import select


def test_exact_changes_and_bounded_details():
    before = [dict(issue_id=str(i), ra_type=2, ra_merge_result='成功') for i in range(40)]
    after = [{**r, 'ra_merge_result':'误触发'} for r in before]
    result = population_changes(before, after)
    assert result[0]['code'] == 'label_changed'
    assert result[0]['count'] == 40 and len(result[0]['items']) == 30
    assert result[0]['items'][0]['before'] == '成功'
    assert population_changes(before, list(reversed(before))) == []
    diff = population_changes(before, [{**before[0], 'ra_type':3}, {'issue_id':'new'}])
    assert {v['code'] for v in diff} == {'issues_added','issues_removed','trigger_type_changed'}


def test_matches_frozen_snapshot_not_latest(db, config):
    seed(db, config)
    snap = db.scalars(select(ReleaseIssueSnapshot)).one()
    source = deepcopy(snap.payload)
    identity = activity_identity(source['issues'], 'issue_time')
    release = source['period']['release']
    plan = {'period':{'activity_hash':identity}, 'population_hash':w.population_identity(source), 'job_id':123}
    batch = SimpleNamespace(release=release,payload=plan,fingerprint='frozen')
    rows = [{**r, 'ra_merge_result':'误触发'} for r in source['issues']]
    w.put_state(db,'release_observation:'+release,{'activity_hash':activity_identity(rows,'issue_time'),'issues':rows})
    newer = deepcopy(source);newer['issues']=rows
    db.add(ReleaseIssueSnapshot(release=release,period_hash='newer',payload=newer));db.commit()
    result = collection_anomalies(db,release,{'population_changed_after_submission':True},[batch])
    assert result[0]['code'] == 'label_changed' and result[0]['count'] == 2
    assert result[0]['job_id'] == 123
    batch.payload['population_hash'] = 'unavailable'
    assert collection_anomalies(db,release,{'population_changed_after_submission':True},[batch])[0]['code'] == 'collection_change_unresolved'
    assert collection_anomalies(db,'different',None,[batch]) == []


def test_missing_observation_is_not_mass_removal(db, config):
    assert collection_anomalies(db,'absent',{'population_changed_after_submission':True},[])[0]['code'] == 'collection_change_unresolved'


def test_applied_revision_resolves_only_matching_labels(db, config):
    from app.services.result_publication import audit_hash
    seed(db, config)
    source = deepcopy(db.scalars(select(ReleaseIssueSnapshot)).one().payload)
    release = source['period']['release']
    plan = {'period':{'activity_hash':activity_identity(source['issues'], 'issue_time')},
            'population_hash':w.population_identity(source), 'job_id':123}
    batch = SimpleNamespace(release=release,payload=plan,fingerprint='frozen')
    rows = [{**r, 'ra_merge_result':'误触发'} for r in source['issues']]
    observed = {'activity_hash':activity_identity(rows,'issue_time'),'issues':rows}
    w.put_state(db,'release_observation:'+release,observed)
    collection = {'population_changed_after_submission':True}
    w.put_state(db,'label_cycle:'+release,{'pending_count':0,'status':'idle'})
    assert not collection_anomalies(db,release,collection,[batch])[0].get('resolved')
    key = 'label_revision:test'
    revision = {'base_audit_hash':audit_hash(plan),'source_hash':observed['activity_hash'],
                'summary':{'available':True},'applied_at':'2026-10-24T23:31:00Z'}
    w.put_state(db,key,revision)
    w.put_state(db,'label_cycle:'+release,{'revision_key':key,'pending_count':0,'status':'idle'})
    result = collection_anomalies(db,release,collection,[batch])
    assert result[0]['resolved'] and result[0]['count']==2
    assert result[0]['items'][0]['before'] == source['issues'][0]['ra_merge_result']
    assert result[0]['resolved_at']==revision['applied_at']
    # A later edit cannot be hidden by an older successful revision.
    newer = deepcopy(rows); newer[0]['ra_merge_result']='out_of_scope'
    w.put_state(db,'release_observation:'+release,{'activity_hash':activity_identity(newer,'issue_time'),'issues':newer})
    assert not collection_anomalies(db,release,collection,[batch])[0].get('resolved')
    w.put_state(db,'release_observation:'+release,observed)
    batch.payload['job_id']=456
    assert not collection_anomalies(db,release,collection,[batch])[0].get('resolved')
