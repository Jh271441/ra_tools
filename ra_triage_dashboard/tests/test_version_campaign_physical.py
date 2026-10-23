import hashlib,json,tempfile,unittest
from pathlib import Path
from ra_triage_dashboard.app.db import Database


class VersionCampaignPhysicalTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'db.sqlite');self.db.init()
        self.db.replace_baseline_scope(scope='manual_sidecar_test',rows=[dict(issue_id='cn'+str(n),gt_label='误触发') for n in range(1,5)],source='test')
        self.db.set_labeling_scope_state(baseline_scope='manual_sidecar_test',status='active',policy_version='test',source_inventory_sha256='a'*64,updated_by='tester')
        for user in ['jasperchen','liangxianghui']:self.db.set_access_user(username=user,role='admin',actor='tester')
        self.rid=self.db.ensure_version_stream('20261009','test')
        self.db.append_version_predictions(run_id=self.rid,rows=[dict(issue_id='cn'+str(n),model_label='误触发',model_confidence=.8,model_extra=dict(software_version='1.gen4-release-20261009.1')) for n in range(1,5)])
        self.policy=dict(sampling_policy='version_probability_v3',seed='a'*64)
        self.campaigns=[];self.items=[]
        for n,who in [(1,'jasperchen'),(2,'liangxianghui')]:
            iid='cn'+str(n);ws=self.db.create_review_workset(baseline_scope='manual_sidecar_test',issue_ids=[iid],selection_source_run_id=self.rid,created_by='test')
            snap=self.db.create_label_result_snapshot(workset_id=ws['id'],created_by='test',allow_partial=True)
            camp=self.db.create_campaign(spec=dict(purpose='model_review',workflow_mode='model_review_and_case_label',evaluation_run_id=self.rid,workset_id=ws['id'],name='old'+str(n),reference_type='label_result_snapshot',reference_id=snap['id'],members=[dict(issue_id=iid,assignees=[who])]),actor='test',actor_source='test',actor_verified=True,idempotency_key='source'+str(n))['campaign']
            self.campaigns.append(camp)
            self.items.append(dict(issue_id=iid,software_version='1.gen4-release-20261009.1',state='published',is_target=True,is_low=True,is_sample=False,binding=dict(run_id=self.rid,campaign_id=camp['id'],assignee=who)))
        self.db.ingest_version_dataset(family='20261009',policy=self.policy,items=self.items,batch_key='old-packet',actor='test')
    def submit(self,campaign,context,reviewer='jasperchen',iid='cn1',key='original'):
        return self.db.submit_combined_review(issue_id=iid,campaign_id=campaign['id'],model_run_id=self.rid,reviewer=reviewer,reviewer_source='test',reviewer_verified=True,model_review_status='completed',reason='unchanged reason',missing_evidence=[],expected_output='误触发',tags=[],rationale='unchanged rationale',expected_model_review_storage_id=context['model_review_storage_id'],expected_case_revision_id=context['case_revision_id'],expected_label_state_fingerprint=context['label_state_fingerprint'],idempotency_key=key)
    def test_physical_merge_keeps_human_identity_and_old_replay_then_appends(self):
        old=self.campaigns[0];ctx=self.db.combined_review_context(issue_id='cn1',campaign_id=old['id'],reviewer='jasperchen')
        written=self.submit(old,ctx)
        receipt=self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2',backup_sha256='a'*64,actor='authorized-test')
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM issue_work_splits WHERE evaluation_run_id=?',(self.rid,)).fetchone()['n'],1)
            revision=c.execute('SELECT * FROM model_review_revisions WHERE id=?',(written['model_review_storage_id'],)).fetchone()
            self.assertEqual(revision['reason'],'unchanged reason');self.assertEqual(revision['reviewer'],'jasperchen')
            self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM label_revisions').fetchone()['n'],1)
        after=self.db.combined_review_context(issue_id='cn1',campaign_id=receipt['campaign_id'],reviewer='jasperchen')
        self.assertEqual(after['model_review_storage_id'],written['model_review_storage_id'])
        self.assertTrue(after['progress']['case_label_acknowledged'])
        self.assertTrue(self.submit(old,ctx)['duplicate'])
        other=self.db.review_task_context(split_id=self.campaigns[1]['id'],username='liangxianghui')
        self.assertEqual(other['id'],receipt['campaign_id'])
        appended=self.db.append_version_campaign_members(family='20261009',policy=self.policy,issue_ids=['cn1','cn2','cn3'],current_target_ids=['cn1','cn2','cn3'],batch_key='next',actor='service')
        self.assertEqual(appended['campaign_id'],receipt['campaign_id']);self.assertEqual(appended['added'],1)
        self.assertEqual(appended['bindings']['cn1']['assignee'],'jasperchen')
        again=self.db.append_version_campaign_members(family='20261009',policy=self.policy,issue_ids=['cn1','cn2','cn3'],current_target_ids=['cn1','cn2','cn3'],batch_key='next',actor='service')
        self.assertEqual(again['added'],0)
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM issue_work_splits').fetchone()['n'],1)
        fresh=self.db.combined_review_context(issue_id='cn3',campaign_id=receipt['campaign_id'],reviewer=appended['bindings']['cn3']['assignee'])
        self.assertTrue(fresh['assigned']);self.submit(dict(id=receipt['campaign_id']),fresh,reviewer=appended['bindings']['cn3']['assignee'],iid='cn3',key='new')
        # Existing packet receipts remain immutable despite aliased task bindings.
        normalized=json.loads(json.dumps(self.items))
        for item in normalized:item['binding']['campaign_id']=receipt['campaign_id']
        self.assertTrue(self.db.ingest_version_dataset(family='20261009',policy=self.policy,items=normalized,batch_key='old-packet',actor='test')['replayed'])
        self.assertTrue(self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2',backup_sha256='a'*64,actor='authorized-test')['replayed'])

    def test_new_release_uses_one_physical_task_from_first_append(self):
        rid=self.db.ensure_version_stream('20261016','test')
        self.db.append_version_predictions(run_id=rid,rows=[dict(issue_id='cn5',model_label='误触发',model_confidence=.8,model_extra=dict(software_version='1.gen4-release-20261016.1'))])
        first=self.db.append_version_campaign_members(family='20261016',policy=self.policy,issue_ids=['cn5'],current_target_ids=['cn5'],batch_key='initial',actor='service')
        again=self.db.append_version_campaign_members(family='20261016',policy=self.policy,issue_ids=['cn5'],current_target_ids=['cn5'],batch_key='initial',actor='service')
        self.assertEqual(first['campaign_id'],again['campaign_id']);self.assertEqual(again['added'],0)
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM issue_work_splits WHERE evaluation_run_id=?',(rid,)).fetchone()['n'],1)

    def test_failed_merge_rolls_back_bindings_and_all_immutable_guards(self):
        with self.db.connect() as c:
            before=[tuple(r) for r in c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()]
            c.execute("UPDATE campaign_reference_items SET reference_id='missing' WHERE campaign_id=?",(self.campaigns[1]['id'],))
        with self.assertRaises(ValueError):self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2',backup_sha256='a'*64,actor='test')
        with self.db.connect() as c:
            after=[tuple(r) for r in c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()]
            self.assertEqual(before,after)
            self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM issue_work_splits').fetchone()['n'],2)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM dataset_audit_events WHERE action='version_task_archived'").fetchone()['n'],0)
