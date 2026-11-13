"""Notification provenance and routing: synthetic DB and mocked transport only."""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import test_combined_reviews as workflow
import test_version_campaign_physical as version_workflow
from ra_triage_dashboard.app.comment_source import resolve_comment_source, comment_source_label, save_comment_review_context
from ra_triage_dashboard.app.dchat import build_discussion_url, DChatSendResult
from ra_triage_dashboard.app.review_notification_dispatcher import ReviewNotificationDispatcher
from ra_triage_dashboard.app.comment_submission import comment_request_fingerprint


class CommentSourceTest(unittest.TestCase):
    setUp = workflow.CombinedReviewWorkflowTest.setUp
    campaign = workflow.CombinedReviewWorkflowTest.campaign

    def test_ordinary_review_discussion_and_case_reply_keep_validated_review_entry(self):
        task = self.campaign(0)
        navigation=Path(self.tmp.name)/'comment_navigation'
        body = 'Ordinary comment from Review @bob'
        root = self.db.create_review_comment(issue_id='cn1', discussion_channel='case',
            unified_issue_discussion=True, author='alice',author_source='test',author_verified=True,
            body=body,client_request_id='review-navigation-1',
            request_fingerprint=comment_request_fingerprint(body,None,[]),
            review_context={'model_run_id':task['evaluation_run_id'],'campaign_id':task['id']},
            record_review_context=lambda record:save_comment_review_context(navigation,record),
            notification_recipients=['bob'])
        for comment in [root,self.reply(root)]:
            source=resolve_comment_source(self.db,comment['id'],navigation_dir=navigation)
            self.assertEqual(source['kind'],'review_discussion')
            self.assertTrue(source['review_link_available'])
            parsed=urlparse(self.url(comment,source));query=parse_qs(parsed.query)
            self.assertEqual(parsed.path,'/manual/review')
            self.assertEqual(query['run'],[task['evaluation_run_id']])
            self.assertEqual(query['work_split'],[task['id']])
            self.assertEqual(query['comment'],[str(comment['id'])])
        self.assertEqual(len(self.db.list_issue_discussion('cn1')),2)
        with self.db.connect() as conn:
            row=conn.execute('SELECT * FROM review_comments WHERE id=?',(root['id'],)).fetchone()
            self.assertEqual(row['discussion_channel'],'case')
            self.assertEqual(row['evaluation_run_id'],'')
            self.assertEqual(conn.execute('SELECT COUNT(*) n FROM model_review_revisions').fetchone()['n'],0)
        # A retry with changed navigation must reuse the original receipt/outbox.
        replay=self.db.create_review_comment(issue_id='cn1', discussion_channel='case',
            unified_issue_discussion=True,author='alice',author_verified=True,body=body,
            client_request_id='review-navigation-1',request_fingerprint=comment_request_fingerprint(body,None,[]),
            review_context={'model_run_id':'missing'})
        self.assertEqual(replay['id'],root['id'])
        settings=SimpleNamespace(dchat_delivery_mode='loopback',data_dir=Path(self.tmp.name),
            kylin_sso_return_url='https://example.test/manual/review',dchat_max_attempts=3)
        sent=[]
        dispatcher=ReviewNotificationDispatcher(settings,self.db,baseline_ids_by_scope={'scope':'1030'})
        with patch('ra_triage_dashboard.app.review_notification_dispatcher.DChatLoopbackClient.send_to_username',
                   side_effect=lambda recipient,text:(sent.append(text) or DChatSendResult('trace','message'))):
            self.assertTrue(dispatcher._dispatch_one());self.assertTrue(dispatcher._dispatch_one())
        for text in sent:
            self.assertIn('判错复核讨论 / Review discussion',text)
            self.assertIn('/manual/review?',text)
            self.assertIn(task['evaluation_run_id'],text)
            self.assertIn(task['id'],text)
        self.db.transition_campaign(campaign_id=task['id'],action='supersede',actor='alice',
            expected_revision=1,idempotency_key='close-review-entry',reason='test')
        unavailable=resolve_comment_source(self.db,root['id'],navigation_dir=navigation)
        self.assertFalse(unavailable['review_link_available'])
        self.assertEqual(urlparse(self.url(root,unavailable)).path,'/manual/case-labeling')

    def test_invalid_optional_review_entry_never_blocks_issue_discussion(self):
        task=self.campaign(0)
        directory=Path(self.tmp.name)/'navigation'
        origins=[{'model_run_id':'missing'},
                 {'model_run_id':task['evaluation_run_id'],'campaign_id':'missing'},
                 {'model_run_id':task['evaluation_run_id'],'campaign_id':self.campaign(1)['id']}]
        for index,origin in enumerate(origins):
            comment=self.db.create_review_comment(issue_id='cn1',discussion_channel='case',unified_issue_discussion=True,
                author='alice',author_verified=True,body=f'Optional origin {index}',review_context=origin,
                record_review_context=lambda record:save_comment_review_context(directory,record))
            source=resolve_comment_source(self.db,comment['id'],navigation_dir=directory)
            self.assertEqual(source['kind'],'issue_discussion' if index==0 else 'review_discussion')
            if index:
                self.assertEqual(source['model_run_id'],task['evaluation_run_id'])
                self.assertEqual(source['campaign_id'],'')
                self.assertTrue(source['review_link_available'])
        self.db.transition_campaign(campaign_id=task['id'],action='supersede',actor='alice',
            expected_revision=1,idempotency_key='expire-optional-entry',reason='test')
        comment=self.db.create_review_comment(issue_id='cn1',discussion_channel='case',unified_issue_discussion=True,
            author='alice',author_verified=True,body='Closed optional task',
            review_context={'model_run_id':task['evaluation_run_id'],'campaign_id':task['id']},
            record_review_context=lambda record:save_comment_review_context(directory,record))
        source=resolve_comment_source(self.db,comment['id'],navigation_dir=directory)
        self.assertEqual(source['model_run_id'],task['evaluation_run_id'])
        self.assertEqual(source['campaign_id'],'')
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) n FROM review_comments').fetchone()['n'],4)
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM review_comments WHERE model_run_id<>'' OR campaign_id<>'' OR evaluation_run_id<>''").fetchone()['n'],0)

    def test_optional_review_entry_resolves_issue_specific_human_task_redirect(self):
        old=self.campaign(0)
        target=self.campaign(0,assignees=['bob'])
        directory=Path(self.tmp.name)/'navigation'
        with self.db.connect() as conn:
            conn.execute('INSERT INTO human_campaign_redirects(campaign_id,issue_id,target_campaign_id,created_at) VALUES(?,?,?,?)',
                         (old['id'],'cn1',target['id'],'2026-11-13T00:00:00+00:00'))
        comment=self.db.create_review_comment(issue_id='cn1',discussion_channel='case',unified_issue_discussion=True,
            author='alice',author_verified=True,body='Old human task URL',
            review_context={'model_run_id':old['evaluation_run_id'],'campaign_id':old['id']},
            record_review_context=lambda record:save_comment_review_context(directory,record))
        source=resolve_comment_source(self.db,comment['id'],navigation_dir=directory)
        self.assertEqual(source['campaign_id'],target['id'])
        self.assertTrue(source['review_link_available'])

    def test_navigation_write_failure_rolls_back_outbox_and_orphan_cannot_attribute_a_comment(self):
        task=self.campaign(0);directory=Path(self.tmp.name)/'navigation'
        def broken(record):
            save_comment_review_context(directory,record)
            raise RuntimeError('synthetic failure after metadata write')
        with self.assertRaises(RuntimeError):
            self.db.create_review_comment(issue_id='cn1',discussion_channel='case',unified_issue_discussion=True,
                author='alice',author_verified=True,body='Original transaction',notification_recipients=['bob'],
                review_context={'model_run_id':task['evaluation_run_id']},record_review_context=broken)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) n FROM review_comments').fetchone()['n'],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) n FROM comment_notifications').fetchone()['n'],0)
        comment=self.db.create_review_comment(issue_id='cn1',discussion_channel='case',author='alice',
            author_verified=True,body='A different comment')
        self.assertEqual(resolve_comment_source(self.db,comment['id'],navigation_dir=directory)['kind'],'issue_discussion')

    def combined(self):
        task = self.campaign(0)
        context = self.db.combined_review_context(issue_id='cn1', campaign_id=task['id'], reviewer='alice')
        self.db.submit_combined_review(
            issue_id='cn1', campaign_id=task['id'], model_run_id=task['evaluation_run_id'],
            reviewer='alice', reviewer_source='test', reviewer_verified=True,
            model_review_status='completed', reason='review', missing_evidence=[],
            expected_output='误触发', tags=[], rationale='Reason @bob',
            expected_model_review_storage_id=context['model_review_storage_id'],
            expected_case_revision_id=context['case_revision_id'],
            expected_label_state_fingerprint=context['label_state_fingerprint'],
            idempotency_key='source-test', mention_recipients=['bob'],
        )
        with self.db.connect() as conn:
            comment = dict(conn.execute('SELECT * FROM review_comments ORDER BY id DESC LIMIT 1').fetchone())
        return task, comment

    def reply(self, parent, author='bob'):
        return self.db.create_review_comment(issue_id='cn1', discussion_channel='case',
            baseline_scope='scope', author=author, author_source='test', author_verified=True,
            body='Reply @alice', reply_to_id=parent['id'], notification_recipients=['alice'])

    def url(self, comment, source):
        return build_discussion_url('https://example.test/manual/review?old=1#old',
            issue_id='cn1', discussion_channel='case', baseline_id='0821',
            comment_id=comment['id'], notification_source=source)

    def test_combined_root_and_reply_chain_use_original_task_and_exact_comment(self):
        task, root = self.combined()
        before = self.db.change_revision()
        source = resolve_comment_source(self.db, root['id'])
        self.assertEqual(self.db.change_revision(), before, 'source projection is read-only')
        self.assertEqual(source['kind'], 'combined_review')
        self.assertEqual(source['campaign_id'], task['id'])
        self.assertTrue(source['review_link_available'])
        self.assertIn('联合复核 / Combined review', comment_source_label(source))
        for comment in [root, self.reply(root)]:
            if comment is not root:
                comment = self.reply(comment, 'alice')
            inherited = resolve_comment_source(self.db, comment['id'])
            self.assertEqual(inherited, source)
            parsed = urlparse(self.url(comment, inherited)); query = parse_qs(parsed.query)
            self.assertEqual(parsed.path, '/manual/review')
            self.assertEqual(query, {'issue':['cn1'], 'run':[task['evaluation_run_id']],
                'comparison':['all'], 'work_split':[task['id']], 'baselines':['0821'],
                'comments':['1'], 'channel':['case'], 'comment':[str(comment['id'])],
                'source':['combined_review']})

    def test_case_labels_do_not_acquire_task_from_membership_or_later_acknowledgment(self):
        task = self.campaign(0)
        revision = self.db.create_label_revision(issue_id='cn1', expected_output='误触发',
            tags=[], evidence_gaps=[], rationale='Reason @bob', is_excluded=False,
            author='alice', author_source='test', author_verified=True,
            expected_previous_revision_id=None, mention_recipients=['bob'])
        root = self.db.get_review_comment(revision['notification']['comment_id'])
        source = resolve_comment_source(self.db, root['id'])
        self.assertEqual(source['kind'], 'issue_label')
        self.assertEqual(urlparse(self.url(root, source)).path, '/manual/case-labeling')
        context = self.db.combined_review_context(issue_id='cn1', campaign_id=task['id'], reviewer='alice')
        self.db.submit_combined_review(issue_id='cn1', campaign_id=task['id'],
            model_run_id=task['evaluation_run_id'], reviewer='alice', reviewer_source='test',
            reviewer_verified=True, model_review_status='completed', reason='review', missing_evidence=[],
            expected_output='误触发', tags=[], rationale='Reason @bob',
            expected_model_review_storage_id=context['model_review_storage_id'],
            expected_case_revision_id=context['case_revision_id'],
            expected_label_state_fingerprint=context['label_state_fingerprint'], idempotency_key='ack')
        self.assertEqual(resolve_comment_source(self.db, root['id']), source)
        self.assertEqual(resolve_comment_source(self.db, self.reply(root)['id']), source)

    def test_prefix_spoof_different_actor_timestamp_or_body_does_not_change_destination(self):
        _, root = self.combined()
        for author, stamp, body in [('bob', root['created_at'], root['body']),
                                   ('alice', '2099-01-01T00:00:00+00:00', root['body']),
                                   ('alice', root['created_at'], root['body']+' changed')]:
            with patch('ra_triage_dashboard.app.db_parts.comments.utc_now', return_value=stamp):
                fake = self.db.create_review_comment(issue_id='cn1', author=author,
                    author_source='test', author_verified=True, body=body, discussion_channel='case')
            self.assertEqual(resolve_comment_source(self.db, fake['id'])['kind'], 'issue_discussion')

    def test_unavailable_task_falls_back_without_changing_source_or_discussion(self):
        task, root = self.combined()
        self.db.transition_campaign(campaign_id=task['id'], action='supersede', actor='alice',
            expected_revision=1, idempotency_key='close-source', reason='test')
        source = resolve_comment_source(self.db, self.reply(root)['id'])
        self.assertEqual(source['kind'], 'combined_review')
        self.assertFalse(source['review_link_available'])
        self.assertIn('Original entry unavailable', comment_source_label(source))
        query = parse_qs(urlparse(self.url(root, source)).query)
        self.assertNotIn('work_split', query)
        self.assertEqual(query['channel'], ['case'])

    def test_reply_cycles_and_cross_scope_links_fail_closed(self):
        _, root = self.combined()
        reply = self.reply(root)
        with self.db.connect() as conn:
            conn.execute('UPDATE review_comments SET reply_to_id=? WHERE id=?', (reply['id'],reply['id']))
        self.assertEqual(resolve_comment_source(self.db,reply['id'])['kind'],'issue_discussion')
        with self.db.connect() as conn:
            conn.execute('UPDATE review_comments SET reply_to_id=?, baseline_scope=? WHERE id=?', (root['id'],'other',reply['id']))
        self.assertEqual(resolve_comment_source(self.db,reply['id'])['kind'],'issue_discussion')

    def test_dispatch_source_link_and_receipts_no_replay_or_network(self):
        task, root = self.combined()
        reply = self.reply(root)
        settings = SimpleNamespace(dchat_delivery_mode='loopback',
            kylin_sso_return_url='https://example.test/manual/review', dchat_max_attempts=3)
        sent = []
        def fake_send(recipient, text):
            sent.append((recipient,text)); return DChatSendResult('test-trace','test-message')
        dispatcher = ReviewNotificationDispatcher(settings,self.db,baseline_ids_by_scope={'scope':'0821'})
        with patch('ra_triage_dashboard.app.review_notification_dispatcher.DChatLoopbackClient.send_to_username',side_effect=fake_send):
            self.assertTrue(dispatcher._dispatch_one()); self.assertTrue(dispatcher._dispatch_one())
            self.assertFalse(dispatcher._dispatch_one())
        self.assertEqual([recipient for recipient,_ in sent],['bob','alice'])
        for (_,text), comment in zip(sent,[root,reply]):
            self.assertIn('来源 / Source：[联合复核 / Combined review',text)
            issue_match = re.search(r'在 \[cn1\]\(([^)]+)\)', text)
            self.assertIsNotNone(issue_match)
            issue_query = parse_qs(urlparse(issue_match[1]).query)
            self.assertEqual(issue_query['issue'], ['cn1'])
            self.assertEqual(issue_query['run'], [task['evaluation_run_id']])
            self.assertEqual(issue_query['work_split'], [task['id']])
            self.assertEqual(issue_query['baselines'], ['0821'])
            self.assertFalse({'comments', 'comment', 'channel', 'source'} & issue_query.keys())
            source_match = re.search(r'来源 / Source：\[.*\]\(([^)]+)\)', text)
            self.assertIsNotNone(source_match)
            source_link = urlparse(source_match[1])
            self.assertEqual(source_link.path, '/manual/review')
            self.assertEqual(parse_qs(source_link.query), {
                'run': [task['evaluation_run_id']], 'comparison': ['all'],
                'work_split': [task['id']], 'baselines': ['0821'],
            })
            self.assertIn('[查看评论]('+self.url(comment, resolve_comment_source(self.db, comment['id']))+')', text)
            self.assertIn('work_split='+task['id'],text)
            self.assertIn('comment='+str(comment['id']),text)
            self.assertIn('channel=case',text)
        self.assertEqual(self.db.get_review_comment(root['id'])['campaign_id'],'')
        self.assertEqual(self.db.comment_notification_status()['sent'],2)


class CommentSourceVersionAliasTest(unittest.TestCase):
    setUp = version_workflow.VersionCampaignPhysicalTest.setUp

    def test_optional_review_entry_resolves_archived_version_task_alias(self):
        old=self.campaigns[0]
        merged=self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2',
            backup_sha256='a'*64,actor='authorized-test')
        directory=Path(self.tmp.name)/'navigation'
        comment=self.db.create_review_comment(issue_id='cn1',discussion_channel='case',unified_issue_discussion=True,
            author='jasperchen',author_verified=True,body='Archived version task URL',
            review_context={'model_run_id':self.rid,'campaign_id':old['id']},
            record_review_context=lambda record:save_comment_review_context(directory,record))
        source=resolve_comment_source(self.db,comment['id'],navigation_dir=directory)
        self.assertEqual(source['kind'],'review_discussion')
        self.assertEqual(source['campaign_id'],merged['campaign_id'])
        self.assertTrue(source['review_link_available'])
