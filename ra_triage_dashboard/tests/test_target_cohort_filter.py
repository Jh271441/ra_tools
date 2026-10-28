"""Target cohorts are read-only version/Issue membership, not human tags."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException
from starlette.requests import Request
from ra_triage_dashboard.app.support import baselines
from ra_triage_dashboard.app.routers import cases
from ra_triage_dashboard.app.routers.labeling_api import queries, exports
import test_labeling_version_membership as fixture


class TargetCohortFilterTests(IsolatedAsyncioTestCase):
    setUp = fixture.LabelingVersionMembershipTests.setUp

    def seed_cohorts(self):
        self.db.ingest_version_dataset(
            family='20261009', policy=dict(sampling_policy='version_probability_v3', seed='a'*64),
            batch_key='cohorts', actor='test', items=[
                dict(issue_id=issue, software_version='1.gen4-release-20261009.1', state='published',
                     is_target=target, is_sample=sample, is_low=low)
                for issue, target, sample, low in [('cn1', True, True, True), ('cn2', False, True, False), ('cn4', True, False, True)]])

    def cohort_request(self, group, extra=''):
        return Request(dict(type='http', query_string=('target_group='+group+extra).encode(), headers=[]))

    async def test_labeling_list_queue_summary_clusters_and_search_share_scope(self):
        self.seed_cohorts()
        before = self.db.change_revision()
        for group, expected in [('sample', ['cn1']), ('low', ['cn4']), ('all', ['cn1', 'cn4'])]:
            request = self.cohort_request(group)
            result = await queries.list_labeling_cases(request, baselines='version-20261009', page_size=1)
            self.assertEqual(result['queue_issue_ids'], expected)
            self.assertEqual(result['total'], len(expected))
            summary = await queries.labeling_summary(request, baselines='version-20261009')
            self.assertEqual(summary['total'], len(expected))
            clusters = await queries.list_labeling_clusters(request, baselines='version-20261009')
            self.assertEqual(sum(i['count'] for i in clusters['items']), len(expected))
        empty = await queries.list_labeling_cases(self.cohort_request('sample'), baselines='version-20261009', q='cn4')
        self.assertEqual(empty['total'], 0)
        self.assertEqual(self.db.change_revision(), before)

    async def test_review_ids_match_labeling_and_are_independent_of_run_and_tags(self):
        self.seed_cohorts()
        with patch.object(cases, 'database', self.db), patch.object(cases, 'request_identity', return_value=SimpleNamespace(verified=False, username='')):
            for group, expected in [('sample', ['cn1']), ('low', ['cn4'])]:
                result = await cases.list_case_issue_ids(self.cohort_request(group), baselines='version-20261009')
                self.assertEqual(result['issue_ids'], expected)
                self.assertEqual(result['total'], len(expected))

    async def test_version_scope_intersection_and_missing_membership_fail_closed(self):
        self.seed_cohorts()
        for scope, group, expected in [
            ('version-20261016', 'sample', []),
            ('version-20261016', 'low', ['cn3']),
            ('version-20261009,version-20261016', 'low', ['cn3', 'cn4']),
            ('0508', 'low', []),
            ('version-20261009,0508', 'sample', ['cn1']),
        ]:
            result = await queries.list_labeling_cases(self.cohort_request(group), baselines=scope)
            self.assertEqual(result['queue_issue_ids'], expected)
        result = await queries.list_labeling_cases(self.cohort_request('sample'), baselines='version-20261009', issue_ids='cn2,cn4')
        self.assertEqual(result['total'], 0)
        with self.assertRaises(HTTPException) as caught:
            await queries.list_labeling_cases(self.cohort_request('bogus'), baselines='version-20261009')
        self.assertEqual(caught.exception.status_code, 400)

    async def test_filtered_export_preserves_cohort(self):
        self.seed_cohorts()
        for group, expected in [('sample', ['cn1']), ('low', ['cn4'])]:
            request = Mock(query_params={}, json=AsyncMock(return_value=dict(baselines='version-20261009', filters=dict(target_group=group))))
            with patch.object(self.db, 'create_label_gt_export_preview', return_value=dict(id='preview', item_count=0)) as create:
                await exports.create_gt_export_preview(request)
            self.assertEqual(list(create.call_args.kwargs['issue_ids']), expected)

    async def test_current_membership_updates_without_rewriting_human_records(self):
        self.seed_cohorts()
        self.assertEqual(baselines.restrict_version_issue_ids('version-20261009', target_group='sample'), ('cn1',))
        with self.db.connect() as conn:
            conn.execute("UPDATE version_dataset_items SET is_target=0 WHERE issue_id='cn1'")
        result = await queries.list_labeling_cases(self.cohort_request('sample'), baselines='version-20261009')
        self.assertEqual(result['total'], 0)
        # No cohort selection still preserves historical-task membership.
        self.assertEqual(baselines.restrict_version_issue_ids('version-20261009', task_id='historical', issue_ids=('cn1',)), ('cn1',))

    async def test_task_dataset_and_progress_are_intersections(self):
        self.seed_cohorts()
        with patch.object(self.db, 'version_campaign_dataset', return_value='release-20261009-odd2'), \
             patch('ra_triage_dashboard.app.db_parts.assignment_rules.combined_task_progress_ids', return_value={'cn4'}):
            request = self.cohort_request('sample', '&task_view=targets&task_progress=pending&work_assignee=alice')
            ids = baselines.restrict_version_issue_ids('version-20261009,version-20261016', request=request, task_id='campaign-fixture')
            self.assertEqual(ids, ('__empty_target_cohort__',))
            request = self.cohort_request('low', '&task_view=targets&task_progress=pending&work_assignee=alice')
            self.assertEqual(baselines.restrict_version_issue_ids('version-20261009,version-20261016', request=request, task_id='campaign-fixture'), ('cn4',))
