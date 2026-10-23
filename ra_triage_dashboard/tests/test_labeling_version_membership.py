import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from starlette.requests import Request
from ra_triage_dashboard.app.baseline_registry import BaselineEntry, BaselineRegistry
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.support import baselines
from ra_triage_dashboard.app.routers.labeling_api import queries, exports, snapshots


class LabelingVersionMembershipTests(IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(Path(tmp.name) / 'fixture.sqlite')
        self.db.init()
        self.db.upsert_issues([dict(issue_id='cn'+str(n), gt_label='正确触发', scenario='junction') for n in range(1,5)], source='test', replace_gt=True, baseline_scope='shared-history')
        self.db.upsert_issues([dict(issue_id='cn5', gt_label='正确触发')], source='test', replace_gt=True, baseline_scope='native')
        for family, items in [('20261009', [('cn1',True),('cn2',False)]), ('20261016',[('cn3',True)])]:
            self.db.ingest_version_dataset(family=family, policy=dict(sampling_policy='version_probability_v3',seed='a'*64), batch_key='fixture', actor='test', items=[dict(issue_id=i,software_version='1.gen4-release-'+family+'.1',state='published',is_target=target,is_sample=False,is_low=target) for i,target in items])
        registry = BaselineRegistry((BaselineEntry(id='0508', label='0508', scope='native', loader='test', xlsx=Path('unused')),))
        stack = ExitStack();self.addCleanup(stack.close)
        for target, name, value in [(baselines,'database',self.db),(baselines,'baseline_registry',registry),(queries,'database',self.db),(exports,'database',self.db)]:
            stack.enter_context(patch.object(target,name,value))
        stack.enter_context(patch.object(queries,'_require_labeling_writer',AsyncMock()))
        stack.enter_context(patch.object(queries,'_active_labeling_scopes',AsyncMock(side_effect=lambda scopes:scopes)))
        stack.enter_context(patch.object(exports,'_active_labeling_scopes',AsyncMock(side_effect=lambda scopes:scopes)))
        stack.enter_context(patch.object(exports,'_labeling_actor',return_value=('test','test',True)))
        self.request = Request(dict(type='http',query_string=b'',headers=[]))

    async def test_list_queue_summary_and_clusters_use_current_targets(self):
        for version, expected in [('version-20261009',['cn1']),('version-20261016',['cn3']),('version-20261009,version-20261016',['cn1','cn3'])]:
            result = await queries.list_labeling_cases(self.request,baselines=version,page_size=1)
            self.assertEqual(result['queue_issue_ids'],expected)
            self.assertEqual(result['total'],len(expected))
            self.assertEqual(len(result['items']),1)
            summary = await queries.labeling_summary(self.request,baselines=version)
            self.assertEqual(summary['total'],len(expected))
            clusters = await queries.list_labeling_clusters(self.request,baselines=version)
            self.assertEqual(sum(i['count'] for i in clusters['items']),len(expected))
        page2=await queries.list_labeling_cases(self.request,baselines='version-20261009,version-20261016',page_size=1,page=2)
        self.assertEqual(page2['items'][0]['issue_id'],'cn3')

    async def test_explicit_intersection_empty_target_and_legacy_union(self):
        result=await queries.list_labeling_cases(self.request,baselines='version-20261009',issue_ids='cn2,cn4')
        self.assertEqual(result['total'],0)
        result=await queries.list_labeling_cases(self.request,baselines='version-20261009,0508')
        self.assertEqual(result['queue_issue_ids'],['cn1','cn5'])
        self.assertEqual(baselines.restrict_version_issue_ids('0508',issue_ids=('cn5',)),('cn5',))
        with self.db.connect() as conn:
            conn.execute("UPDATE version_dataset_items SET is_target=0 WHERE dataset_id='release-20261009-odd2'")
        result=await queries.list_labeling_cases(self.request,baselines='version-20261009')
        self.assertEqual(result['queue_issue_ids'],[])
        self.assertEqual(result['total'],0)

    async def test_frozen_task_and_query_parameter_membership(self):
        self.assertEqual(baselines.restrict_version_issue_ids('version-20261009',issue_ids=('cn2',),task_id='frozen-task'),('cn2',))
        self.assertEqual(baselines.restrict_version_issue_ids('version-20261009',task_id='frozen-task'),())
        request=Request(dict(type='http',query_string=b'baselines=version-20261016',headers=[]))
        result=await queries.list_labeling_cases(request)
        self.assertEqual(result['queue_issue_ids'],['cn3'])

    async def test_gt_export_filter_and_explicit_selection_share_membership(self):
        for body in [
            dict(baselines='version-20261009',filters=dict(q='cn')),
            dict(baselines='version-20261009',issue_ids=['cn1','cn2','cn4']),
            dict(baselines='version-20261009'),
        ]:
            request=Mock(query_params={},json=AsyncMock(return_value=body))
            with patch.object(self.db,'create_label_gt_export_preview',return_value=dict(id='preview',item_count=0)) as create:
                await exports.create_gt_export_preview(request)
            self.assertEqual(tuple(create.call_args.kwargs['issue_ids']),('cn1',))

    async def test_gt_candidate_counts_exclude_non_targets(self):
        with patch.object(snapshots, 'database', self.db), \
             patch.object(snapshots, '_require_labeling_admin', AsyncMock()), \
             patch.object(snapshots, '_active_labeling_scopes', AsyncMock(side_effect=lambda scopes:scopes)), \
             patch.object(self.db, 'label_gt_candidates', return_value=[
                 dict(issue_id='cn1', status='ready'), dict(issue_id='cn2', status='conflict'),
             ]):
            result = await snapshots.get_gt_candidates(self.request, baselines='version-20261009')
        self.assertEqual(result['items'], [dict(issue_id='cn1', status='ready')])
        self.assertEqual((result['ready_count'], result['conflict_count']), (1, 0))
