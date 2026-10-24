"""End-to-end database invariants for complete Issue decisions, without production writes."""
import tempfile
from pathlib import Path
from unittest import TestCase
import test_case_labeling as labeling_tests
from ra_triage_dashboard.app.db import LabelAnnotationConflictError
from ra_triage_dashboard.app.labeling_summary import summarize_labeling_cases


class FullIssueDecisionTest(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=labeling_tests.CaseLabelingTest().make_db(self.tmp.name);self.addCleanup(self.db.close)
        self.db.set_labeling_scope_state(baseline_scope='scope',status='active',policy_version='test',source_inventory_sha256='a'*64,updated_by='test')

    def vote(self, author='alice', issue='cn1', output='误触发', excluded=True, previous=None, **kwargs):
        return self.db.create_label_revision(issue_id=issue,expected_output=output,tags=['traffic_light'],
            evidence_gaps=[],rationale='original evidence',is_excluded=excluded,author=author,
            author_source='test',author_verified=True,expected_previous_revision_id=previous,**kwargs)

    def decide(self, adopted=None, excluded=False, previous=None, **kwargs):
        state=self.db.project_issue_label_states('scope',['cn1'])['cn1']
        return self.db.adjudicate_issue_label(baseline_scope='scope',issue_id='cn1',expected_output='误触发',
            rationale='reviewer explanation',actor='judge',actor_source='test',actor_verified=True,
            expected_previous_decision_id=previous,expected_source_fingerprint=kwargs.pop('fingerprint',state['source_fingerprint']),
            full_result=dict(is_excluded=excluded,tags=['junction'],evidence_gaps=[],label_rationale='final label evidence',
                adopted_revision_id=adopted,**kwargs))

    def test_override_exclusion_everywhere_and_preserve_personal_history(self):
        alice=self.vote();self.vote('bob',output='正确触发',excluded=False)
        result=self.decide(alice['id']);d=result['decision']
        self.assertFalse(d['is_excluded']);self.assertEqual(d['full_result']['adopted_revision']['rationale'],'original evidence')
        self.assertEqual(d['rationale'],'reviewer explanation');self.assertIn('is_excluded',d['full_result']['changed_fields'])
        self.assertFalse(self.db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])
        self.assertEqual(self.db.project_issue_tag_contexts(['cn1'])['cn1']['tags'],['junction'])
        self.assertEqual(self.db.list_labeling_cases(baseline_scopes=['scope'],exclusion='excluded')['total'],0)
        self.assertEqual(self.db.list_labeling_cases(baseline_scopes=['scope'],exclusion='active')['total'],2)
        items,_=self.db._project_labeling_cases(baseline_scopes=['scope'],issue_ids=['cn1'])
        summary=summarize_labeling_cases(items)
        self.assertEqual(summary['total'],1)
        cases=self.db.label_cases_for_issue('cn1')
        self.assertEqual(len(cases[0]['resolution']['heads']),2)
        self.assertTrue(next(r for r in cases[0]['resolution']['heads'] if r['author']=='alice')['is_excluded'])
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM label_revisions').fetchone()['n'],2)
            self.assertEqual(c.execute('SELECT gt_label FROM issues WHERE issue_id=?',('cn1',)).fetchone()['gt_label'],'正确触发')

    def test_stale_fingerprint_and_previous_decision_prevent_overwrite(self):
        a=self.vote();state=self.db.project_issue_label_states('scope',['cn1'])['cn1'];d=self.decide(a['id'])['decision']
        with self.assertRaises(LabelAnnotationConflictError):self.decide(a['id'])
        self.vote(previous=a['id'],excluded=True)
        projected=self.db.project_issue_label_states('scope',['cn1'])['cn1']
        self.assertEqual(projected['state'],'stale');self.assertTrue(projected['decision']['stale'])
        self.assertTrue(self.db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])
        with self.assertRaises(LabelAnnotationConflictError):self.decide(a['id'],previous=d['id'],fingerprint=state['source_fingerprint'])
        renewed=self.decide(a['id'],previous=d['id'])
        self.assertEqual(renewed['decision']['full_result']['adopted_revision_id'],a['id'])
        self.assertFalse(self.db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])

    def test_legacy_decision_does_not_invent_false_exclusion(self):
        self.vote();s=self.db.project_issue_label_states('scope',['cn1'])['cn1']
        d=self.db.adjudicate_issue_label(baseline_scope='scope',issue_id='cn1',expected_output='误触发',
            rationale='legacy',actor='judge',actor_source='test',actor_verified=True,
            expected_source_fingerprint=s['source_fingerprint'])['decision']
        self.assertIsNone(d['is_excluded']);self.assertIsNone(d['full_result'])
        self.assertTrue(self.db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])

    def test_legacy_classification_only_decision_still_requires_rationale(self):
        self.vote();s=self.db.project_issue_label_states('scope',['cn1'])['cn1']
        with self.assertRaisesRegex(ValueError,'裁决依据'):
            self.db.adjudicate_issue_label(baseline_scope='scope',issue_id='cn1',expected_output='误触发',
                rationale='',actor='judge',actor_source='test',actor_verified=True,
                expected_source_fingerprint=s['source_fingerprint'])

    def test_adoption_must_match_issue_and_exclusion_must_be_boolean(self):
        self.vote();other=self.vote(issue='cn2')
        for adopted,excluded in [(other['id'],False),(999,False),(None,None),(None,'false')]:
            with self.assertRaises(ValueError):self.decide(adopted,excluded=excluded)
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM issue_label_decisions').fetchone()['n'],0)

    def test_retained_images_are_bound_to_exact_revision_and_safe_metadata(self):
        image=dict(id='test-image',original_name='e.png',stored_name='private.png',media_type='image/png',size_bytes=10,width=1,height=1,sha256='a'*64)
        a=self.vote(attachments=[image])
        with self.assertRaises(ValueError):self.decide(a['id'],retained_attachment_ids=['other-image'])
        d=self.decide(a['id'],retained_attachment_ids=['test-image'])['decision']
        attachment=d['attachments'][0]
        self.assertNotIn('stored_name',attachment)
        self.assertEqual(self.db.get_label_attachment(attachment['id'])['stored_name'],'private.png')
        self.assertEqual(self.db.get_label_attachment(attachment['id'])['issue_id'],'cn1')
        self.assertEqual(self.db.get_label_attachment('test-image')['revision_id'],a['id'])

    def test_global_decision_does_not_complete_an_unsubmitted_task(self):
        from ra_triage_dashboard.app.work_split import distribute_issue_ids
        split=self.db.apply_work_split(assignments=distribute_issue_ids(['cn1'],[{'name':'alice'},{'name':'bob'}],seed=1,reviewers_per_issue=2),created_by='admin',reviewers_per_issue=2)
        workset=self.db.create_review_workset(baseline_scope='scope',issue_ids=['cn1'],created_by='admin')
        self.db.bind_labeling_task(task_id=split['split_id'],workset_id=workset['id'])
        a=self.vote(task_id=split['split_id'])
        before=self.db.get_label_case(a['label_case']['id'])
        self.decide(a['id'])
        after=self.db.get_label_case(a['label_case']['id'])
        self.assertEqual(before['resolution'],after['resolution'])
        self.assertEqual(after['resolution']['state'],'pending')
        result=self.db.list_labeling_cases(baseline_scopes=['scope'],task_id=split['split_id'],exclusion='active')
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['label_state'],'pending')
        self.assertFalse(result['items'][0]['is_excluded'])

    def test_snapshot_and_gt_candidates_keep_full_decision_reference(self):
        a=self.vote();d=self.decide(a['id'])['decision']
        candidate=next(i for i in self.db.label_gt_candidates(['scope']) if i['issue_id']=='cn1')
        self.assertEqual(candidate['expected_output'],'误触发')
        self.assertEqual(candidate['decision_id'],d['id'])
        self.assertEqual(candidate['status'],'ready')
        exclusion = next(i for i in self.db.case_exclusion_candidate_rows(baseline_scopes=['scope']) if i['issue_id']=='cn1')['case_exclusion']
        self.assertEqual(exclusion['reason_source']['kind'], 'issue_decision')
        self.assertEqual(exclusion['reason_source']['decision_id'], d['id'])

    def test_legacy_sqlite_schema_upgrade_keeps_decision_history(self):
        # Exercise the additive ALTER path on an existing schema, not just a new DB.
        self.vote()
        state=self.db.project_issue_label_states('scope',['cn1'])['cn1']
        self.db.adjudicate_issue_label(baseline_scope='scope',issue_id='cn1',expected_output='误触发',rationale='legacy',actor='judge',actor_source='test',actor_verified=True,expected_source_fingerprint=state['source_fingerprint'])
        with self.db.connect() as c:c.execute('ALTER TABLE issue_label_decisions DROP COLUMN full_result_json')
        self.db.init()
        d=self.db.list_issue_label_decisions(baseline_scope='scope',issue_id='cn1')[0]
        self.assertIsNone(d['is_excluded']);self.assertEqual(d['rationale'],'legacy')
