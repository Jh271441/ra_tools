import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from ra_triage_dashboard.app import rd_results as rd


class Client:
    def __init__(self, value=None):
        self.row = dict(issue_id='cn123', **{rd.FIELD: value}, **{k: 'preserved' for k in rd.PROTECTED})
        self.calls = []
        self.lost = self.damage = self.failure = False

    def fetch(self, ids):
        return [copy.deepcopy(self.row)]

    def update(self, values):
        self.calls.append(values)
        if not self.failure:
            self.row[rd.FIELD] = values['cn123']
        if self.damage:
            self.row[rd.PROTECTED[0]] = 'changed'
        if self.lost:
            raise TimeoutError()
        return {'code': 0, 'msg': 'success'}


class RDResultsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = rd.PublicationStore(self.temp.name)
        self.client = Client()
        self.row = dict(issue_id='cn123', state='resolved', label='正确触发', fingerprint='v1')
        self.patch = patch.object(rd, 'local_rows', return_value={'cn123': self.row})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def preview(self, overwrite=False):
        return self.store.preview('admin', {'cn123': self.row}, rd.read_remote(self.client,['cn123']), overwrite, 'fixture')

    def commit(self, p):
        return self.store.commit(p['id'], 'admin', None, self.client, {'cn123'})

    def test_exact_field_mapping_and_idempotent_receipt(self):
        p = self.preview()
        self.assertEqual(self.client.calls, [])
        result = self.commit(p)
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(self.client.calls, [{'cn123':'成功'}])
        self.commit(p)
        self.assertEqual(len(self.client.calls), 1)
        self.assertNotIn('after', result['results'][0])

    def test_existing_same_skipped(self):
        self.client.row[rd.FIELD] = '成功'
        self.commit(self.preview())
        self.assertEqual(self.client.calls, [])

    def test_conflict_requires_explicit_overwrite(self):
        self.client.row[rd.FIELD] = '误触发'
        self.assertFalse(self.preview()['items'][0]['eligible'])
        self.commit(self.preview(True))
        self.assertEqual(len(self.client.calls), 1)

    def test_unresolved_never_writes(self):
        for state in ('none','pending','conflict','stale'):
            self.row['state'] = state
            self.commit(self.preview(True))
        self.assertEqual(self.client.calls, [])

    def test_source_change_rejected(self):
        p = self.preview()
        self.row['fingerprint'] = 'v2'
        with self.assertRaises(ValueError): self.commit(p)
        self.assertEqual(self.client.calls, [])
        receipt = self.store.receipt(p['id'])
        self.assertEqual(receipt['state'], 'needs_recheck')
        self.assertEqual(receipt['results'][0]['state'], 'not_attempted')

    def test_remote_change_rejected(self):
        p = self.preview()
        self.client.row[rd.FIELD] = '误触发'
        with self.assertRaises(ValueError): self.commit(p)

    def test_lost_response_readback(self):
        self.client.lost = True
        result = self.commit(self.preview())
        self.assertEqual(result['state'], 'complete')
        self.assertFalse(result['results'][0]['acknowledged'])

    def test_failed_write_no_blind_retry(self):
        self.client.failure = True
        p = self.preview()
        self.assertEqual(self.commit(p)['state'], 'needs_recheck')
        with self.assertRaises(ValueError): self.commit(p)
        self.assertEqual(len(self.client.calls), 1)

    def test_protected_field_change_fails(self):
        self.client.damage = True
        result = self.commit(self.preview())
        self.assertEqual(result['state'], 'needs_recheck')
        self.assertEqual(result['results'][0]['reason'], 'protected_changed')

    def test_same_operation_concurrent_commit_only_writes_once(self):
        p = self.preview()
        entered, release = Event(), Event()
        update = self.client.update
        def delayed(values):
            entered.set()
            self.assertTrue(release.wait(5))
            return update(values)
        with patch.object(self.client, 'update', delayed), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.commit, p)
            self.assertTrue(entered.wait(5))
            try:
                self.assertEqual(self.store.receipt(p['id'])['state'], 'running')
                second = pool.submit(self.commit, p)
            finally:
                release.set()
            self.assertEqual(first.result()['state'], 'complete')
            self.assertEqual(second.result()['state'], 'complete')
        self.assertEqual(len(self.client.calls), 1)

    def test_overwrite_permission_does_not_allow_a_new_remote_value(self):
        self.client.row[rd.FIELD] = '误触发'
        first, second = self.preview(True), self.preview(True)
        self.commit(first)
        with self.assertRaises(ValueError): self.commit(second)
        self.assertEqual(len(self.client.calls), 1)

    def test_interrupted_intent_is_unknown_and_cannot_replay(self):
        p = self.preview()
        record = self.store.get(p['id'])
        record.update(state='running', results=[dict(issue_id='cn123', state='intent')])
        self.store.save(record)
        receipt = self.store.receipt(p['id'])
        self.assertEqual(receipt['state'], 'needs_recheck')
        self.assertEqual(receipt['results'][0]['state'], 'unverified')
        self.assertEqual(receipt['results'][0]['reason'], 'interrupted')
        with self.assertRaises(ValueError): self.commit(p)
        self.assertEqual(self.client.calls, [])

    def test_actor_expiry_and_membership(self):
        p = self.preview()
        with self.assertRaises(ValueError): self.store.commit(p['id'],'other',None,self.client,{'cn123'})
        with self.assertRaises(ValueError): self.store.commit(p['id'],'admin',None,self.client,set())
        record = self.store.get(p['id']); record['expires_at'] = 0; self.store.save(record)
        with self.assertRaises(ValueError): self.commit(p)
        self.assertEqual(self.client.calls, [])

    def test_missing_duplicate_and_invalid_remote(self):
        for rows in ([],[self.client.row,self.client.row],[dict(issue_id='cn123',ra_rd_review_result=3)]):
            with patch.object(self.client,'fetch',return_value=rows):
                with self.assertRaises(ValueError): rd.read_remote(self.client,['cn123'])

    def test_path_validation(self):
        with self.assertRaises(ValueError): self.store.get('../secrets')


