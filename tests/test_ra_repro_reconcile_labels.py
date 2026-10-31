from copy import deepcopy
import json
import pytest
from ra_api.release_labels import cohort_label_update
from scripts.ra_repro_reconcile_labels import reconcile


LABEL = 'ra_repro_full_20261028_20261016'
RELEASE = 'gen4-release-20261016'


def sample():
    row = {'id':123, 'version':4, 'name':'existing scene', 'scenario':'immutable input',
        'start_timestamp':100, 'end_timestamp':200, 'scenario_tags':['retained'],
        'labels':[LABEL, LABEL+'_'+RELEASE, LABEL+'_positive_auto', LABEL+'_AutoTrigger', '#456', 'other-label']}
    change = {'scenario_id':'123', 'issue_id':'cn456', 'scenario_revision':4,
        'start_timestamp':100, 'end_timestamp':200, 'cohort':'negative_auto',
        'before_labels':sorted(row['labels']), 'after_labels':cohort_label_update(row, LABEL, RELEASE, 'negative_auto')}
    payload = {'release':RELEASE, 'period':{'release':RELEASE,'verified':True,'scenario_creation_label':LABEL},
        'label':LABEL,'source_hash':'verified-population','changes':[change]}
    return row, payload


def test_repairs_gt_cohort_retains_labels_and_writes_audit_before_update(tmp_path):
    row, payload = sample()
    calls = []
    def update(sid, labels):
        audit = json.loads(next((tmp_path/'label-sync').glob('*.json')).read_text())
        assert audit['status']=='planned' and audit['before']['123']==row
        calls.append(sid); row['labels']=labels;row['version']+=1
        return {'msg':'success'}
    result = reconcile(payload, lambda ids:[deepcopy(row)], update, tmp_path)
    assert result['ready'] and result['verified_count']==1 and calls==['123']
    assert LABEL+'_negative_auto' in row['labels'] and LABEL+'_positive_auto' not in row['labels']
    assert 'other-label' in row['labels'] and row['scenario']=='immutable input'
    audit = json.loads(open(result['audit_path']).read())
    assert audit['status']=='complete' and audit['updated_ids']==['123']
    assert cohort_label_update(row,LABEL,RELEASE,'negative_auto') is None


@pytest.mark.parametrize('drift',['source','version','time','labels','namespace','ambiguous','coverage','trigger'])
def test_prewrite_metadata_guards_block_without_upstream_writes(tmp_path,drift):
    row, payload = sample()
    if drift=='source':row['labels'][-2]='#457'
    if drift=='version':row['version']+=1
    if drift=='time':row['start_timestamp']+=1
    if drift=='labels':row['labels'].append('unobserved-edit')
    if drift=='namespace':
        row['labels'].append('ra_repro_cycle_20261028_1016')
        payload['changes'][0]['before_labels']=sorted(row['labels'])
    if drift=='ambiguous':
        row['labels'].append(LABEL+'_negative_auto')
        payload['changes'][0]['before_labels']=sorted(row['labels'])
    if drift=='trigger':payload['changes'][0]['cohort']='positive_manual'
    calls=[]
    with pytest.raises(ValueError):
        reconcile(payload,lambda ids:[] if drift=='coverage' else [row],lambda *a:calls.append(a),tmp_path)
    assert calls==[]


def test_postwrite_input_change_retains_failed_audit(tmp_path):
    row,payload=sample()
    def update(sid,labels):
        row['labels']=labels;row['scenario']='concurrently changed input'
        return {'msg':'success'}
    with pytest.raises(ValueError,match='input or labels'):
        reconcile(payload,lambda ids:[deepcopy(row)],update,tmp_path)
    audit=json.loads(next((tmp_path/'label-sync').glob('*.json')).read_text())
    assert audit['status']=='failed' and audit['updated_ids']==['123']


def test_trigger_change_never_uses_gt_only_repair():
    row,_=sample()
    with pytest.raises(ValueError,match='trigger change'):
        cohort_label_update(row,LABEL,RELEASE,'positive_manual')
