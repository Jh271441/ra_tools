import copy
import io
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import openpyxl

from ra_triage_dashboard.app import rd_results as rd
from ra_triage_dashboard.app.label_publication_inputs import filter_issue_rows, parse_te_xlsx
from ra_triage_dashboard.tests import test_te_corrections as te_fixtures


def workbook_bytes(rows):
    book = openpyxl.Workbook(); sheet = book.active
    for row in rows: sheet.append(row)
    buffer = io.BytesIO(); book.save(buffer); book.close(); return buffer.getvalue()


class PublicationInputTest(unittest.TestCase):
    def test_multi_issue_lists_are_exact_deduplicated_and_single_search_compatible(self):
        rows = [dict(issue_id=iid) for iid in ['cn1','cn10','cn2','cn20']]
        for q in ['cn1\ncn2\ncn1', 'cn1, cn2', 'CN1；CN2', 'https://x.test/issue/cn1 cn2']:
            self.assertEqual([r['issue_id'] for r in filter_issue_rows(rows,q)], ['cn1','cn2'])
        self.assertEqual(len(filter_issue_rows(rows, 'cn1')),2)
        for q in ['cn1,invalid', ','.join(f'cn{i}' for i in range(501)), 'x'*8001]:
            with self.assertRaises(ValueError): filter_issue_rows(rows,q)

    def test_file_expected_outputs_are_explicit_and_equal_duplicates_are_reported(self):
        raw=workbook_bytes([['Issue ID','期望输出','备注'],['CN123','成功','original'],['cn124','误触发',''],['cn124','误触发','duplicate'],['cn125','无需协助','']])
        rows, source = parse_te_xlsx('../targets.xlsx',raw)
        self.assertEqual([r['label'] for r in rows.values()],['正确触发','误触发','无需协助'])
        self.assertEqual(source['filename'],'targets.xlsx'); self.assertEqual(source['duplicates'],1)
        self.assertEqual(rows['cn124']['source_row'],3); self.assertEqual(len(source['sha256']),64)

    def test_invalid_targets_formulas_conflicting_duplicates_and_ambiguous_headers_fail(self):
        for data in [
            [['issue_id','expected_output'],['cn123','未知']],
            [['issue_id','expected_output'],['invalid','误触发']],
            [['issue_id','expected_output'],['cn123','=1+1']],
            [['issue_id','expected_output'],['="cn123"','误触发']],
            [['issue_id','expected_output'],['cn123','误触发'],['cn123','无需协助']],
            [['issue_id','Issue ID','期望输出'],['cn123','cn123','误触发']],
            [['issue_id'],['cn123']], [['issue_id','expected_output']],
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError): parse_te_xlsx('targets.xlsx',workbook_bytes(data))
        for name,raw in [('x.csv',b'abc'),('x.xlsm',workbook_bytes([['issue_id','expected_output']])),('x.xlsx',b'not a workbook')]:
            with self.assertRaises(ValueError): parse_te_xlsx(name,raw)

    def test_excel_limits_are_enforced(self):
        with self.assertRaisesRegex(ValueError,'256'):
            parse_te_xlsx('targets.xlsx',workbook_bytes([['issue_id','expected_output']+['x']*255,['cn123','误触发']]))
        with self.assertRaisesRegex(ValueError,'20000'):
            parse_te_xlsx('targets.xlsx',workbook_bytes([['issue_id','expected_output']]+[[f'cn{i}','误触发'] for i in range(20001)]))


