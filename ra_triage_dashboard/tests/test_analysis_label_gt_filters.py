"""Reason aggregates, details and exports share the current Issue label filter."""
import csv
import io
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from fastapi import HTTPException
from ra_triage_dashboard.app.routers import analysis, cases
from ra_triage_dashboard.app.routers.labeling_api import queries
from ra_triage_dashboard.app.support import review_payloads, catalogs
import test_labeling_version_membership as fixture


class AnalysisLabelGtFiltersTests(IsolatedAsyncioTestCase):
    def setUp(self):
        fixture.LabelingVersionMembershipTests.setUp(self)
        self.ids = [f'cn{n}' for n in range(101, 128)]
        self.db.upsert_issues([dict(issue_id=i, gt_label='' if i=='cn124' else '正确触发') for i in self.ids], source='test', replace_gt=True, baseline_scope='native')
        self.run, _ = self.db.import_model_run(name='fixture', source_name='fixture', source_sha256='a'*64,
            metadata={}, rows=[dict(issue_id=i, model_label='正确触发') for i in self.ids])
        self.run = self.run["id"]
        for n in range(101, 128):
            issue = f'cn{n}'
            if n != 126:
                self.db.create_label_revision(issue_id=issue, expected_output='正确触发' if 121<=n<=123 else '误触发',
                    tags=[], evidence_gaps=[], rationale='current RD rationale', is_excluded=False,
                    author='alice', author_source='test', author_verified=True, expected_previous_revision_id=None)
            self.db.create_model_review(issue_id=issue, model_run_id=self.run, status='in_progress',
                reason='visible model reason', missing_evidence=[], reviewer='model-reviewer')
        self.db.create_label_revision(issue_id='cn125', expected_output='正确触发', tags=[], evidence_gaps=[],
            rationale='conflicting RD', is_excluded=False, author='bob', author_source='test',
            author_verified=True, expected_previous_revision_id=None)
        self.db.apply_gt_sync_snapshot(scope='native', rows=[dict(issue_id=i,gt_label='正确触发') for i in ['cn5',*self.ids] if i not in ['cn124','cn127']],
            source_name='Trail', source_view_id=1000, source_field='ra_merge_result', trigger='test',
            requested_by='test', requested_by_source='test', requested_by_verified=False,
            allow_sparse=True, expected_issue_ids=['cn5',*self.ids], raw_labels={'cn127':'out_of_scope'})
        stack=ExitStack(); self.addCleanup(stack.close)
        for module in [analysis,cases,review_payloads,catalogs]:
            stack.enter_context(patch.object(module,'database',self.db))
        stack.enter_context(patch.object(cases,'request_identity',return_value=SimpleNamespace(verified=False,username='')))

    async def test_detail_pagination_aggregates_summary_and_csv_share_twenty(self):
        before=self.db.change_revision()
        options=dict(baselines='0508',model_run_id=self.run,gt_relation='differs_from_gt',label_state='resolved',comparison='all')
        first=await analysis.review_reason_analysis(self.request,**options,page=1,page_size=10)
        second=await analysis.review_reason_analysis(self.request,**options,page=2,page_size=10)
        expected=[f'cn{n}' for n in range(101,121)]
        self.assertEqual((first['total'],second['total'],len(first['items']),len(second['items'])),(20,20,10,10))
        self.assertEqual(sorted(row['issue_id'] for row in first['items']+second['items']),expected)
        self.assertEqual(first['filters']['gt_relation'],['differs_from_gt'])
        self.assertEqual(first['filters']['label_state'],['resolved'])
        self.assertEqual(first['gt_update_counts']['all'],20)
        summary=await queries.labeling_summary(self.request,baselines='0508',gt_relation='differs_from_gt',status='resolved',page_size=100)
        self.assertEqual(summary['total'],20)
        for format in ['csv','xlsx']:
            response=await analysis.export_review_reason_analysis(self.request,**options,format=format)
            if format=='csv':
                rows=list(csv.reader(io.StringIO(response.body.decode('utf-8-sig'))))
                self.assertEqual(len(rows),21)
                self.assertEqual({cell for row in rows[1:] for cell in row if cell in expected},set(expected))
            else:
                from openpyxl import load_workbook
                workbook=load_workbook(io.BytesIO(response.body),read_only=True)
                self.assertEqual(workbook.active.max_row,21)
        self.assertEqual(self.db.change_revision(),before)

    async def test_relation_or_state_and_and_raw_gt_and_model_filters(self):
        for values,expected in [
            (dict(gt_relation='matches_gt'),['cn121','cn122','cn123']),
            (dict(gt_relation='fills_missing_gt'),['cn124']),
            (dict(gt_relation='matches_gt,fills_missing_gt'),['cn121','cn122','cn123','cn124']),
            (dict(gt_relation='matches_gt',label_state='conflict'),[]),
            (dict(label_state='conflict'),['cn125']),
            (dict(label_state='none'),['cn126']),
            (dict(label_state='resolved',gt_relation='matches_gt',comparison='mismatch'),[]),
        ]:
            result=await analysis.review_reason_analysis(self.request,baselines='0508',model_run_id=self.run,**values)
            self.assertEqual([i['issue_id'] for i in result['items']],expected)
            export=await analysis.export_review_reason_analysis(self.request,baselines='0508',model_run_id=self.run,**values,format='csv')
            self.assertEqual(len(list(csv.reader(io.StringIO(export.body.decode('utf-8-sig'))))),len(expected)+1)

    async def test_bad_filter_values_fail_for_json_and_export(self):
        for endpoint in [analysis.review_reason_analysis,analysis.export_review_reason_analysis]:
            for extra in [dict(label_state='not-a-state'),dict(gt_relation='not-a-relation')]:
                with self.assertRaises(HTTPException) as caught:
                    await endpoint(self.request,baselines='0508',**extra)
                self.assertEqual(caught.exception.status_code,400)
