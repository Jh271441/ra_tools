"""TE corrections use Manual labels, live RD agreement and one fixed target."""
import copy
import tempfile
import time
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from ra_triage_dashboard.tests import test_rd_results as fixtures
from ra_triage_dashboard.app import rd_results as rd
from ra_triage_dashboard.app.te_correction_source import TEObservationStore, merge_observations


class TEClient:
    def __init__(self, te='误触发', label='成功'):
        self.row = dict(issue_id='cn123', **{rd.TE_FIELD: te, rd.FIELD: label}, **{k: 'preserved' for k in rd.PROTECTED})
        self.calls = []
        self.lost = self.damage = self.fail_readback = False

    def fetch(self, ids):
        if self.fail_readback and self.calls:
            raise TimeoutError()
        return [copy.deepcopy(self.row)]

    def update(self, values):
        self.calls.append(values)
        self.row[rd.TE_FIELD] = values['cn123']
        if self.damage:
            self.row[rd.FIELD] = '无需协助'
        if self.lost:
            raise TimeoutError()
        return dict(code=0, msg='success')


class TEPublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = rd.PublicationStore(self.temp.name)
        self.client = TEClient()
        self.row = dict(issue_id='cn123', state='resolved', label='正确触发', fingerprint='v1')
        p = patch.object(rd, 'local_rows', return_value={'cn123': self.row}); p.start(); self.addCleanup(p.stop)

    def preview(self, aligned=True):
        return self.store.preview('admin', {'cn123': self.row}, rd.read_remote(self.client, ['cn123'], mode=rd.TE_MODE), aligned, 'version-20261016', mode=rd.TE_MODE)

    def commit(self, preview):
        return self.store.commit(preview['id'], 'admin', None, self.client, {'cn123'})

    def test_only_te_changes_and_receipt_freezes_mode_rd_and_agreement(self):
        before = copy.deepcopy(self.client.row)
        p = self.preview()
        self.assertEqual(p['mode'], rd.TE_MODE)
        self.assertEqual(p['field'], rd.TE_FIELD)
        self.assertEqual(p['items'][0]['rd_current'], '成功')
        self.assertTrue(p['offline_aligned'])
        self.assertEqual(self.client.calls, [])
        result = self.commit(p)
        self.assertEqual(result['results'][0]['state'], 'verified')
        self.assertEqual(result['results'][0]['observed'], '成功')
        self.assertEqual({k:v for k,v in self.client.row.items() if k != rd.TE_FIELD}, {k:v for k,v in before.items() if k != rd.TE_FIELD})
        self.commit(p)
        self.assertEqual(len(self.client.calls), 1)

    def test_ineligible_records_cannot_write(self):
        for te, label, status in [('成功','成功','same'),(None,'成功','te_empty'),('','成功','te_empty'),('误触发',None,'rd_mismatch'),('误触发','无需协助','rd_mismatch')]:
            with self.subTest(te=te, rd=label):
                self.client = TEClient(te, label)
                p = self.preview()
                self.assertEqual(p['items'][0]['status'], status)
                self.assertFalse(p['items'][0]['eligible'])
                self.commit(p)
                self.assertEqual(self.client.calls, [])

    def test_pending_conflict_and_stale_manual_labels_block(self):
        for state in ['pending','conflict','stale']:
            self.row['state'] = state
            p = self.preview()
            self.assertFalse(p['items'][0]['eligible'])
            self.assertEqual(p['items'][0]['status'], 'blocked')

    def test_no_offline_agreement_no_eligible_rows(self):
        p = self.preview(False)
        self.assertFalse(p['offline_aligned'])
        self.assertFalse(p['items'][0]['eligible'])

    def test_remote_rd_or_te_or_manual_source_change_blocks_before_write(self):
        for field in [rd.FIELD, rd.TE_FIELD, 'fingerprint']:
            self.client = TEClient(); self.row['fingerprint'] = 'v1'
            p = self.preview()
            if field == 'fingerprint': self.row[field] = 'v2'
            else: self.client.row[field] = '无需协助'
            with self.assertRaises(ValueError): self.commit(p)
            self.assertEqual(self.client.calls, [])
            self.assertEqual(self.store.receipt(p['id'])['state'], 'needs_recheck')

    def test_readback_requires_rd_unchanged_and_handles_lost_response(self):
        for failure, state in [('lost','verified'), ('damage','unverified'), ('fail_readback','unverified')]:
            self.client = TEClient(); setattr(self.client, failure, True)
            p = self.preview(); r = self.commit(p)
            self.assertEqual(r['results'][0]['state'], state)
            self.assertEqual(len(self.client.calls), 1)
            if state == 'unverified':
                with self.assertRaises(ValueError): self.commit(p)
                self.assertEqual(len(self.client.calls), 1)

    def test_transport_accepts_only_fixed_te_payload_and_legal_values(self):
        auth = SimpleNamespace(_post_headers=lambda url: {})
        transport = rd.RDTransport(auth, rd.TE_MODE)
        payload = dict(user_location='cn', source_id=1, issue_info={'cn123': {rd.TE_FIELD:'成功'}})
        with patch('requests.Session') as session:
            session.return_value.__enter__.return_value.post.return_value = MagicMock()
            transport.send_request('https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/', payload)
            for attrs in [{rd.FIELD:'成功'}, {rd.TE_FIELD:'正确触发'}, {rd.TE_FIELD:'成功',rd.FIELD:'成功'}]:
                bad = {**payload, 'issue_info': {'cn123':attrs}}
                with self.assertRaises(ValueError): transport.send_request('https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/', bad)
            self.assertEqual(session.return_value.__enter__.return_value.post.call_count, 1)

    def test_te_adapter_reuses_auth_but_builds_only_te_update(self):
        native = SimpleNamespace(client=SimpleNamespace(_post_headers=lambda url: {}))
        module = SimpleNamespace(TrailHTTP=lambda: native)
        with patch.object(rd.importlib, 'import_module', return_value=module), \
                patch.object(rd.sys, 'path', list(rd.sys.path)), \
                patch.object(rd.RDTransport, '_send_request', return_value={'code':0,'msg':'success'}) as send:
            bridge = rd.adapter(self.temp.name, mode=rd.TE_MODE)
            bridge.update({'cn123':'误触发'})
            self.assertEqual(send.call_args.args[1], dict(user_location='cn',source_id=1,
                issue_info={'cn123':{rd.TE_FIELD:'误触发'}}))
            self.assertEqual(bridge.client.field, rd.TE_FIELD)

    def test_legacy_rd_receipt_keeps_rd_target(self):
        p = self.store.preview('admin', {'cn123':self.row}, {'cn123':{rd.FIELD:None, **{k:None for k in rd.PROTECTED}}}, False, 'fixture')
        record = self.store.get(p['id']); record.pop('mode'); record.pop('field'); self.store.save(record)
        self.assertEqual(self.store.receipt(p['id'])['field'], rd.FIELD)

    def test_read_te_preserves_unknown_empty_and_other_enums_in_bounded_chunks(self):
        values = [{}, {rd.TE_FIELD:None}, {rd.TE_FIELD:''}, {rd.TE_FIELD:'成功'}, {rd.TE_FIELD:'未接起'}, {rd.TE_FIELD:0}]
        batches = []
        def fetch(ids):
            batches.append(list(ids))
            return [dict(issue_id=iid, **values[int(iid[2:]) % len(values)]) for iid in ids]
        result = rd.read_te_observations(SimpleNamespace(fetch=fetch), [f'cn{i}' for i in range(101)])
        self.assertEqual([len(batch) for batch in batches], [40,40,21])
        self.assertEqual([result[f'cn{i}']['te_status'] for i in range(6)], ['unknown','unfilled','unfilled','filled','filled','filled'])
        self.assertEqual(result['cn4']['te_value'], '未接起')
        for rows in [[], [dict(issue_id='cn123', **{rd.TE_FIELD:True})], [dict(issue_id='cn123', **{rd.TE_FIELD:{'invalid':True}})]]:
            with self.assertRaises(ValueError):
                rd.read_te_observations(SimpleNamespace(fetch=lambda ids: rows), ['cn123'])


class TEObservationStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = TEObservationStore(self.temp.name, 'synthetic')
        self.ids = [f'cn{i}' for i in range(101)]

    def read(self, refresh=False, reader=None, store=None):
        return (store or self.store).read('version-20261016', self.ids, refresh=refresh, read_remote=reader)

    def finish(self):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            saved, status = self.read()
            if status['status'] != 'running': return saved, status
            time.sleep(.01)
        self.fail('TE refresh did not finish')

    def test_no_automatic_remote_fetch_single_flight_and_reopen(self):
        entered, release = Event(), Event()
        calls = []
        def reader(ids):
            calls.append(ids); entered.set(); release.wait(3)
            return {iid:dict(te_status='unfilled',te_value=None) for iid in ids}
        self.assertEqual(self.read()[1]['status'], 'not_started')
        self.assertEqual(calls, [])
        first = self.read(True, reader)[1]
        try:
            self.assertEqual(first['status'], 'running'); self.assertTrue(entered.wait(1))
            for _ in range(3): self.assertEqual(self.read(True, reader)[1]['started_at'], first['started_at'])
            self.assertEqual(len(calls), 1)
        finally: release.set()
        saved, status = self.finish()
        self.assertEqual(status['status'], 'ready')
        self.assertEqual(len(saved['snapshot']['items']), 101)  # Keep empty TE observations too.
        reopened = self.read(store=TEObservationStore(self.temp.name, 'synthetic'))
        self.assertEqual(reopened[0], saved)
        self.assertEqual(len(calls), 2)
        self.assertFalse(status['membership_changed'])
        self.assertTrue(self.store.read('version-20261016', self.ids[:-1])[1]['membership_changed'])

    def test_partial_failure_keeps_previous_complete_snapshot_and_never_auto_retries(self):
        self.read(True, lambda ids:{iid:dict(te_status='filled',te_value='误触发') for iid in ids})
        original = self.finish()[0]['snapshot']
        calls=[]
        def fail(ids):
            calls.append(ids)
            if len(calls)>1: raise RuntimeError('private upstream error')
            return {iid:dict(te_status='filled',te_value='成功') for iid in ids}
        self.read(True, fail)
        saved, status = self.finish()
        self.assertEqual(status['status'], 'failed')
        self.assertEqual(saved['snapshot'], original)
        self.read(); self.assertEqual(len(calls), 2)
        self.assertNotIn('private', str(status))

    def test_newer_complete_observations_win_and_partial_values_are_never_projected(self):
        monitor = dict(source_status='ready',last_success_at='2026-11-06T01:00:00+00:00')
        observed = [dict(issue_id='cn1',te_status='filled',te_value='误触发')]
        saved = dict(status='failed',partial=[dict(issue_id='cn1',remote=dict(te_status='filled',te_value='成功'))])
        self.assertEqual(merge_observations(monitor,observed,saved,{})[1]['cn1']['te_value'], '误触发')
        saved['snapshot'] = dict(checked_at='2026-11-06T02:00:00+00:00',items=[dict(issue_id='cn1',remote=dict(te_status='filled',te_value='成功'))])
        self.assertEqual(merge_observations(monitor,observed,saved,{})[1]['cn1']['te_value'], '成功')
        monitor['last_success_at'] = '2026-11-06T03:00:00+00:00'
        self.assertEqual(merge_observations(monitor,observed,saved,{})[1]['cn1']['te_value'], '误触发')


