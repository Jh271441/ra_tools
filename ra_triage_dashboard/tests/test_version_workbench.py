import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace
from ra_triage_dashboard.app.version_workbench import workbench, gallery_csv
from ra_triage_dashboard.app.daily_review_source import SnapshotChanged


class VersionWorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.folder=self.root/'reports/te_review_monitor/snapshots';self.folder.mkdir(parents=True)
        rows=[dict(issue_id='cn1',dataset='1009',date='2026-10-20',version='1.gen4-release-20261009.594',reason='low',te_status='filled',te_value='失败')]
        self.save(rows)
        # cn2 is a new target not yet included in the TE snapshot; cn3 is still collecting.
        self.rows=[dict(issue_id='cn1',is_target=True,is_sample=False,is_low=True,state='published',first_seen='2026-10-20',updated_at='2026-10-22',issue_time=1792479600000,binding={},prediction={'model_label':'正确触发','model_confidence':0.8}),
                   dict(issue_id='cn2',is_target=True,is_sample=True,is_low=True,state='published',first_seen='2026-10-23',updated_at='2026-10-23',issue_time=1792479600000,binding={},prediction={'model_label':'误触发','model_confidence':0.7}),
                   dict(issue_id='cn3',is_target=False,is_sample=False,is_low=False,state='ready',first_seen='2026-10-23',updated_at='2026-10-23',issue_time=1792479600000,binding={},prediction=None)]
        self.db=SimpleNamespace(list_version_datasets=lambda:[dict(id='release-20261009-odd2',revision=1)],version_dataset_gallery_rows=lambda _:json.loads(json.dumps(self.rows)))
    def save(self, rows, **extra):
        data=dict(schema_version=1,source_field='ra_review_result_new',dataset='1009',date='',snapshot_revision='a'*64,last_success_at=datetime.now(timezone.utc).isoformat(),rows=rows);data.update(extra)
        (self.folder/(data['dataset']+'.json')).write_text(json.dumps(data))
        if data['dataset']=='1009':(self.folder.parent/'version-membership-1009.json').write_text('{"schema_version":1}')
    def read(self, **kw):return workbench(self.db,self.root,'release-20261009-odd2',**kw)
    def test_one_scope_has_predictions_and_te_without_shrinking_denominator(self):
        a,_=self.read(page_size=1)
        self.assertEqual(a['items'][0]['issue_id'],'cn2')
        self.assertEqual(a['items'][0]['te_status'],'unknown')
        self.assertEqual(a['te']['summary'],dict(total=2,filled=1,unfilled=0,unknown=1,rate=.5))
        b,rows=self.read(te_status='filled')
        self.assertEqual(b['total'],1);self.assertEqual(b['te']['summary'],a['te']['summary'])
        self.assertEqual(rows[0]['prediction']['model_label'],'正确触发')
        self.assertEqual(b['te']['distribution'],[dict(value='失败',count=1)])
    def test_reason_override_pagination_dates_and_non_target(self):
        low,_=self.read(mode='low');self.assertEqual(low['total'],1)
        sample,_=self.read(mode='samples');self.assertEqual(sample['total'],1)
        all_rows,_=self.read(mode='all');self.assertEqual(all_rows['total'],3)
        pending,_=self.read(mode='all',te_status='unknown');self.assertEqual(pending['total'],1)
        q,_=self.read(q='cn3',mode='all');self.assertEqual(q['items'][0]['te_status'],'not_target');self.assertEqual(q['te']['summary']['total'],0)
        day=low['date_options'][0];filtered,_=self.read(date=day);self.assertEqual(filtered['total'],2)
        self.assertEqual(filtered['te']['daily'][0]['summary']['total'],2)
    def test_missing_te_snapshot_preserves_registry_targets_as_unknown(self):
        (self.folder/'1009.json').unlink()
        data,_=self.read();self.assertEqual(data['te']['summary']['total'],2);self.assertEqual(data['te']['summary']['unknown'],2)
        self.assertEqual(data['te']['source_field'],'ra_review_result_new')
    def test_export_scope_revision_and_formula_guard(self):
        first,rows=self.read(te_status='filled');data,csv_rows=self.read(te_status='filled',revision=first['snapshot_revision'])
        self.assertEqual(len(csv_rows),1);self.assertEqual(len(gallery_csv(csv_rows).splitlines()),2)
        self.rows[0]['prediction']['model_label']='=untrusted'
        self.assertIn("'=untrusted",gallery_csv(self.rows))
        self.db.list_version_datasets=lambda:[dict(id='release-20261009-odd2',revision=2)]
        with self.assertRaises(SnapshotChanged):self.read(te_status='filled',revision=first['snapshot_revision'])
    def test_0821_remains_frozen_and_separate(self):
        self.save([dict(issue_id='cn9',dataset='0821',date=None,version='1.gen4-release-20260821.1',reason='sample',te_status='unfilled',te_value=None)],dataset='0821')
        data,rows=workbench(self.db,self.root,'historical-0821')
        self.assertEqual(data['total'],1);self.assertTrue(data['dataset']['historical']);self.assertEqual(rows[0]['issue_id'],'cn9')
    def test_legacy_deep_link_preserves_scope_and_prefix(self):
        import asyncio
        from starlette.requests import Request
        from ra_triage_dashboard.app.routers import core
        request=Request(dict(type='http',query_string=b'dataset=0821&reason=sample&te_status=filled&media=camera&page=2&sort=issue',headers=[]))
        with patch.object(core,'settings',SimpleNamespace(base_path='/manual')):
            response=asyncio.run(core.legacy_daily_review(request))
        url=response.headers['location']
        self.assertIn('/manual/version-datasets?',url);self.assertIn('dataset=historical-0821',url);self.assertIn('mode=samples',url);self.assertIn('te_status=filled',url);self.assertIn('media=camera',url);self.assertIn('page=2',url)
