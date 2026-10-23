"""Explicit pending-task exclusion decisions retain history and source CAS."""
import tempfile
import unittest
import test_case_labeling as labeling_tests
from ra_triage_dashboard.app.db import LabelAnnotationConflictError
from ra_triage_dashboard.app.work_split import distribute_issue_ids

class ExclusionAdjudicationTest(unittest.TestCase):
    def fixture(self, tmp, *, complete=False):
        db = labeling_tests.CaseLabelingTest().make_db(tmp)
        split = db.apply_work_split(assignments=distribute_issue_ids(['cn1'], [{'name':'alice'},{'name':'bob'}], seed=1, reviewers_per_issue=2), created_by='admin', reviewers_per_issue=2)
        workset = db.create_review_workset(baseline_scope='scope', issue_ids=['cn1'], name='task', created_by='admin')
        db.bind_labeling_task(task_id=split['split_id'], workset_id=workset['id'])
        revisions=[]
        for author,excluded,output in [('alice',True,'误触发' if complete else ''),('bob',False,'误触发')]:
            revisions.append(db.create_label_revision(issue_id='cn1',task_id=split['split_id'],expected_output=output,tags=[],evidence_gaps=[],rationale='original '+author,is_excluded=excluded,author=author,author_source='test',author_verified=True,expected_previous_revision_id=None))
        case=db.get_label_case(revisions[-1]['label_case']['id'])
        args=dict(label_case_id=case['id'],source_revision_ids=[v['id'] for v in case['resolution']['heads']],expected_output='误触发',tags=[],evidence_gaps=[],rationale='No exclusion needed',is_excluded=False,actor='judge',actor_source='test',actor_verified=True,expected_previous_resolution_id=None,adjudication_scope='exclusion',confirm_full_label=True)
        return db,case,args,revisions,split['split_id']

    def test_pending_exclusion_decision_preserves_history_and_removes_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,case,args,revisions,task=self.fixture(tmp)
            self.assertEqual(case['resolution']['state'],'pending')
            self.assertTrue(case['can_adjudicate_exclusion'])
            self.assertTrue(db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])
            gt=db.get_issue('cn1')['gt_label']
            for changes in [dict(confirm_full_label=False),dict(confirm_full_label='true'),dict(rationale=''),dict(adjudication_scope='label')]:
                with self.assertRaises(ValueError):db.adjudicate_label_case(**{**args,**changes})
            result=db.adjudicate_label_case(**args)
            self.assertFalse(db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])
            self.assertEqual(db.labeling_case_issue_ids(baseline_scopes=['scope'],exclusion='excluded'),[])
            self.assertEqual(db.get_issue('cn1')['gt_label'],gt)
            self.assertEqual([v['id'] for v in result['resolution']['heads']],[v['id'] for v in case['resolution']['heads']])
            self.assertEqual(len(result['revisions']),3)
            self.assertEqual(result['resolution']['result_revision']['rationale'],'No exclusion needed')
            with self.assertRaises(LabelAnnotationConflictError):db.adjudicate_label_case(**args)
            self.assertEqual(len(db.get_label_case(case['id'])['revisions']),3)
            db.create_label_revision(issue_id='cn1',task_id=task,expected_output='',tags=[],evidence_gaps=[],rationale='new evidence',is_excluded=True,author='alice',author_source='test',author_verified=True,expected_previous_revision_id=revisions[0]['id'])
            self.assertTrue(db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])
            with self.assertRaises(LabelAnnotationConflictError):db.adjudicate_label_case(**{**args,'expected_previous_resolution_id':result['saved_resolution_id']})

    def test_same_label_different_exclusion_and_readonly_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,case,args,_,task=self.fixture(tmp,complete=True)
            self.assertEqual(case['resolution']['state'],'resolved')
            self.assertTrue(case['can_adjudicate_exclusion'])
            db.adjudicate_label_case(**args)
            # A separate effective source must still keep the overall Issue excluded.
            db.create_label_revision(issue_id='cn1',expected_output='误触发',tags=[],evidence_gaps=[],rationale='other source',is_excluded=True,author='other',author_source='test',author_verified=True,expected_previous_revision_id=None)
            self.assertTrue(db.project_issue_exclusions(['cn1'])['cn1']['is_excluded'])
            with db.connect() as conn:
                conn.execute("UPDATE issue_work_splits SET legacy_read_only=1 WHERE id=?", (task,))
            self.assertFalse(db.get_label_case(case['id'])['can_adjudicate_exclusion'])
            with self.assertRaises(ValueError):db.adjudicate_label_case(**args)
