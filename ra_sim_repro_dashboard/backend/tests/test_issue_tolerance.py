from copy import deepcopy
import pytest
from ra_api.release_tolerance import POLICY, LEGACY_POLICY, assess, grade, validate_frozen
from test_release_workflow import db, config, scene_labels
from test_result_publication import data
from app.services import release_workflow as w

@pytest.mark.parametrize('total,bad,allowed', [(1856,1,True),(200,1,True),(1001,5,True),(1000,5,True),(2000,6,True),(2000,39,True),(2000,40,False),(2000,41,False),(1,0,True),(0,0,False)])
def test_boundary(total,bad,allowed):
    if allowed:
        assert assess(map(str,range(total)),map(str,range(bad)))['abnormal_issue_count']==bad
    else:
        with pytest.raises(ValueError): assess(map(str,range(total)),map(str,range(bad)))


def setup(db,config,monkeypatch,failed=1,total=201):
    rows=[{'issue_id':str(i),'ra_type':2,'ra_merge_result':'成功'} for i in range(total)]
    scenes=[{'issue_id':str(i),'scenario_id':str(i+1),'scenario_labels':scene_labels('positive_auto')} for i in range(failed,total)]
    real_sync=w.sync_once
    def sync(*args,**kwargs):
        return real_sync(db,config,lambda *a:rows,lambda *a:scenes)
    monkeypatch.setattr(w,'sync_once',sync)
    sync()
    receipt={'ready':False,'failed':failed,'failures':[{'issue_id':str(i),'reason':'missing_bag'} for i in range(failed)]}
    monkeypatch.setattr(w,'driver_call',lambda *a:receipt)
    return rows,scenes,receipt,sync


def test_preparation_freezes_denominator_and_rechecks_source(db,config,monkeypatch):
    rows,scenes,receipt,sync=setup(db,config,monkeypatch)
    w.prepare_missing_scenes(db,config)
    sync()  # monitor performs another full sync before planning
    plan=w.make_plan(db,config)
    assert validate_frozen(plan)['issue_count']==201
    assert len(plan['scenarios'])==200
    assert w.make_plan(db,config)['fingerprint']==plan['fingerprint']
    assert plan['issues'][0]['evaluation_exclusion']['approved_by']==POLICY['version']
    rows[0]['ra_merge_result']='失败';sync()
    with pytest.raises(ValueError,match='尚未匹配'): w.make_plan(db,config)

@pytest.mark.parametrize('case',['incomplete','duplicate','unknown_reason','mapping','unknown_gt','over_budget'])
def test_bad_evidence_never_bypasses_gate(db,config,monkeypatch,case):
    rows,scenes,receipt,sync=setup(db,config,monkeypatch,failed=40 if case=='over_budget' else 1,total=2000)
    if case=='incomplete':receipt['failed']=2
    if case=='duplicate':receipt['failures']*=2;receipt['failed']=2
    if case=='unknown_reason':receipt['failures'][0]['reason']='timeout'
    if case=='mapping':
        snapshot=sync();snapshot.payload={**snapshot.payload,'mapping_error':'failed'};db.commit()
    if case=='unknown_gt': rows[-1]['ra_merge_result']='unknown';sync()
    if case=='unknown_gt':
        w.prepare_missing_scenes(db,config)
        with pytest.raises(ValueError,match='GT'): w.make_plan(db,config)
    else:
        with pytest.raises(ValueError):w.prepare_missing_scenes(db,config)


@pytest.mark.parametrize('prep_count,allowed',[(4,True),(5,True),(24,False)])
def test_result_budget_includes_preparation(data,prep_count,allowed):
    from test_result_publication import ready_for_auto
    from app.services.release_metrics import summarize_population
    from app.services.result_publication import validate_coverage_standard
    _,batch,_=ready_for_auto(data)
    p=deepcopy(batch.payload)
    for index in range(1000):
        iid='good'+str(index);sid='extra'+str(index)
        p['issues'].append({'issue_id':iid,'ra_type':2,'ra_merge_result':'成功'})
        p['scenarios'].append({'issue_id':iid,'scenario_id':sid,'cohort':'positive_auto'})
        p['results'][sid]=deepcopy(p['results']['1'])
        p['scenario_results'][sid]=deepcopy(p['scenario_results']['1'])
    failures=[{'issue_id':'prep'+str(i),'reason':'missing_bag'} for i in range(prep_count)]
    for f in failures:
        p['issues'].append({'issue_id':f['issue_id'],'ra_type':2,'ra_merge_result':'成功',
            'evaluation_exclusion':{'approved_by':POLICY['version'],'reason':f['reason']}})
    p['issue_tolerance']={'policy':POLICY,'population_hash':p['population_hash'],
        'eligible_issue_ids':[i['issue_id'] for i in p['issues']], 'preparation_failures':failures}
    p['result_import'].update(scenario_count=1201,valid_scenario_count=1200)
    p['execution_progress'].update(total=1201,completed=1200)
    p['result_import']['subset_summary']=summarize_population(
        [i for i in p['issues'] if i['issue_id']!='i2'],
        [s for s in p['scenarios'] if s['issue_id']!='i2'],p['results'])
    if allowed:
        result=validate_coverage_standard(p)
        assert result['abnormal_issue_count']==prep_count+1
        assert result['issue_count']==1201+prep_count and result['valid_issue_count']==1200
    else:
        with pytest.raises(ValueError,match='98%'):validate_coverage_standard(p)


@pytest.mark.parametrize('total,bad,level',[(2000,5,'normal'),(1000,5,'degraded'),(2000,6,'degraded'),(2000,39,'degraded'),(2000,40,'blocked'),(2000,41,'blocked')])
def test_three_quality_levels(total,bad,level):
    assert grade(range(total),range(bad))['quality_level']==level


def test_legacy_policy_remains_strict():
    with pytest.raises(ValueError,match='≤ 5'):
        assess(range(2000),range(6),LEGACY_POLICY)
    with pytest.raises(ValueError):
        assess(range(200),[0],LEGACY_POLICY)
    assert assess(range(1001),range(5),LEGACY_POLICY)['quality_level']=='normal'
