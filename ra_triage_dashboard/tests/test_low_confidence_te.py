import json

import pytest

from ra_triage_dashboard.app.low_confidence_te import apply_te_extension, plan_te_extension
from ra_triage_dashboard.app.version_review_tasks import version_task_detail
from ra_triage_dashboard.tests.test_human_publication import db, choose, context, submit

DATASET = 'release-20261106-odd2'


def legacy_low(db):
    cid = next(t['campaign_id'] for t in db.role_version_campaigns(DATASET) if t['cohort'] == 'low')
    with db.connect() as c:
        c.execute("DELETE FROM review_work_assignments WHERE split_id=? AND assignee IN ('yupuxue_v','zhangxuzhao_v')", (cid,))
        c.execute("UPDATE issue_work_splits SET mode='single',overlap_ratio=0 WHERE id=?", (cid,))
        c.execute("UPDATE campaign_issue_members SET required_submitter_count=1,reviewers_per_issue=1,assignment_kinds_json='[\"base\"]' WHERE campaign_id=?", (cid,))
        for row in c.execute('SELECT issue_id,binding_json FROM version_dataset_items WHERE dataset_id=?', (DATASET,)).fetchall():
            binding=json.loads(row['binding_json'])
            if binding.get('campaign_id')==cid:
                binding['assignees']=[binding['assignee']]
                c.execute('UPDATE version_dataset_items SET binding_json=? WHERE dataset_id=? AND issue_id=?', (json.dumps(binding), DATASET, row['issue_id']))
        db._campaign_refresh_compat_assignment_snapshot(c, cid)
    return cid


def test_extension_preserves_rd_work_and_adds_one_balanced_te_per_low_case(db):
    cid = legacy_low(db)
    iid, binding = choose(db)
    rd = binding['assignee']
    submit(db, iid, rd)
    before_context = context(db, iid, rd)
    assert before_context['progress']['model_review_submitted']
    with db.connect() as c:
        old_rd = [dict(r) for r in c.execute('SELECT * FROM review_work_assignments WHERE split_id=? ORDER BY issue_id', (cid,)).fetchall()]
        old_sampling = [dict(r) for r in c.execute('SELECT * FROM review_work_assignments WHERE split_id<>? ORDER BY split_id,issue_id,assignee', (cid,)).fetchall()]
        old_votes = [dict(r) for r in c.execute('SELECT * FROM label_revisions ORDER BY id').fetchall()]
        old_references = [dict(r) for r in c.execute('SELECT * FROM campaign_reference_items ORDER BY campaign_id,baseline_scope').fetchall()]
    plan = plan_te_extension(db, DATASET)
    assert plan['added']==len(old_rd)
    assert max(plan['te_counts'].values())-min(plan['te_counts'].values())<=1
    assert len(plan['pairs'])==4
    result=apply_te_extension(db,dataset_id=DATASET,actor='jasperchen',expected_fingerprint=plan['fingerprint'])
    assert result['added']==len(old_rd)
    assert apply_te_extension(db,dataset_id=DATASET,actor='jasperchen',expected_fingerprint=plan['fingerprint'])['replayed']
    after_context=context(db,iid,rd)
    for key in ['model_review', 'model_review_storage_id', 'case_revision', 'case_revision_id', 'progress']:
        assert after_context[key]==before_context[key]
    assert after_context['campaign']=={**before_context['campaign'],
        'config_revision': before_context['campaign']['config_revision']+1}
    assert after_context['label_state_fingerprint']!=before_context['label_state_fingerprint']
    with db.connect() as c:
        assert [dict(r) for r in c.execute("SELECT * FROM review_work_assignments WHERE split_id=? AND assignment_kind='base' ORDER BY issue_id", (cid,)).fetchall()]==old_rd
        assert [dict(r) for r in c.execute('SELECT * FROM review_work_assignments WHERE split_id<>? ORDER BY split_id,issue_id,assignee', (cid,)).fetchall()]==old_sampling
        assert [dict(r) for r in c.execute('SELECT * FROM label_revisions ORDER BY id').fetchall()]==old_votes
        assert [dict(r) for r in c.execute('SELECT * FROM campaign_reference_items ORDER BY campaign_id,baseline_scope').fetchall()]==old_references
    detail=version_task_detail(db,cid)
    assert detail['mode']=='blind' and detail['reviewers_per_issue']==2 and detail['overlap_ratio']==1
    assert detail['assignment_count']==2*len(old_rd)
    for row in db.version_dataset_gallery_rows(DATASET):
        if row['binding']['campaign_id']!=cid:continue
        assert len(row['reviewers'])==2
        te=next(r['username'] for r in row['reviewers'] if r['username'].endswith('_v'))
        assert context(db,row['issue_id'],te)['assigned']
    te=next(r['username'] for r in next(r for r in db.version_dataset_gallery_rows(DATASET) if r['issue_id']==iid)['reviewers'] if r['username'].endswith('_v'))
    submit(db,iid,te)
    assert next(r for r in db.version_dataset_gallery_rows(DATASET) if r['issue_id']==iid)['review_submitted']


def test_extension_rejects_stale_plan_and_non_admin(db):
    cid=legacy_low(db);plan=plan_te_extension(db,DATASET)
    with pytest.raises(PermissionError):
        apply_te_extension(db,dataset_id=DATASET,actor='unregistered',expected_fingerprint=plan['fingerprint'])
    with db.connect() as c:c.execute('UPDATE issue_work_splits SET config_revision=config_revision+1 WHERE id=?',(cid,))
    with pytest.raises(ValueError,match='inventory changed'):
        apply_te_extension(db,dataset_id=DATASET,actor='jasperchen',expected_fingerprint=plan['fingerprint'])


def test_extension_rolls_back_assignments_audits_and_config_on_error(db,monkeypatch):
    legacy_low(db);plan=plan_te_extension(db,DATASET)
    def fail(*args,**kwargs):raise RuntimeError('revision failed')
    monkeypatch.setattr(db,'_campaign_insert_revision',fail)
    with pytest.raises(RuntimeError,match='revision failed'):
        apply_te_extension(db,dataset_id=DATASET,actor='jasperchen',expected_fingerprint=plan['fingerprint'])
    assert plan_te_extension(db,DATASET)==plan


def test_legacy_low_append_requires_extension_before_new_cross_review(db):
    legacy_low(db)
    run=db.ensure_version_stream('20261106','test')
    ids=['cn9990']
    from ra_triage_dashboard.app.db_parts.role_version_tasks import sampled
    while sampled('a'*64,'20261106',ids[0]):ids[0]='cn'+str(int(ids[0][2:])+1)
    db.append_version_predictions(run_id=run,rows=[dict(issue_id=ids[0],model_label='误触发',model_confidence=.7,model_extra=dict(software_version='1.gen4-release-20261106.1'))])
    args=dict(family='20261106',policy=dict(sampling_policy='version_probability_v3',seed='a'*64),issue_ids=ids,current_target_ids=ids,batch_key='new-low',actor='test')
    with pytest.raises(ValueError,match='Extend existing'):db.append_version_campaign_members(**args)
    plan=plan_te_extension(db,DATASET)
    apply_te_extension(db,dataset_id=DATASET,actor='jasperchen',expected_fingerprint=plan['fingerprint'])
    result=db.append_version_campaign_members(**args)
    assert len(result['bindings'][ids[0]]['assignees'])==2
    assert result['bindings'][ids[0]]['assignees'][1].endswith('_v')