class TERoutesTest(unittest.TestCase):
    def setUp(self):
        fixtures.RDRoutesTest.setUp(self)
        self.client = TEClient()
        self.routes.settings.trail_te_write_enabled = False
        self.body = dict(baselines='version-20261016', issue_ids=['cn123'], mode=rd.TE_MODE, overwrite=True)
        for target, name, value in [
            (rd,'adapter',lambda *args, **kwargs:self.client),
            (self.routes,'resolve_request_baseline_ids',lambda raw, **kwargs:raw.split(',')),
            (self.routes,'te_snapshot',lambda *args:(dict(source_status='ready',last_success_at='2026-11-06T01:00:00+00:00'), [dict(issue_id='cn123',te_status='filled',te_value='误触发')])),
        ]:
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)

    def preview(self):
        r=self.http.post('/api/rd-results/preview',json=self.body,headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def test_single_version_scope_and_mode_validation(self):
        for scope in ['fixture', '0508', 'version-20261016,version-20261009', 'version-20261016,0508', '']:
            r=self.http.post('/api/rd-results/preview',json={**self.body,'baselines':scope},headers=self.headers)
            self.assertIn(r.status_code,[400,422],r.text)
        for extra in [dict(mode='arbitrary'),dict(field=rd.FIELD),dict(label='误触发')]:
            r=self.http.post('/api/rd-results/preview',json={**self.body,**extra},headers=self.headers)
            self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(self.client.calls,[])

    def test_te_gate_independent_of_rd_and_receipt_controls_field(self):
        p=self.preview(); self.routes.settings.trail_rd_write_enabled=True
        body=dict(operation_id=p['id'],confirmed=True)
        r=self.http.post('/api/rd-results/commit',json=body,headers=self.headers)
        self.assertEqual(r.status_code,403,r.text)
        self.assertEqual(self.client.calls,[])
        self.routes.settings.trail_te_write_enabled=True
        r=self.http.post('/api/rd-results/commit',json=body,headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['field'],rd.TE_FIELD)
        self.assertEqual(self.client.row[rd.FIELD],'成功')

    def test_agreement_required_and_writer_cannot_preview_or_commit(self):
        self.body['overwrite']=False; p=self.preview(); self.routes.settings.trail_te_write_enabled=True
        r=self.http.post('/api/rd-results/commit',json=dict(operation_id=p['id'],confirmed=True),headers=self.headers)
        self.assertEqual(r.status_code,403,r.text)
        self.role='writer'
        self.assertEqual(self.http.post('/api/rd-results/preview',json=self.body,headers=self.headers).status_code,403)
        self.assertEqual(self.client.calls,[])

    def test_snapshot_summary_and_mode_history_isolation(self):
        r=self.http.get('/api/rd-results?baselines=version-20261016&mode=te-correction')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['counts'],dict(total=1,resolved=1,same=0,blocked=0))
        self.assertEqual(r.json()['items'][0]['te_current'],'误触发')
        self.assertFalse(r.json()['write_enabled'])
        self.assertEqual(self.client.calls,[])
        p=self.preview(); self.commit_preview(p)
        self.assertEqual(self.http.get('/api/rd-results/operations').json()['items'],[])
        history=self.http.get('/api/rd-results/operations?mode=te-correction').json()['items']
        self.assertEqual(history[0]['field'],rd.TE_FIELD)

    def commit_preview(self,p):
        self.routes.settings.trail_te_write_enabled=True
        r=self.http.post('/api/rd-results/commit',json=dict(operation_id=p['id'],confirmed=True),headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)

    def finish_refresh(self):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            result = self.http.get('/api/rd-results/te-refresh?baselines=version-20261016')
            self.assertEqual(result.status_code,200,result.text)
            if result.json()['status'] != 'running': return result.json()
            time.sleep(.01)
        self.fail('TE refresh did not finish')

    def test_refresh_reads_live_te_without_writes_and_summary_survives_reopen(self):
        self.role = 'writer'
        endpoint = '/api/rd-results/te-refresh'
        result = self.http.get(endpoint+'?baselines=version-20261016')
        self.assertEqual(result.json()['status'], 'not_started')
        self.client.row[rd.TE_FIELD] = '成功'
        response = self.http.post(endpoint,json={'baselines':'version-20261016'},headers=self.headers)
        self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(self.finish_refresh()['status'], 'ready')
        result = self.http.get('/api/rd-results?baselines=version-20261016&mode=te-correction').json()
        self.assertEqual(result['counts'],dict(total=1,resolved=0,same=1,blocked=0))
        self.assertEqual(result['items'][0]['te_current'], '成功')
        self.assertEqual(self.client.calls, [])
        with patch.object(self.client,'fetch',side_effect=RuntimeError('Must not query on GET')):
            self.assertEqual(self.http.get(endpoint+'?baselines=version-20261016').json()['status'],'ready')
            self.assertEqual(self.http.get('/api/rd-results?baselines=version-20261016&mode=te-correction').status_code,200)

    def test_refresh_scope_marker_and_role_fail_closed(self):
        endpoint='/api/rd-results/te-refresh'
        for scope in ['0508','version-20261016,version-20261009','']:
            result=self.http.post(endpoint,json={'baselines':scope},headers=self.headers)
            self.assertIn(result.status_code,[400,422])
        result=self.http.post(endpoint,json={'baselines':'version-20261016','issue_ids':['cn123']},headers=self.headers)
        self.assertEqual(result.status_code,422)
        result=self.http.post(endpoint,json={'baselines':'version-20261016'})
        self.assertEqual(result.status_code,403)
        self.role='viewer'
        self.assertEqual(self.http.post(endpoint,json={'baselines':'version-20261016'},headers=self.headers).status_code,403)
        self.assertEqual(self.http.get(endpoint+'?baselines=version-20261016').status_code,403)
        self.assertEqual(self.client.calls,[])

    def test_refresh_returns_before_slow_fetch_and_failure_retains_snapshot(self):
        entered, release = Event(), Event()
        fetch = self.client.fetch
        def slow(ids):
            entered.set(); release.wait(3); return fetch(ids)
        with patch.object(self.client,'fetch',side_effect=slow):
            try:
                result=self.http.post('/api/rd-results/te-refresh',json={'baselines':'version-20261016'},headers=self.headers)
                self.assertEqual(result.status_code,202,result.text)
                self.assertTrue(entered.wait(1)); self.assertFalse(release.is_set())
                self.assertEqual(self.http.get('/api/rd-results/te-refresh?baselines=version-20261016').json()['status'],'running')
            finally: release.set()
            self.assertEqual(self.finish_refresh()['status'],'ready')
        with patch.object(self.client,'fetch',side_effect=RuntimeError('private upstream detail')):
            self.http.post('/api/rd-results/te-refresh',json={'baselines':'version-20261016'},headers=self.headers)
            status=self.finish_refresh()
        self.assertEqual(status['status'],'failed')
        result=self.http.get('/api/rd-results?baselines=version-20261016&mode=te-correction').json()
        self.assertEqual(result['items'][0]['te_current'],'误触发')
        self.assertEqual(result['snapshot']['refresh']['status'],'failed')
        self.assertEqual(self.client.calls,[])


if __name__ == '__main__': unittest.main()
