"""Shared Issue tags must scope labeling before paging, queues and exports."""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from ra_triage_dashboard.app.routers.labeling_api import queries, exports, common
from ra_triage_dashboard.app.runtime_catalogs import REVIEW_TAG_CATALOG
from ra_triage_dashboard.app.support.issue_tag_filters import parse_issue_tag_groups
import test_labeling_version_membership as fixture


class LabelingIssueTagsTest(IsolatedAsyncioTestCase):
    def setUp(self):
        fixture.LabelingVersionMembershipTests.setUp(self)
        catalog = patch.object(common, '_review_tag_catalog', return_value=REVIEW_TAG_CATALOG)
        catalog.start(); self.addCleanup(catalog.stop)
        self.heads = {}
        for issue, tags in [('cn1', ['gate', 'intent_u_turn']), ('cn3', ['construction_change', 'intent_straight'])]:
            self.heads[issue] = self.revision(issue, tags)

    def revision(self, issue, tags, previous=None):
        return self.db.create_label_revision(
            issue_id=issue, expected_output='正确触发', tags=tags, evidence_gaps=[],
            rationale='fixture', is_excluded=False, author='alice', author_source='test',
            author_verified=True, expected_previous_revision_id=previous,
        )

    async def test_list_queue_summary_clusters_and_export_share_groups(self):
        before = self.db.change_revision()
        version = 'version-20261009,version-20261016'
        for tags, expected in [('gate,construction_change', ['cn1','cn3']),
                               ('gate,construction_change,intent_u_turn', ['cn1']),
                               ('gate,intent_straight', [])]:
            result = await queries.list_labeling_cases(self.request, baselines=version, issue_tags=tags, page_size=1)
            self.assertEqual(result['queue_issue_ids'], expected)
            self.assertEqual(result['total'], len(expected))
            summary = await queries.labeling_summary(self.request, baselines=version, issue_tags=tags)
            self.assertEqual(summary['total'], len(expected))
            clusters = await queries.list_labeling_clusters(self.request, baselines=version, issue_tags=tags)
            self.assertEqual(sum(i['count'] for i in clusters['items'] if i['kind']=='scenario'),len(expected))
            if expected:
                request = Mock(query_params={}, json=AsyncMock(return_value=dict(baselines=version, filters=dict(issue_tags=tags))))
                with patch.object(self.db,'create_label_gt_export_preview',return_value=dict(id='fixture', item_count=0)) as create:
                    await exports.create_gt_export_preview(request)
                self.assertEqual(create.call_args.kwargs['issue_ids'],expected)
        page2 = await queries.list_labeling_cases(self.request, baselines=version, issue_tags='gate,construction_change', page_size=1,page=2)
        self.assertEqual(page2['items'][0]['issue_id'],'cn3')
        self.assertEqual(self.db.change_revision(),before)

    async def test_current_heads_authoritative_empty_and_invalid_keys(self):
        self.revision('cn1',[],self.heads['cn1']['id'])
        result=await queries.list_labeling_cases(self.request,baselines='version-20261009',issue_tags='gate')
        self.assertEqual(result['total'],0)
        for endpoint in [queries.list_labeling_cases,queries.labeling_summary,queries.list_labeling_clusters]:
            with self.assertRaises(HTTPException) as caught:
                await endpoint(self.request,baselines='version-20261009',issue_tags='unknown-tag')
            self.assertEqual(caught.exception.status_code,400)
        with patch.object(self.db,'project_issue_tag_contexts',return_value={'cn1':{'tags':[], 'decision_id':'current'}}):
            self.assertEqual((await queries.list_labeling_cases(self.request,baselines='version-20261009',issue_tags='gate'))['total'],0)

    async def test_projection_bounded_and_intersects_other_filters(self):
        self.db.upsert_issues([dict(issue_id=f'cn{n}') for n in range(100,901)],source='test',baseline_scope='many',replace_gt=False)
        groups=parse_issue_tag_groups('gate',REVIEW_TAG_CATALOG,{})
        with patch.object(self.db,'project_issue_tag_contexts',return_value={}) as projection:
            result=self.db.list_labeling_cases(baseline_scopes=['many'],issue_tag_groups=groups)
        self.assertEqual(result['total'],0)
        self.assertEqual([len(c.args[0]) for c in projection.call_args_list],[400,400,1])
        result=await queries.list_labeling_cases(self.request,baselines='version-20261009,version-20261016',issue_tags='gate',q='cn3')
        self.assertEqual(result['total'],0)
