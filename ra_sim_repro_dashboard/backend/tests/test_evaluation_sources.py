from copy import deepcopy

from app.services.evaluation_sources import distribution
from app.services import metric_profiles as profiles


def fixture():
    # Independent SQL membership expectations: correct literal, fallback success,
    # manual false, manual no-assist, excluded fallback and non-NULL empty model.
    values = [
        ('a', 2, '正确触发', 5, '正确触发', (0,1,1,1)),
        ('b', 2, None, 1, '成功', (1,1,1,1)),
        ('c', 3, '误触发', 1, '误触发', (0,0,0,0)),
        ('d', 3, '无需协助', 1, '无需协助', (0,0,0,1)),
        ('e', 2, None, 6, '未接起', (0,0,0,0)),
        ('f', 2, '', 1, '', (0,1,1,1)),
    ]
    keys = ('precision_numerator','precision_denominator','recall_numerator','recall_denominator')
    return {'revision_key':'test-revision','context':{'release':'gen4-release-20261023','profile_id':'auto_triage_sql_v2','date_start':'2026-10-29','date_end':'2026-11-04'},
        'source_count':6,'profile':{'config':deepcopy(profiles.DEFAULT_CONFIG)},
        'source':{'dashboard':{'observed_at':'2026-11-09T00:00:00+00:00','sample_snapshot_id':'sample-a',
            'rows':[{'issue_id':iid,'merged_ra_auto_result':merged} for iid,_,_,_,merged,_ in values]},
            'labels':{iid:{'ra_stuck_auto_result':model,'ra_result':raw} for iid,_,model,raw,_,_ in values}},
        'rows':[{'issue_id':iid,'ra_type':trigger,'auto_label':merged,'auto_memberships':dict(zip(keys,flags))} for iid,trigger,_,_,merged,flags in values],
        'metrics':{'counts':dict(zip(keys,(1,3,3,4)))}}


def test_literal_distribution_and_null_fallback_preserve_independent_counts():
    revision=fixture(); before=deepcopy(revision)
    result=distribution(revision)
    assert result['available'] and result['total']==6
    model,fallback,unknown=result['groups']
    assert [g['count'] for g in result['groups']]==[4,2,0]
    assert model['classes']=={'correct':1,'false':1,'no_assist':1,'other':1}
    assert model['classified_count']==3
    assert fallback['classes']=={'correct':1,'false':0,'no_assist':0,'other':1}
    assert fallback['classified_count']==1
    assert {'label':'','count':1} in model['raw_labels'],'empty model must not fall back'
    assert result['counts']=={'precision_numerator':1,'precision_denominator':3,'recall_numerator':3,'recall_denominator':4}
    assert result['correct_not_precision']==1
    assert revision==before,'GET projection must not change stored labels or membership flags'
    assert not any('issue_id' in g for g in result['groups'])


def test_missing_projection_and_disagreement_remain_unverified():
    for change in ('missing','disagreement'):
        revision=fixture()
        if change=='missing':del revision['source']['labels']['a']['ra_stuck_auto_result']
        else:revision['source']['labels']['a']['ra_stuck_auto_result']='误触发'
        result=distribution(revision)
        assert result['available']
        assert [g['count'] for g in result['groups']]==[3,2,1]
        assert result['counts']==revision['metrics']['counts']


def test_custom_rules_and_mapping_update_counts_without_rewriting_literal_source():
    for mode in ('include','mapping'):
        revision=fixture()
        if mode=='include':revision['profile']['config']['memberships']['precision_numerator']['include'].append('正确触发')
        else:
            revision['profile']['config']['label']['mapping']['正确触发']='成功'
            revision['rows'][0]['auto_label']='成功'
        revision['rows'][0]['auto_memberships']['precision_numerator']=1
        revision['metrics']['counts']['precision_numerator']=2
        result=distribution(revision)
        assert result['available'] and result['counts']['precision_numerator']==2
        assert result['correct_not_precision']==0
        assert {'label':'正确触发','count':1} in result['groups'][0]['raw_labels']
        assert result['rules']==revision['profile']['config']['memberships']


def test_incomplete_or_inconsistent_receipts_do_not_become_zero_charts():
    for mode in ('missing','duplicate','different_ids','bad_counts','bad_flags'):
        revision=fixture()
        if mode=='missing':del revision['source']
        elif mode=='duplicate':revision['rows'].append(deepcopy(revision['rows'][0]))
        elif mode=='different_ids':revision['source']['dashboard']['rows'][0]['issue_id']='other'
        elif mode=='bad_counts':revision['metrics']['counts']['recall_numerator']=2
        else:revision['rows'][0]['auto_memberships']['recall_numerator']=0
        result=distribution(revision)
        assert not result['available']
        assert 'total' not in result and 'groups' not in result


def test_saved_scopes_and_snapshots_are_carried_without_global_combination():
    first=fixture();second=fixture()
    second['context']['date_end']='2026-11-03';second['revision_key']='another-revision'
    second['source']['dashboard']['sample_snapshot_id']='sample-b'
    assert distribution(first)['context']['date_end']=='2026-11-04'
    assert distribution(second)['context']['date_end']=='2026-11-03'
    assert distribution(second)['sample_snapshot_id']=='sample-b'


def test_board_exposes_aggregates_without_changing_the_stored_revision(prepared,monkeypatch):
    from test_evaluation_pipeline import seed
    from app.services import evaluation_pipeline as p,release_workflow as w
    db,_,batch,_,value=seed(prepared,monkeypatch)
    before=deepcopy(w.get_state(db,value['revision_key']));batch_before=deepcopy(batch.payload)
    result=p.board(db,**value['context'])
    assert result['revision']['source_distribution']['available']
    assert result['revision']['source_distribution']['total']==value['source_count']
    assert result['revision']['source_distribution']['counts']==value['metrics']['counts']
    assert all(k not in result['revision'] for k in ('source','payload','rows','lineage'))
    assert w.get_state(db,value['revision_key'])==before and batch.payload==batch_before


# Reuse the existing isolated SQLite fixtures, with all upstream readers stubbed.
from test_auto_triage_metrics import db,prepared
