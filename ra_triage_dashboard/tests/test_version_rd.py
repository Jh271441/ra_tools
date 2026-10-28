"""RD counts reuse Manual conclusions, never GT/model/joint-review completion."""
import json
import tempfile
import unittest
from unittest.mock import patch

from ra_triage_dashboard.tests import test_case_labeling, test_version_workbench


class VersionRDTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = test_case_labeling.CaseLabelingTest().make_db(self.tmp.name)

    def label(self, iid, output, author='alice', previous=None):
        return self.db.create_label_revision(
            issue_id=iid, expected_output=output, tags=[], evidence_gaps=[],
            rationale='private rationale', is_excluded=False, author=author,
            author_source='test', author_verified=True,
            expected_previous_revision_id=previous,
        )

    def test_actual_scopes_missing_labels_and_counts_only(self):
        self.db.upsert_issues([{'issue_id':'cn3','gt_label':'正确触发'}],
                              source='test', replace_gt=True, baseline_scope='original-other')
        self.label('cn1', '误触发')
        self.label('cn3', '无需协助')
        result = self.db.version_dataset_rd_summary(['cn1','cn2','cn3','cn4','cn1'])
        self.assertEqual((result['total'],result['completed'],result['pending'],result['conflict']), (4,2,2,0))
        self.assertEqual(result['distribution'], {'正确触发':0,'误触发':1,'无需协助':1})
        self.assertEqual(set(result), {'source','source_status','total','completed','pending','conflict','distribution'})
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(self.db.version_dataset_rd_summary([])['total'], 0)

    def test_conflict_decision_and_stale_match_manual(self):
        self.db.set_labeling_scope_state(baseline_scope='scope', status='active', policy_version='test',
                                        source_inventory_sha256='a'*64, updated_by='test')
        first = self.label('cn1','误触发')
        self.label('cn1','正确触发','bob')
        self.assertEqual(self.db.version_dataset_rd_summary(['cn1'])['conflict'],1)
        state = self.db.project_issue_label_states('scope',['cn1'])['cn1']
        self.db.adjudicate_issue_label(baseline_scope='scope',issue_id='cn1',expected_output='无需协助',
            rationale='decision',actor='carol',actor_source='test',actor_verified=True,
            expected_source_fingerprint=state['source_fingerprint'],expected_previous_decision_id=None)
        self.assertEqual(self.db.version_dataset_rd_summary(['cn1'])['distribution']['无需协助'],1)
        self.label('cn1','无需协助',previous=first['id'])
        result=self.db.version_dataset_rd_summary(['cn1'])
        self.assertEqual((result['completed'],result['conflict']),(0,1))
        self.assertEqual(self.db.list_labeling_cases(baseline_scopes=['scope'])['items'][0]['label_state'],'conflict')

    def test_bounded_projection_and_no_gt_fallback(self):
        ids=[f'cn{100+i}' for i in range(405)]
        self.db.upsert_issues([dict(issue_id=i,gt_label='正确触发') for i in ids],
                             source='test',replace_gt=True,baseline_scope='original')
        with patch.object(self.db,'project_issue_label_states',wraps=self.db.project_issue_label_states) as project:
            result=self.db.version_dataset_rd_summary(ids)
            self.assertEqual([len(c.args[1]) for c in project.call_args_list],[400,5])
        self.assertEqual((result['completed'],result['pending']),(0,405))

    def test_filters_pagination_revision_and_te_independence(self):
        fixture=test_version_workbench.VersionWorkbenchTest();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.db.version_dataset_rd_summary=self.db.version_dataset_rd_summary
        fixture.rows[0]['binding']={'assignee':'alice'}
        fixture.rows[0]['review_submitted']=True
        fixture.rows[1]['binding']={'assignee':'bob'}
        fixture.rows[1]['review_submitted']=False
        first=fixture.read(page_size=1)[0]
        # Model prediction and completed joint-review flag do not count as RD.
        self.assertEqual(first['rd']['completed'],0)
        self.assertEqual(first['rd']['total'],2)
        self.label('cn1','误触发')
        current=fixture.read()[0]
        self.assertNotEqual(first['snapshot_revision'],current['snapshot_revision'])
        for kw in ({'page':2,'page_size':1},{'te_status':'unknown'},{'sort':'issue'}):
            self.assertEqual(fixture.read(**kw)[0]['rd'],current['rd'])
        for kw,expected in [({'mode':'low'},(1,1)),({'mode':'samples'},(1,0)),
                            ({'assignee':'alice'},(1,1)),({'review_status':'pending'},(1,0)),
                            ({'q':'cn2'},(1,0)),({'date':'2020-01-01'},(0,0)),
                            ({'q':'cn3','mode':'all'},(0,0))]:
            result=fixture.read(**kw)[0]['rd']
            self.assertEqual((result['total'],result['completed']),expected)
