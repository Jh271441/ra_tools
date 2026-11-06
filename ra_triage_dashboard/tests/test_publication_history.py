"""Audit and final readback for explicit RD/TE publications, without Trail I/O."""
import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app import rd_results as rd
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.publication_audit import sync_publication_audit, reconcile_publication_history
from ra_triage_dashboard.app.routers import trail_history
from ra_triage_dashboard.app.te_correction_source import TEObservationStore
from ra_triage_dashboard.tests import test_te_corrections as fixtures


class PublicationHistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Database(Path(self.temp.name)/'audit.sqlite3');self.db.init();self.addCleanup(self.db.close)
        self.client=fixtures.TEClient();self.row=dict(issue_id='cn123',state='resolved',label='正确触发',fingerprint='v1')
        self.actor=SimpleNamespace(username='admin',source='kylin_ticket',verified=True)
        self.store=rd.PublicationStore(self.temp.name,audit_database=self.db,actor=self.actor)
        p=patch.object(rd,'local_rows',return_value={'cn123':self.row});p.start();self.addCleanup(p.stop)

    def preview(self):
        return self.store.preview('admin',{'cn123':self.row},rd.read_remote(self.client,['cn123'],mode=rd.TE_MODE),False,'version-20261009',mode=rd.TE_MODE)

    def commit(self,p):
        return self.store.commit(p['id'],'admin',None,self.client,{'cn123'})

    def test_audit_precedes_write_and_final_readback_is_separate_and_idempotent(self):
        p=self.preview();calls=[];fetch=self.client.fetch;update=self.client.update
        def audited_update(values):
            entry=self.db.trail_operation('publication-'+p['id'])
            self.assertEqual(entry['status'],'pending');self.assertTrue(entry['actor_verified'])
            return update(values)
        def counted_fetch(ids):calls.append(ids);return fetch(ids)
        with patch.object(self.client,'update',side_effect=audited_update),patch.object(self.client,'fetch',side_effect=counted_fetch):
            result=self.commit(p)
        self.assertEqual(len(calls),4) # preflight, batch check, verification, final refresh
        self.assertEqual(result['refresh']['items'],[{'issue_id':'cn123','current':'成功'}])
        history=self.db.trail_operation(result['history_operation_id'])
        self.assertEqual(history['status'],'succeeded');self.assertEqual(history['source'],'te_correction')
        self.assertEqual(history['items'][0],dict(issue_id='cn123',field=rd.TE_FIELD,before={'value':'误触发'},after={'value':'成功'}))
        reconcile_publication_history(self.db,self.temp.name);reconcile_publication_history(self.db,self.temp.name)
        self.assertEqual(len(self.db.trail_operation(history['id'])['events']),2)
        self.commit(p);self.assertEqual(len(self.client.calls),1)

    def test_audit_failure_prevents_network_write(self):
        p=self.preview()
        with patch.object(self.db,'begin_trail_operation',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaisesRegex(ValueError,'未上传'):self.commit(p)
        self.assertEqual(self.client.calls,[])
        self.assertEqual(self.store.receipt(p['id'])['state'],'needs_recheck')

    def test_final_refresh_failure_does_not_erase_verified_upload(self):
        p=self.preview();fetch=self.client.fetch;count=[0]
        def fail_final(ids):
            count[0]+=1
            if count[0]==4:raise TimeoutError()
            return fetch(ids)
        with patch.object(self.client,'fetch',side_effect=fail_final):result=self.commit(p)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['results'][0]['state'],'verified')
        self.assertEqual(result['refresh']['status'],'failed')
        self.assertEqual(self.db.trail_operation(result['history_operation_id'])['status'],'succeeded')

    def test_large_historical_rd_receipt_backfills_original_time_without_identity_invention(self):
        count=628;record=dict(id='a'*32,actor='old-user',mode='rd',state='complete',created_at=1_790_000_000,
            finished_at=1_790_000_010,baselines='version-20261009',items=[],results=[])
        for i in range(count):
            iid=f'cn{i}';record['items'].append(dict(issue_id=iid,eligible=True,before={rd.FIELD:None},desired='误触发'))
            record['results'].append(dict(issue_id=iid,state='verified'))
        sync_publication_audit(self.db,record);sync_publication_audit(self.db,record)
        history=self.db.trail_operation('publication-'+record['id'])
        self.assertEqual(history['item_count'],count);self.assertFalse(history['actor_verified'])
        self.assertEqual(history['created_at'],datetime.fromtimestamp(record['created_at'],timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'))
        self.assertEqual(len(history['events']),2)
        self.assertEqual(self.db.list_trail_operations(issue_ids=['cn627'])['total'],1)
        self.assertEqual(self.db.list_trail_operations(issue_ids=[])['total'],0)
        self.assertEqual(self.db.list_trail_operations(page=99,page_size=10)['page'],1)

    def test_label_audit_is_read_only_in_unified_history_restore_routes(self):
        result=self.commit(self.preview());operation=result['history_operation_id']
        settings=SimpleNamespace(data_dir=self.temp.name)
        with patch.object(trail_history,'database',self.db),patch.object(trail_history,'settings',settings):
            detail=asyncio.run(trail_history.detail(operation));self.assertFalse(detail['restorable'])
            with patch.object(trail_history,'_admin',return_value=self.actor),patch.object(trail_history,'_snapshot',side_effect=AssertionError('no Trail query')):
                with self.assertRaises(Exception) as exc:asyncio.run(trail_history.verify(operation,None))
                self.assertEqual(exc.exception.status_code,409)

    def test_readbacks_overlay_only_older_source_without_fabricating_full_snapshot(self):
        store=TEObservationStore(self.temp.name,'fixture');record=dict(id='b'*32,baselines='version-20261009')
        store.record_readback(record,dict(status='ready',checked_at=2_000_000_000,items=[dict(issue_id='cn123',current='成功')]))
        observations={'cn123':dict(issue_id='cn123',te_value='误触发'),'cn124':dict(issue_id='cn124',te_value='误触发')}
        metadata,rows=store.apply_readbacks(record['baselines'],{'last_success_at':'2026-01-01T00:00:00Z'},copy.deepcopy(observations))
        self.assertEqual(rows['cn123']['te_value'],'成功');self.assertEqual(rows['cn124']['te_value'],'误触发')
        self.assertEqual(metadata['last_success_at'],'2026-01-01T00:00:00Z')
        _,rows=store.apply_readbacks(record['baselines'],{'last_success_at':'2040-01-01T00:00:00Z'},copy.deepcopy(observations))
        self.assertEqual(rows,observations)


class PublicationRefreshRoutesTest(unittest.TestCase):
    def setUp(self):fixtures.TERoutesTest.setUp(self)

    def test_completed_te_updates_summary_and_history_without_a_browser(self):
        self.routes.settings.trail_te_write_enabled=True
        p=self.http.post('/api/rd-results/preview',json=self.body,headers=self.headers).json()
        result=self.http.post('/api/rd-results/commit',json=dict(operation_id=p['id'],confirmed=True),headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['refresh']['status'],'ready')
        summary=self.http.get('/api/rd-results?baselines=version-20261016&mode=te-correction').json()
        self.assertEqual(summary['items'][0]['te_current'],'成功');self.assertEqual(summary['counts']['same'],1)
        self.assertEqual(self.audit_db.list_trail_operations(source='te_correction')['total'],1)
