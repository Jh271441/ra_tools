import unittest
from types import SimpleNamespace
from ra_triage_dashboard.app.version_review_tasks import task, version_task_detail


class VersionReviewTasksTest(unittest.TestCase):
    def setUp(self):
        self.dataset=dict(id='release-20261009-odd2',run_id='canonical',release_family='20261009',created_at='2026-10-23',updated_at='2026-10-23')
        self.rows=[dict(issue_id='cn1',is_target=True,review_submitted=True,binding=dict(assignee='jasperchen',campaign_id='original-a')),
                   dict(issue_id='cn2',is_target=True,review_submitted=False,binding=dict(assignee='liangxianghui',campaign_id='original-b')),
                   dict(issue_id='cn3',is_target=False,review_submitted=False,binding={})]
        self.db=SimpleNamespace(list_version_datasets=lambda:[self.dataset],version_dataset_gallery_rows=lambda _:self.rows,
                                version_dataset_batches=lambda _:[dict(target_added=1,batch_key='receipt'),dict(target_added=0,batch_key='metadata-only')])
    def test_one_stable_appendable_parent_preserves_source_bindings(self):
        before=task(self.db,self.dataset)
        self.rows.append(dict(issue_id='cn4',is_target=True,review_submitted=False,binding=dict(assignee='jasperchen',campaign_id='append-c')))
        after=task(self.db,self.dataset)
        self.assertEqual(before['split_id'],after['split_id']);self.assertTrue(after['appendable'])
        self.assertEqual((before['total_count'],after['total_count']),(2,3))
        self.assertEqual(after['completed_count'],1)
        self.assertEqual(self.rows[0]['binding']['campaign_id'],'original-a')
        self.assertEqual({m['username']:m['assigned_count'] for m in after['members']},{'jasperchen':2,'liangxianghui':1})
    def test_version_detail_paginates_current_targets_with_original_review_routes(self):
        detail=version_task_detail(self.db,'version:release-20261009-odd2',status='pending')
        self.assertEqual([r['issue_id'] for r in detail['items']],['cn2'])
        self.assertEqual(detail['items'][0]['source_split_id'],'original-b')
        self.assertEqual(len(detail['additions']),1)
        detail=version_task_detail(self.db,'version:release-20261009-odd2',assignee='jasperchen')
        self.assertEqual(detail['filtered_count'],1);self.assertTrue(detail['items'][0]['submitted'])
        self.assertIsNone(version_task_detail(self.db,'version:missing'))

    def test_physical_task_uses_real_campaign_id_and_old_alias(self):
        self.db.version_campaign_id=lambda _: 'canonical-campaign'
        self.db.version_campaign_dataset=lambda _: self.dataset['id']
        for row in self.rows:
            if row.get('binding'): row['binding']['campaign_id']='canonical-campaign'
        result=task(self.db,self.dataset)
        self.assertEqual(result['split_id'],'canonical-campaign')
        self.assertTrue(result['physically_merged'])
        self.assertEqual(version_task_detail(self.db,'old-campaign')['split_id'],'canonical-campaign')
        self.assertEqual(version_task_detail(self.db,'version:'+self.dataset['id'])['split_id'],'canonical-campaign')
