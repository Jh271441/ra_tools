"""GT relation is a resolved Case-label comparison, independent of model correctness."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from ra_triage_dashboard.app.routers import cases
from ra_triage_dashboard.app.routers.labeling_api import queries, exports
import test_labeling_version_membership as fixture


class GtRelationFilterTest(IsolatedAsyncioTestCase):
    setUp = fixture.LabelingVersionMembershipTests.setUp

    def seed(self):
        self.db.upsert_issues([
            dict(issue_id=f'cn{n}', gt_label='' if n == 103 else '正确触发')
            for n in range(101, 107)
        ], source='test', replace_gt=True, baseline_scope='native')
        for issue, label, author in [
            ('cn101', '误触发', 'alice'), ('cn102', '正确触发', 'alice'),
            ('cn103', '误触发', 'alice'), ('cn105', '误触发', 'alice'),
            ('cn105', '正确触发', 'bob'),
        ]:
            self.db.create_label_revision(issue_id=issue, expected_output=label, tags=[],
                evidence_gaps=[], rationale='fixture', is_excluded=False, author=author,
                author_source='test', author_verified=True, expected_previous_revision_id=None)

    async def test_case_review_queue_summary_clusters_and_export_share_scope(self):
        self.seed()
        before = self.db.change_revision()
        for relation, expected in [
            ('differs_from_gt', ['cn101']), ('matches_gt', ['cn102']),
            ('fills_missing_gt', ['cn103']), ('matches_gt,differs_from_gt', ['cn101', 'cn102']),
        ]:
            result = await queries.list_labeling_cases(self.request, baselines='0508', gt_relation=relation, page_size=1)
            self.assertEqual(result['queue_issue_ids'], expected)
            self.assertEqual(result['total'], len(expected))
            self.assertEqual(len(result['items']), 1)
            summary = await queries.labeling_summary(self.request, baselines='0508', gt_relation=relation)
            self.assertEqual(summary['total'], len(expected))
            clusters = await queries.list_labeling_clusters(self.request, baselines='0508', gt_relation=relation)
            self.assertEqual(sum(i['count'] for i in clusters['items']), 0 if relation == 'fills_missing_gt' else len(expected))
            with patch.object(cases, '_review_tag_catalog', return_value=()), patch.object(cases, 'database', self.db), patch.object(cases, 'request_identity', return_value=SimpleNamespace(verified=False, username='')):
                gallery = await cases.list_cases(self.request, baselines='0508', gt_relation=relation, page_size=1)
                ids = await cases.list_case_issue_ids(self.request, baselines='0508', gt_relation=relation)
                empty = await cases.list_case_issue_ids(self.request, baselines='0508', gt_relation=relation, label_state='conflict')
            self.assertEqual(ids['issue_ids'], expected)
            self.assertEqual(gallery['total'], len(expected))
            self.assertEqual(empty['issue_ids'], [])
            request = Mock(query_params={}, json=AsyncMock(return_value=dict(baselines='0508', filters=dict(gt_relation=relation))))
            with patch.object(self.db, 'create_label_gt_export_preview', return_value=dict(id='preview', item_count=0)) as create:
                await exports.create_gt_export_preview(request)
            self.assertEqual(list(create.call_args.kwargs['issue_ids']), expected)
        self.assertEqual(self.db.change_revision(), before)

    async def test_invalid_values_fail_closed_and_status_is_an_and_condition(self):
        self.seed()
        for endpoint in [queries.list_labeling_cases, queries.labeling_summary, queries.list_labeling_clusters, cases.list_cases, cases.list_case_issue_ids]:
            with self.assertRaises(HTTPException) as error:
                await endpoint(self.request, baselines='0508', gt_relation='bad')
            self.assertEqual(error.exception.status_code, 400)
        empty = await queries.list_labeling_cases(self.request, baselines='0508', gt_relation='differs_from_gt', status='conflict')
        self.assertEqual(empty['queue_issue_ids'], [])
        empty = await queries.list_labeling_cases(self.request, baselines='0508', gt_relation='differs_from_gt', gt='误触发')
        self.assertEqual(empty['queue_issue_ids'], [])
        with patch.object(cases, '_review_tag_catalog', return_value=()), patch.object(cases, 'database', self.db), patch.object(cases, 'request_identity', return_value=SimpleNamespace(verified=False, username='')):
            resolved = await cases.list_case_issue_ids(self.request, baselines='0508', gt_relation='differs_from_gt', label_state='resolved')
        self.assertEqual(resolved['issue_ids'], ['cn101'])

    async def test_review_filters_before_pagination_across_candidate_batches(self):
        rows = [dict(issue_id=f'cn{n:04}', baseline_scope='native', gt_label='正确触发') for n in range(405)]
        projections = {row['issue_id']: dict(state='resolved', expected_output='误触发' if n >= 399 else '正确触发') for n, row in enumerate(rows)}
        def iterate(**kwargs):
            self.assertNotIn('gt_relation', kwargs)
            self.assertEqual(kwargs['batch_size'], 400)
            yield rows[:400]
            yield rows[400:]
        db = Mock(iter_case_review_candidate_batches=iterate)
        db.list_cases.side_effect = lambda **kw: dict(items=[r for r in rows if r['issue_id'] in kw['issue_ids']])
        db.project_issue_label_states.side_effect = lambda scope, ids, **kw: {key: projections[key] for key in ids}
        with patch.object(cases, 'database', db), patch.object(cases, '_review_tag_catalog', return_value=()), patch.object(cases, '_with_effective_case_review_status', side_effect=lambda item, _: item):
            result = cases._case_result_with_status_filter(filters=dict(gt_relation=('differs_from_gt',)), review_statuses=(), page=2, page_size=2)
        self.assertEqual(result['total'], 6)
        self.assertEqual([item['issue_id'] for item in result['items']], ['cn0401', 'cn0402'])
        self.assertNotIn('gt_relation', db.list_cases.call_args.kwargs)

    async def test_noncanonical_raw_gt_is_not_reported_as_missing(self):
        self.seed()
        self.db.apply_gt_sync_snapshot(
            scope='native', rows=[dict(issue_id=issue, gt_label='正确触发')
                for issue in ['cn5', 'cn101', 'cn102', 'cn104', 'cn105']],
            source_name='Trail', source_view_id=1000, source_field='ra_merge_result',
            trigger='test', requested_by='test', requested_by_source='test',
            requested_by_verified=False, allow_sparse=True,
            expected_issue_ids=['cn5', *[f'cn{n}' for n in range(101, 107)]],
            raw_labels={'cn106': 'out_of_scope'},
        )
        self.db.create_label_revision(issue_id='cn106', expected_output='误触发', tags=[],
            evidence_gaps=[], rationale='fixture', is_excluded=False, author='alice',
            author_source='test', author_verified=True, expected_previous_revision_id=None)
        result = await queries.list_labeling_cases(self.request, baselines='0508', gt_relation='fills_missing_gt')
        self.assertEqual(result['queue_issue_ids'], ['cn103'])
        with patch.object(cases, 'database', self.db), patch.object(cases, 'request_identity', return_value=SimpleNamespace(verified=False, username='')):
            result = await cases.list_case_issue_ids(self.request, baselines='0508', gt_relation='fills_missing_gt')
        self.assertEqual(result['issue_ids'], ['cn103'])
