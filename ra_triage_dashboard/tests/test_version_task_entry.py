"""Live target queues are explicit; historical task links remain unchanged."""
import asyncio
import unittest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

import test_version_campaign_physical as fixture
from ra_triage_dashboard.app.support import baselines, filter_parsing
from ra_triage_dashboard.app.routers import analysis, cases


class VersionTaskEntryTest(unittest.TestCase):
    setUp = fixture.VersionCampaignPhysicalTest.setUp
    submit = fixture.VersionCampaignPhysicalTest.submit

    def request(self, view):
        return Request(dict(type='http', query_string=('task_view='+view).encode(), headers=[]))

    def test_context_keeps_version_identity_without_mutation(self):
        receipt = self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2', backup_sha256='a'*64, actor='test')
        revision = self.db.change_revision()
        with patch.object(cases, 'database', self.db), patch.object(baselines, 'database', self.db), \
             patch.object(cases, 'request_identity', return_value=SimpleNamespace(verified=True, username='jasperchen')), \
             patch.object(self.db, 'access_role', return_value='admin'):
            result = asyncio.run(cases.review_task_context(receipt['campaign_id'], self.request('pending')))
        self.assertEqual(result['task']['baseline_ids'], ['version-20261009'])
        self.assertEqual(result['task']['issue_count'], 2)
        self.assertEqual(self.db.change_revision(), revision)

    def test_browser_route_contract(self):
        subprocess.run(['node', str(Path(__file__).with_name('version_task_entry.cjs'))], check=True)

    def test_queue_uses_joint_completion_not_model_status_and_keeps_history(self):
        old = self.campaigns[0]
        ctx = self.db.combined_review_context(issue_id='cn1', campaign_id=old['id'], reviewer='jasperchen')
        self.submit(old, ctx)
        receipt = self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2', backup_sha256='a'*64, actor='test')
        cid = receipt['campaign_id']
        revision = self.db.change_revision()
        with patch.object(baselines, 'database', self.db):
            def ids(view, selected=()):
                return baselines.restrict_version_issue_ids(request=self.request(view), task_id=cid, issue_ids=selected)
            self.assertEqual(ids('targets'), ('cn1', 'cn2'))
            self.assertEqual(ids('pending'), ('cn2',))
            self.assertEqual(ids('pending', ('cn1',)), ('__empty_version_membership__',))
            # Ordinary historical links preserve their full task membership.
            self.assertEqual(baselines.restrict_version_issue_ids('version-20261009', task_id=cid), ())
            self.assertEqual(self.db.change_revision(), revision)
            with self.db.connect() as conn:
                conn.execute('UPDATE combined_review_progress SET case_label_acknowledged=false WHERE campaign_id=?', (cid,))
            self.assertEqual(ids('pending'), ('cn1', 'cn2'))
            self.items[0]['is_target'] = False
            self.items[0]['is_low'] = False
            self.db.ingest_version_dataset(family='20261009', policy=self.policy, items=self.items, batch_key='retire', actor='test')
            self.assertEqual(ids('targets'), ('cn2',))
            self.assertEqual(ids('pending'), ('cn2',))
            for view, task_id in [('bogus', cid), ('pending', ''), ('targets', 'missing')]:
                with self.assertRaises(HTTPException):
                    baselines.restrict_version_issue_ids(request=self.request(view), task_id=task_id)

    def test_gallery_and_analysis_export_apply_same_live_scope(self):
        receipt = self.db.consolidate_version_campaigns(dataset_id='release-20261009-odd2', backup_sha256='a'*64, actor='test')
        cid = receipt['campaign_id']
        self.items[0]['is_target'] = False
        self.db.ingest_version_dataset(family='20261009', policy=self.policy, items=self.items, batch_key='retire', actor='test')
        request = self.request('targets')
        with patch.object(baselines, 'database', self.db), \
             patch.object(filter_parsing, 'resolve_request_baseline_scopes', return_value=['manual_sidecar_test']), \
             patch.object(analysis, 'resolve_request_baseline_scopes', return_value=['manual_sidecar_test']), \
             patch.object(analysis, 'resolve_request_baseline_ids', return_value=['version-20261009']):
            filters = filter_parsing._case_filter_kwargs(request=request, work_split_id=cid)
            self.assertEqual(filters['issue_ids'], ('cn2',))
            self.assertEqual(filters['work_split_id'], cid)
            with patch.object(analysis, '_review_reason_analysis_payload', return_value={'items':[]}) as payload, \
                 patch.object(analysis, '_review_analysis_export_response', return_value='csv'):
                asyncio.run(analysis.review_reason_analysis(request, work_split_id=cid))
                self.assertEqual(payload.call_args.kwargs['issue_ids'], ('cn2',))
                asyncio.run(analysis.export_review_reason_analysis(request, work_split_id=cid, format='csv'))
                self.assertEqual(payload.call_args.kwargs['issue_ids'], ('cn2',))