class RDBatchTest(unittest.TestCase):
    def test_failures_stop_batch_and_preserve_distinct_outcomes(self):
        for mode in ('rejected', 'write_timeout', 'readback_timeout', 'precheck_timeout', 'changed', 'membership_changed'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                rows = {iid: dict(issue_id=iid, state='resolved', label='正确触发', fingerprint='v1')
                        for iid in ('cn1', 'cn2', 'cn3')}
                remote = {iid: dict(issue_id=iid, **{rd.FIELD: None}, **{k: 'original' for k in rd.PROTECTED}) for iid in rows}
                members = set(rows)
                class BatchClient:
                    calls = []
                    failed_read = False
                    reads = 0
                    def fetch(self, ids):
                        self.reads += 1
                        if ids == ['cn2']:
                            if mode == 'precheck_timeout' or (mode == 'readback_timeout' and len(self.calls) == 2):
                                raise TimeoutError('internal error never returned to browser')
                            if mode == 'changed': remote['cn2'][rd.FIELD] = '误触发'
                        return [copy.deepcopy(remote[i]) for i in ids]
                    def update(self, values):
                        self.calls.append(values)
                        iid = next(iter(values))
                        if iid == 'cn2' and mode == 'rejected': return {'code': 1, 'msg': 'failed'}
                        remote[iid][rd.FIELD] = values[iid]
                        if iid == 'cn1' and mode == 'membership_changed': members.remove('cn2')
                        if iid == 'cn2' and mode == 'write_timeout': raise TimeoutError()
                        return {'code': 0, 'msg': 'success'}
                client, store = BatchClient(), rd.PublicationStore(folder)
                with patch.object(rd, 'local_rows', side_effect=lambda db, ids: {i: rows[i] for i in ids}):
                    p = store.preview('admin', rows, rd.read_remote(client, list(rows)), False, 'fixture')
                    result = store.commit(p['id'], 'admin', None, client, lambda: members)
                states = [r['state'] for r in result['results']]
                if mode == 'write_timeout':
                    self.assertEqual(states, ['verified'] * 3)
                    self.assertEqual(result['state'], 'complete')
                    self.assertFalse(result['results'][1]['acknowledged'])
                else:
                    self.assertEqual(result['state'], 'needs_recheck')
                    self.assertEqual(states, ['verified', 'not_attempted' if mode in ('precheck_timeout', 'changed', 'membership_changed') else 'unverified', 'not_attempted'])
                    self.assertEqual(len(client.calls), 1 if mode in ('precheck_timeout', 'changed', 'membership_changed') else 2)
                    reason = {'rejected':'value_mismatch', 'readback_timeout':'readback_failed', 'precheck_timeout':'check_failed', 'changed':'source_changed', 'membership_changed':'source_changed'}[mode]
                    self.assertEqual(result['results'][1]['reason'], reason)
                    self.assertIsNone(remote['cn3'][rd.FIELD])
                self.assertEqual(store.receipt(p['id']), result)
                self.assertEqual(result['results'][0]['observed'], '成功')
                self.assertNotIn('after', result['results'][0])

    def test_write_payload_rejects_extra_fields_before_network(self):
        transport = rd.RDTransport(None)
        url = 'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/'
        with self.assertRaises(ValueError):
            transport.send_request(url, {'user_location':'cn', 'source_id':1,
                                        'issue_info': {'cn1': {rd.FIELD:'成功', 'ra_merge_result':'成功'}}})


class RDProjectionTest(unittest.TestCase):
    def test_real_projection_active_scope_decision_and_stale(self):
        from ra_triage_dashboard.tests.test_case_labeling import CaseLabelingTest
        with tempfile.TemporaryDirectory() as folder:
            db = CaseLabelingTest().make_db(folder)
            self.addCleanup(db.close)
            db.set_labeling_scope_state(baseline_scope='scope', status='active', policy_version='test', source_inventory_sha256='a'*64, updated_by='test')
            def compare_summary():
                projected, _ = db._project_labeling_cases(baseline_scopes=['scope'])
                local = rd.local_rows(db, ['cn1','cn2'])
                for item in projected:
                    row = local[item['issue_id']]
                    self.assertEqual(item['label_state'], {'none':'pending','stale':'conflict'}.get(row['state'], row['state']))
                    self.assertEqual(item['expected_output'], row['label'])
            def vote(author, label, previous=None):
                return db.create_label_revision(issue_id='cn1', expected_output=label, tags=[], evidence_gaps=[], rationale='human', is_excluded=False,
                    author=author, author_source='test', author_verified=True, expected_previous_revision_id=previous)
            first = vote('alice','正确触发')
            compare_summary()
            self.assertEqual(rd.local_rows(db,['cn1'])['cn1']['label'],'正确触发')
            self.assertNotEqual(rd.local_rows(db,['cn2'])['cn2']['state'],'resolved')
            vote('bob','误触发')
            compare_summary()
            self.assertEqual(rd.local_rows(db,['cn1'])['cn1']['state'],'conflict')
            source = db.project_issue_label_states('scope',['cn1'])['cn1']
            db.adjudicate_issue_label(baseline_scope='scope',issue_id='cn1',expected_output='无需协助', rationale='decision', actor='carol',actor_source='test',actor_verified=True,
                expected_source_fingerprint=source['source_fingerprint'],expected_previous_decision_id=None)
            self.assertEqual(rd.local_rows(db,['cn1'])['cn1']['label'],'无需协助')
            compare_summary()
            vote('alice','无需协助',first['id'])
            self.assertEqual(rd.local_rows(db,['cn1'])['cn1']['state'],'stale')
            compare_summary()
            db.set_labeling_scope_state(baseline_scope='scope', status='shadow', policy_version='test', source_inventory_sha256='a'*64, updated_by='test')
            self.assertEqual(rd.local_rows(db,['cn1','cn2']), {})


class RDRoutesTest(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from ra_triage_dashboard.app.routers import rd_results as routes
        self.routes = routes
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.client = Client()
        self.row = dict(issue_id='cn123',state='resolved',label='正确触发',fingerprint='v1',authors=['alice'])
        self.role = 'admin'
        def identity(*args):
            if self.role not in {'admin','writer'}: raise HTTPException(403)
            return SimpleNamespace(username='admin')
        def admin(*args):
            if self.role != 'admin': raise HTTPException(403)
            return SimpleNamespace(username='admin')
        for target,name,value in [(routes,'_writer_identity',identity),(routes,'_admin_identity',admin),
            (routes,'members',lambda *args:['cn123']), (rd,'local_rows',lambda *args:{'cn123':self.row}),
            (rd,'adapter',lambda *args:self.client),
            (routes,'settings',SimpleNamespace(data_dir=self.tmp.name,trail_rd_write_enabled=False,ra_auto_triage_root=self.tmp.name))]:
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
        app=FastAPI();app.include_router(routes.router);self.http=TestClient(app)
        self.body={'baselines':'fixture','issue_ids':['cn123']}
        self.headers={'X-RA-Triage-Request':'browser-v1'}

    def test_roles_and_disabled_gate(self):
        self.role='viewer'; self.assertEqual(self.http.get('/api/rd-results?baselines=fixture').status_code,403)
        self.role='writer'; self.assertEqual(self.http.get('/api/rd-results?baselines=fixture').status_code,200)
        self.assertEqual(self.http.post('/api/rd-results/preview',json=self.body,headers=self.headers).status_code,403)
        self.role='admin'
        p=self.http.post('/api/rd-results/preview',json=self.body,headers=self.headers)
        self.assertEqual(p.status_code,200,p.text)
        self.assertEqual(self.http.post('/api/rd-results/commit',json={'operation_id':p.json()['id'],'confirmed':True},headers=self.headers).status_code,403)
        self.assertEqual(self.client.calls,[])

    def test_marker_validation_and_scope(self):
        self.assertEqual(self.http.post('/api/rd-results/preview',json=self.body).status_code,403)
        for body in ({**self.body,'issue_ids':['cn999']},{**self.body,'issue_ids':['cn123','cn123']}):
            self.assertIn(self.http.post('/api/rd-results/preview',json=body,headers=self.headers).status_code,(400,409))
        self.assertEqual(self.http.post('/api/rd-results/preview',json={**self.body,'overwrite':'false'},headers=self.headers).status_code,422)

    def test_enabled_confirmed_commit_and_history(self):
        self.routes.settings.trail_rd_write_enabled=True
        p=self.http.post('/api/rd-results/preview',json=self.body,headers=self.headers).json()
        body={'operation_id':p['id'],'confirmed':False}
        self.assertEqual(self.http.post('/api/rd-results/commit',json=body,headers=self.headers).status_code,403)
        body['confirmed']=True
        response=self.http.post('/api/rd-results/commit',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state'],'complete')
        self.assertEqual(len(self.http.get('/api/rd-results/operations').json()['items']),1)

    def test_failed_preflight_receipt_is_retrievable_without_writing(self):
        self.routes.settings.trail_rd_write_enabled=True
        p=self.http.post('/api/rd-results/preview',json=self.body,headers=self.headers).json()
        self.client.row[rd.FIELD]='误触发'
        response=self.http.post('/api/rd-results/commit',json={'operation_id':p['id'],'confirmed':True},headers=self.headers)
        self.assertEqual(response.status_code,409)
        receipt=self.http.get('/api/rd-results/operations/'+p['id']).json()
        self.assertEqual(receipt['state'],'needs_recheck')
        self.assertEqual(receipt['results'][0]['state'],'not_attempted')
        self.assertEqual(self.client.calls,[])

    def test_scope_change_during_selection_does_not_silently_drop_items(self):
        with patch.object(rd,'local_rows',return_value={}):
            for action in ('status','preview'):
                response=self.http.post('/api/rd-results/'+action,json=self.body,headers=self.headers)
                self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.client.calls,[])


if __name__ == '__main__':
    unittest.main()