class ExcelRoutesTest(unittest.TestCase):
    def setUp(self): te_fixtures.TERoutesTest.setUp(self)

    def upload(self, rows, **kwargs):
        return self.http.post('/api/rd-results/te-excel-preview',
            data=kwargs.get('data',{'baselines':'version-20261016'}),
            files={'file':(kwargs.get('filename','targets.xlsx'),workbook_bytes(rows),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
            headers=kwargs.get('headers',self.headers))

    def test_file_value_overrides_manual_and_writes_only_te(self):
        self.row['label']='无需协助'  # File is the authorized source for this operation.
        self.client.row[rd.FIELD]='误触发'; self.client.row[rd.TE_FIELD]='成功'
        response=self.upload([['issue_id','expected_output'],['cn123','误触发']])
        self.assertEqual(response.status_code,200,response.text)
        preview=response.json(); self.assertEqual(preview['items'][0]['desired'],'误触发')
        self.assertEqual(preview['scope']['source']['kind'],'xlsx'); self.assertTrue(preview['items'][0]['eligible'])
        self.assertEqual(self.client.calls,[])
        self.routes.settings.trail_te_write_enabled=True
        with patch.object(rd,'local_rows',side_effect=AssertionError('File target must not fall back to Manual')):
            result=self.http.post('/api/rd-results/commit',json=dict(operation_id=preview['id'],confirmed=True),headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['results'][0]['state'],'verified')
        self.assertEqual(self.client.row[rd.TE_FIELD],'误触发'); self.assertEqual(self.row['label'],'无需协助')

    def test_bad_or_outside_rows_never_read_or_write_trail(self):
        for rows in [[['Issue ID','期望输出'],['cn999','误触发']], [['Issue ID','期望输出'],['cn123','无效']], [['Issue ID','期望输出'],['cn123','误触发'],['cn123','无需协助']]]:
            with patch.object(self.client,'fetch') as fetch:
                result=self.upload(rows)
                self.assertIn(result.status_code,[400,409],result.text); fetch.assert_not_called()
        self.assertEqual(self.client.calls,[])

    def test_file_target_can_differ_from_live_rd_and_rechecks_before_commit(self):
        self.client.row[rd.TE_FIELD]='成功'
        response=self.upload([['Issue ID','期望输出'],['cn123','误触发']])
        self.assertTrue(response.json()['items'][0]['eligible'])
        self.routes.settings.trail_te_write_enabled=True
        result=self.http.post('/api/rd-results/commit',json=dict(operation_id=response.json()['id'],confirmed=True),headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.row[rd.FIELD],'成功')
        self.assertEqual(self.client.row[rd.TE_FIELD],'误触发')
        self.client.row[rd.TE_FIELD]='成功'
        response=self.upload([['Issue ID','期望输出'],['cn123','误触发']]); preview=response.json()
        self.client.row[rd.FIELD]='无需协助'
        result=self.http.post('/api/rd-results/commit',json=dict(operation_id=preview['id'],confirmed=True),headers=self.headers)
        self.assertEqual(result.status_code,409,result.text); self.assertEqual(len(self.client.calls),1)

    def test_mutated_file_target_fingerprint_is_rejected_and_old_receipts_stay_separate(self):
        self.client.row[rd.FIELD]='误触发'
        response=self.upload([['Issue ID','期望输出'],['cn123','误触发']]); preview=response.json()
        store=self.routes.store(); record=store.get(preview['id']); record['items'][0]['label']='无需协助'; store.save(record)
        self.routes.settings.trail_te_write_enabled=True
        result=self.http.post('/api/rd-results/commit',json=dict(operation_id=preview['id'],confirmed=True),headers=self.headers)
        self.assertEqual(result.status_code,409,result.text); self.assertEqual(self.client.calls,[])

    def test_xlsx_permission_marker_confirmation_and_source_contract(self):
        rows=[['Issue ID','期望输出'],['cn123','正确触发']]
        self.role='writer'; self.assertEqual(self.upload(rows).status_code,403)
        self.role='admin'; self.assertEqual(self.upload(rows,headers={}).status_code,403)
        self.assertEqual(self.upload(rows,data={'baselines':'fixture','overwrite':'true'}).status_code,400)
        response=self.upload(rows,data={'baselines':'version-20261016','overwrite':'false'})
        self.assertEqual(response.status_code,200,response.text);self.assertNotIn('offline_aligned',response.json())
        self.assertTrue(response.json()['items'][0]['eligible'])
        self.assertEqual(self.client.calls,[])

    def test_multi_issue_scope_preview_uses_the_same_exact_subset(self):
        rows={iid:dict(issue_id=iid,state='resolved',label='正确触发',fingerprint='v1',authors=[]) for iid in ['cn123','cn1234','cn124']}
        remote={iid:dict(self.client.row,issue_id=iid) for iid in rows}
        observation=[dict(issue_id=iid,te_status='filled',te_value='误触发') for iid in rows]
        with patch.object(self.routes,'members',return_value=list(rows)), patch.object(rd,'local_rows',side_effect=lambda db,ids:{iid:rows[iid] for iid in ids}), \
                patch.object(self.routes,'te_snapshot',return_value=({'source_status':'ready'},observation)), \
                patch.object(self.client,'fetch',side_effect=lambda ids:[copy.deepcopy(remote[iid]) for iid in ids]):
            query=urlencode(dict(baselines='version-20261016',mode='te-correction',q='cn123\ncn124\ncn123'))
            response=self.http.get('/api/rd-results?'+query)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual([r['issue_id'] for r in response.json()['items']],['cn123','cn124'])
            response=self.http.post('/api/rd-results/preview-scope',json=dict(baselines='version-20261016',mode='te-correction',q='cn123,cn124',overwrite=True),headers=self.headers)
            self.assertEqual([r['issue_id'] for r in response.json()['items']],['cn123','cn124'])
            self.assertEqual(self.client.calls,[])
