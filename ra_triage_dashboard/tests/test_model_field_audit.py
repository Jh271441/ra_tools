from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import tempfile
import unittest

from ra_triage_dashboard.app import model_field_audit as audit
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import trail_history as routes


class ModelAuditTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name)/'audit.sqlite3'); self.db.init()
        self.rows = [{'issue_id':'cn00000001', audit.FIELD:'正确触发', audit.INFO:{
            'model_result':{'label':'正确触发'}, 'ra_triage_dashboard':{'should_exclude':False}}}]
        self.changes = [{'issue_id':'cn00000001', audit.FIELD:'成功'}]
        self.actor = SimpleNamespace(username='admin',source='sso',verified=True)
        routes._previews.clear()

    def begin(self):
        return audit.begin(self.db, operation_id='original', source='model_label_normalization',
            actor='service',actor_source='authorized_local_service',reason='1030',rows=self.rows,changes=self.changes)

    def test_only_scalar_enters_durable_audit_and_context_conflicts(self):
        self.begin()
        self.rows[0][audit.FIELD]='成功'
        self.assertEqual(audit.reconcile(self.db,'original',self.rows),{'cn00000001':'succeeded'})
        operation=self.db.trail_operation('original')
        changes, conflicts=audit.restore(operation,self.rows)
        self.assertFalse(conflicts);self.assertEqual(changes,[{'issue_id':'cn00000001',audit.FIELD:'正确触发'}])
        self.rows[0][audit.INFO]['model_result']={'label':'无需协助'}
        self.assertEqual(audit.restore(operation,self.rows)[1],['cn00000001'])
        audit.reconcile(self.db,'original',self.rows)
        self.assertEqual(self.db.trail_operation('original')['status'],'succeeded')
        with self.assertRaises(ValueError):
            audit.operation_items(self.rows,[{**self.changes[0],audit.INFO:{}}])

    def test_real_null_is_preserved_but_unqualified_clear_stays_disabled(self):
        self.rows[0][audit.FIELD]=None; self.begin(); self.rows[0][audit.FIELD]='成功'
        operation=self.db.trail_operation('original')
        self.assertIsNone(operation['items'][0]['before']['value'])
        self.assertTrue(audit.restore(operation,self.rows)[1])
        self.assertEqual(audit.restore(operation,self.rows,null_qualified=True)[0],
            [{'issue_id':'cn00000001',audit.FIELD:None}])

    async def test_preview_commit_readback_retry_and_newer_value_conflict(self):
        self.begin();self.rows[0][audit.FIELD]='成功';audit.reconcile(self.db,'original',self.rows)
        writes=[]
        async def snapshot(ids,field):return deepcopy(self.rows)
        def writer(changes,**kwargs):
            writes.extend(deepcopy(changes))
            for change in changes:self.rows[0].update(change)
            return {'failed_issue_ids':[]}
        settings=SimpleNamespace(trail_attribute_info_field=audit.INFO,ra_auto_triage_root=Path('/tmp'),
            trail_attribute_write_chunk_size=10)
        with patch.object(routes,'database',self.db),patch.object(routes,'settings',settings),\
             patch.object(routes,'_admin',AsyncMock(return_value=self.actor)),\
             patch.object(routes,'_snapshot',snapshot),patch.object(routes,'write_trail_model_results',writer):
            req=SimpleNamespace(json=AsyncMock(return_value={'reason':'restore enum','issue_ids':['cn00000001']}))
            preview=await routes.restore_preview('original',req)
            self.assertTrue(preview['ready']);self.assertFalse(writes)
            req=SimpleNamespace(json=AsyncMock(return_value={'confirm':True,'preview_id':preview['preview_id']}))
            result=await routes.restore_commit('original',req)
            self.assertTrue(result['ok']);self.assertEqual(self.rows[0][audit.FIELD],'正确触发')
            self.assertEqual(len(writes),1);self.assertEqual(set(writes[0]),{'issue_id',audit.FIELD})
            self.assertEqual(await routes.restore_commit('original',req),result)
            self.assertEqual(len(writes),1)
            with self.assertRaises(ValueError):self.begin()


if __name__=='__main__':unittest.main()
