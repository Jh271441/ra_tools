"""Legacy task provenance links must return the full frozen queue."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import HTTPException
from starlette.requests import Request
from ra_triage_dashboard.app.baseline_registry import BaselineEntry, BaselineRegistry
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import cases, analysis
from ra_triage_dashboard.app.support import baselines, filter_parsing, review_payloads, catalogs


class LegacySupplementalScopeTests(IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(Path(tmp.name) / 'fixture.sqlite')
        self.db.init()
        self.sidecar = 'manual_sidecar_version_20261009'
        self.ids = [f'cn{n:03}' for n in range(1, 21)]
        for scope, ids in [('old-daily', self.ids[:10]), (self.sidecar, self.ids[10:] + ['cn021']), ('native', ['cn022'])]:
            self.db.upsert_issues([dict(issue_id=i, gt_label='正确触发') for i in ids], source='test', replace_gt=True, baseline_scope=scope)
        self.run = self.db.ensure_version_stream('20261009', 'test')
        self.db.append_version_predictions(run_id=self.run, rows=[dict(issue_id=i, model_label='误触发', model_confidence=.8) for i in self.ids + ['cn021']])
        self.db.ingest_version_dataset(family='20261009', policy=dict(sampling_policy='version_probability_v3', seed='a'*64), batch_key='fixture', actor='test', items=[dict(issue_id=i, software_version='1.gen4-release-20261009.1', state='published', is_target=True, is_low=False, is_sample=True) for i in self.ids + ['cn021']])
        for scope in ['old-daily', self.sidecar]:
            self.db.set_labeling_scope_state(baseline_scope=scope, status='active', policy_version='test', source_inventory_sha256='a'*64, updated_by='test')
        self.db.set_access_user(username='liangxianghui', role='admin', actor='test')
        workset = self.db.create_review_workset(baseline_scopes=['old-daily', self.sidecar], issue_ids=self.ids, selection_source_run_id=self.run, created_by='test')
        references = [dict(baseline_scope=scope, reference_type='label_result_snapshot', reference_id=self.db.create_label_result_snapshot(workset_id=workset['id'], baseline_scope=scope, created_by='test', allow_partial=True)['id']) for scope in ['old-daily', self.sidecar]]
        self.task = self.db.create_campaign(spec=dict(purpose='model_review', workflow_mode='model_review_and_case_label', evaluation_run_id=self.run, workset_id=workset['id'], name='recheck', references=references, filters=dict(supplemental_review=True, dataset_id='release-20261009-odd2'), members=[dict(issue_id=i, assignees=['liangxianghui']) for i in self.ids]), actor='test', actor_source='test', actor_verified=True, idempotency_key='fixture')['campaign']['id']
        registry = BaselineRegistry(tuple(BaselineEntry(id=i, label=i, scope=s, loader='test', xlsx=Path('unused'), default_selected=i=='0508') for i,s in [('0508','native'),('1009-2026-10-16','old-daily')]))
        stack = ExitStack()
        self.addCleanup(stack.close)
        for module in [baselines, cases, analysis, review_payloads, catalogs]:
            stack.enter_context(patch.object(module, 'database', self.db))
        stack.enter_context(patch.object(baselines, 'baseline_registry', registry))
        stack.enter_context(patch.object(baselines, 'load_partitions', return_value={}))
        stack.enter_context(patch.object(cases, 'request_identity', return_value=SimpleNamespace(verified=False, username='')))
        stack.enter_context(patch.object(analysis, 'request_identity', return_value=SimpleNamespace(verified=False, username='')))
        stack.enter_context(patch.object(cases, '_public_case_items', side_effect=lambda rows, **kw: rows))
        stack.enter_context(patch.object(cases, '_review_tag_catalog', return_value=()))
        self.legacy = '1009-2026-10-16,' + self.sidecar

    def request(self, **params):
        return Request(dict(type='http', query_string=urlencode(dict(work_split_id=self.task, **params)).encode(), headers=[]))

    async def test_old_and_new_links_return_twenty_with_ten_per_page_and_same_export(self):
        before = self.db.change_revision()
        for selection in [self.legacy, 'version-20261009']:
            request = self.request(baselines=selection)
            kwargs = dict(baselines=selection, model_run_id=self.run, work_split_id=self.task, work_assignee='liangxianghui', comparison='all')
            first = await cases.list_cases(request, **kwargs, page_size=10)
            second = await cases.list_cases(request, **kwargs, page_size=10, page=2)
            ids = await cases.list_case_issue_ids(request, **kwargs)
            owners = await cases.work_assignees(request, **{k:v for k,v in kwargs.items() if k!='work_assignee'})
            self.assertEqual((first['total'], second['total'], len(first['items']), len(second['items'])), (20,20,10,10))
            self.assertEqual(sorted(row['issue_id'] for row in first['items'] + second['items']), self.ids)
            self.assertEqual(ids['issue_ids'], self.ids)
            self.assertEqual(owners['total'], 20)
            self.assertEqual(first['filters']['baselines'], ['version-20261009'])
            response = await analysis.export_review_reason_analysis(request, **kwargs, gallery_scope=True, format='csv')
            csv = response.body.decode('utf-8-sig')
            self.assertEqual(len(csv.splitlines()), 21)
            for issue in self.ids:
                self.assertIn(issue, csv)
            self.assertNotIn('cn021', csv)
        self.assertEqual(self.db.change_revision(), before)

    async def test_business_filters_and_deliberate_source_subset_still_apply(self):
        request = self.request(baselines=self.legacy)
        for extra, expected in [(dict(comparison='match'), []), (dict(search='cn001'), ['cn001']), (dict(work_assignee='someone-else'), [])]:
            result = await cases.list_case_issue_ids(request, baselines=self.legacy, work_split_id=self.task, model_run_id=self.run, **extra)
            self.assertEqual(result['issue_ids'], expected)
        result = await cases.list_case_issue_ids(request, baselines='1009-2026-10-16', work_split_id=self.task, model_run_id=self.run)
        self.assertEqual(result['issue_ids'], self.ids[:10])
        # POST callers pass the task explicitly, without query-string task state.
        filters = filter_parsing._case_filter_kwargs(baselines=self.legacy, work_split_id=self.task)
        self.assertEqual(set(filters['baseline_scopes']), {'old-daily', self.sidecar})

    async def test_canonical_task_sample_and_rd_gt_difference_keep_all_twenty(self):
        result = self.db.consolidate_version_campaigns(
            dataset_id='release-20261009-odd2', backup_sha256='a'*64, actor='test')
        self.task = result['campaign_id']
        with patch.object(cases, 'request_identity', return_value=SimpleNamespace(verified=True, username='liangxianghui')):
            context = await cases.review_task_context(self.task, self.request())
        self.assertEqual(context['task']['baseline_ids'], ['version-20261009'])
        for issue in self.ids:
            self.db.create_label_revision(issue_id=issue, expected_output='误触发', tags=[],
                evidence_gaps=[], rationale='existing RD', is_excluded=False, author='rd',
                author_source='test', author_verified=True, expected_previous_revision_id=None)
        before = self.db.change_revision()
        for selection in [self.legacy, 'version-20261009']:
            request = self.request(baselines=selection, target_group='sample')
            kwargs = dict(baselines=selection, model_run_id=self.run, work_split_id=self.task,
                          gt_relation='differs_from_gt', comparison='all')
            first = await cases.list_cases(request, **kwargs, page_size=10)
            second = await cases.list_cases(request, **kwargs, page_size=10, page=2)
            ids = await cases.list_case_issue_ids(request, **kwargs)
            self.assertEqual((first['total'], second['total'], len(first['items']), len(second['items'])), (20,20,10,10))
            self.assertEqual(ids['issue_ids'], self.ids)
            response = await analysis.export_review_reason_analysis(request, **kwargs, gallery_scope=True, format='csv')
            self.assertEqual(len(response.body.decode('utf-8-sig').splitlines()), 21)
        self.assertEqual(self.db.change_revision(), before)
        request = self.request(target_group='sample')
        subset = await cases.list_case_issue_ids(request, baselines='1009-2026-10-16',
            work_split_id=self.task, model_run_id=self.run, gt_relation='differs_from_gt')
        self.assertEqual(subset['issue_ids'], self.ids[:10])

    def test_canonical_flag_without_registration_does_not_upgrade(self):
        with self.db.connect() as conn:
            conn.execute('UPDATE issue_work_splits SET filter_json=? WHERE id=?',
                         ('{"version_live":true,"version_dataset_id":"release-20261009-odd2"}', self.task))
        self.assertEqual(baselines.resolve_request_baseline_ids(self.legacy, request=self.request()), ['1009-2026-10-16'])

    def test_only_exact_complete_selection_of_validated_supplemental_task_is_upgraded(self):
        request = self.request()
        self.assertEqual(baselines.resolve_request_baseline_ids(self.legacy, request=request), ['version-20261009'])
        for selection in [self.legacy+',0508', self.legacy+',unknown-scope', self.legacy.replace(self.sidecar, 'manual_sidecar_version_20990101')]:
            self.assertNotIn('version-20261009', baselines.resolve_request_baseline_ids(selection, request=request))
        for task in ['', 'missing']:
            self.assertEqual(baselines.resolve_request_baseline_ids(self.legacy, task_id=task), ['1009-2026-10-16'])
        with self.db.connect() as conn:
            conn.execute('UPDATE issue_work_splits SET filter_json=? WHERE id=?', ('{}', self.task))
        self.assertEqual(baselines.resolve_request_baseline_ids(self.legacy, request=request), ['1009-2026-10-16'])

    def test_empty_or_outside_members_fail_closed(self):
        with self.db.connect() as conn:
            conn.execute('DELETE FROM version_dataset_items WHERE issue_id=?', (self.ids[-1],))
        with self.assertRaises(HTTPException) as caught:
            baselines.resolve_request_baseline_ids(self.legacy, request=self.request())
        self.assertEqual(caught.exception.status_code, 400)
