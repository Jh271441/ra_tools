"""Discussion destinations, historical visibility and cross-entry consistency."""
import asyncio
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import test_combined_reviews as workflow
from ra_triage_dashboard.app.routers.labeling_api import comments as labeling
from ra_triage_dashboard.app.routers import campaigns
from test_review_comments import json_request


class DiscussionScopeTest(unittest.TestCase):
    setUp = workflow.CombinedReviewWorkflowTest.setUp
    campaign = workflow.CombinedReviewWorkflowTest.campaign

    def create(self, **kwargs):
        return self.db.create_review_comment(issue_id='cn1', author='alice', body='discussion', **kwargs)

    def test_task_comments_without_old_links_appear_in_both_entries(self):
        task = self.campaign(0)
        other = self.campaign(1)
        public = self.create(discussion_channel='case')
        current = self.create(discussion_channel='campaign', campaign_id=task['id'])
        outside = self.create(discussion_channel='campaign', campaign_id=other['id'])
        review = self.create(model_run_id=self.runs[0]['id'])
        rows = self.db.list_label_comments(issue_id='cn1', task_id=task['id'])
        self.assertEqual([r['id'] for r in rows], [public['id'], current['id']])
        self.assertEqual(rows[1]['label_task_id'], task['id'])
        self.assertEqual(rows[1]['task_name'], task['name'])
        self.assertEqual([r['id'] for r in self.db.list_label_comments(issue_id='cn1', task_id=task['id'], discussion_channel='campaign')], [current['id']])
        self.assertEqual([r['id'] for r in self.db.list_label_comments(issue_id='cn1', discussion_channel='case')], [public['id']])
        self.assertEqual({r['id'] for r in self.db.list_label_comments(issue_id='cn1')}, {public['id'],current['id'],outside['id']})
        self.assertNotIn(review['id'], {r['id'] for r in rows})
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) n FROM label_comment_links').fetchone()['n'], 0)

    def test_combined_task_labeling_post_and_reply_preserve_scope_without_review_writes(self):
        task = self.campaign(0)
        with patch.object(labeling, 'database', self.db), patch.object(labeling, '_require_labeling_writer', new=AsyncMock()), patch.object(labeling, '_require_active_labeling_issue', new=AsyncMock(return_value=self.db.get_issue('cn1'))), patch.object(labeling, '_labeling_actor', return_value=('alice','test',True)), patch.object(labeling, 'settings', SimpleNamespace(dchat_notifications_enabled=False)):
            saved = asyncio.run(labeling._create_label_comment_record('cn1', json_request({}), {'body':'task message','task_id':task['id']}))
            comment = saved['comment']
            self.assertEqual(comment['campaign_id'],task['id'])
            self.assertEqual(comment['discussion_channel'],'campaign')
            reply = asyncio.run(labeling._create_label_comment_record('cn1', json_request({}), {'body':'reply','task_id':task['id'],'reply_to_id':comment['id']}))
            self.assertEqual(reply['comment']['reply_to_id'],comment['id'])
            for wrong_task in ('', self.campaign(1)['id']):
                with self.assertRaises(HTTPException):
                    asyncio.run(labeling._create_label_comment_record('cn1',json_request({}),{'body':'wrong','task_id':wrong_task,'reply_to_id':comment['id']}))
            listed = asyncio.run(labeling.list_labeling_comments('cn1',json_request({}),task_id=task['id']))
            self.assertEqual(listed['task']['name'],task['name'])
            self.assertFalse(listed['task']['read_only'])
            self.db.transition_campaign(campaign_id=task['id'],action='supersede',actor='alice',expected_revision=1,idempotency_key='replace',reason='test')
            listed = asyncio.run(labeling.list_labeling_comments('cn1',json_request({}),task_id=task['id']))
            self.assertTrue(listed['task']['read_only'])
            self.assertEqual(len(listed['comments']),2)
            with self.assertRaises(HTTPException):
                asyncio.run(labeling._create_label_comment_record('cn1',json_request({}),{'body':'closed reply','task_id':task['id'],'reply_to_id':comment['id']}))
            public = asyncio.run(labeling._create_label_comment_record('cn1',json_request({}),{'body':'public survives'}))
            self.assertEqual(public['comment']['campaign_id'],'')
        with self.db.connect() as conn:
            for table in ['combined_review_submissions','label_revisions','model_review_revisions']:
                self.assertEqual(conn.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n'],0)

    def test_task_discussion_reports_historical_state_and_preserves_admin_guard(self):
        task=self.campaign(0)
        with patch.object(campaigns,'database',self.db):
            data=asyncio.run(campaigns.get_campaign_discussion(task['id'],'cn1'))
            self.assertEqual(data['task']['name'],task['name'])
            self.assertFalse(data['task']['read_only'])
            with patch.object(campaigns,'_campaign_admin',side_effect=HTTPException(403,'admin required')):
                with self.assertRaises(HTTPException):
                    asyncio.run(campaigns.create_campaign_comment(task['id'],'cn1',json_request({'body':'no permission'})))

    def test_notification_links_follow_stored_scope_and_keep_self_reminders(self):
        from urllib.parse import parse_qs, urlparse
        from ra_triage_dashboard.app.dchat import build_discussion_url
        from ra_triage_dashboard.app.review_mentions import notification_recipients
        self.assertEqual(notification_recipients(['alice'],author='alice'),['alice'])
        task=self.campaign(0)
        for channel,kwargs,path in [
            ('case',{},'/manual/case-labeling'),
            ('campaign',{'campaign_id':task['id']},'/manual/campaigns'),
            ('model_review',{'model_run_id':self.runs[0]['id']},'/manual/review'),
        ]:
            comment=self.create(discussion_channel=channel,notification_recipients=['alice'],**kwargs)
            item=self.db.claim_comment_notification(now='2099-01-01T00:00:00+00:00')
            self.assertEqual(item['discussion_channel'],channel)
            self.assertEqual(item['campaign_id'],kwargs.get('campaign_id',''))
            url=build_discussion_url('https://example.test/manual/review?old=1#old',issue_id=item['issue_id'],discussion_channel=item['discussion_channel'],campaign_id=item['campaign_id'],baseline_id='0508',model_run_id=item['model_run_id'],comment_id=comment['id'])
            parsed=urlparse(url); query=parse_qs(parsed.query)
            self.assertEqual(parsed.path,path)
            self.assertEqual(query['comment'],[str(comment['id'])])
            self.assertEqual(query['comments'],['1'])
            self.assertNotIn('old',query)
            if channel=='campaign': self.assertEqual(query['campaign'],[task['id']])
            if channel=='model_review': self.assertEqual(query['run'],[self.runs[0]['id']])
            if channel=='case': self.assertNotIn('campaign',query)
            if channel!='model_review': self.assertEqual(query['baselines'],['0508'])
        with self.assertRaisesRegex(ValueError,'任务信息'):
            build_discussion_url('https://example.test/manual/review',issue_id='cn1',discussion_channel='campaign')

    def test_notification_dispatcher_uses_scoped_url_without_network(self):
        from ra_triage_dashboard.app.dchat import DChatSendResult
        from ra_triage_dashboard.app.review_notification_dispatcher import ReviewNotificationDispatcher
        comment=self.create(discussion_channel='case',notification_recipients=['alice'])
        settings=SimpleNamespace(dchat_delivery_mode='loopback',kylin_sso_return_url='https://example.test/manual/review',dchat_max_attempts=3)
        sent=[]
        def fake_send(recipient,text):
            sent.append((recipient,text));return DChatSendResult('trace','message')
        async def dispatch():
            dispatcher=ReviewNotificationDispatcher(settings,self.db,baseline_ids_by_scope={"scope":"0508"})
            return dispatcher._dispatch_one(),dispatcher._dispatch_one()
        with patch('ra_triage_dashboard.app.review_notification_dispatcher.DChatLoopbackClient.send_to_username',side_effect=fake_send):
            self.assertEqual(asyncio.run(dispatch()),(True,False))
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0][0],'alice')
        self.assertIn('/manual/case-labeling?',sent[0][1])
        self.assertIn('comment='+str(comment['id']),sent[0][1])
        self.assertIn('baselines=0508',sent[0][1])
        self.assertNotIn('baselines=scope',sent[0][1])
        self.assertEqual(self.db.comment_notification_status()['sent'],1)

    def test_actual_frontend_discussion_behavior(self):
        root=Path(__file__).resolve().parents[2]
        result=subprocess.run(['node',str(Path(__file__).with_name('discussion_scope.cjs'))],cwd=root,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
