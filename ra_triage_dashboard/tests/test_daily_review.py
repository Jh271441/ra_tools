from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
from datetime import datetime,timezone,timedelta
from ra_triage_dashboard.app.daily_review_source import project,export_csv,SnapshotChanged,daily_overview

class DailyReviewTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.folder=self.root/'reports/te_review_monitor';(self.folder/'snapshots').mkdir(parents=True)
 def tearDown(self):self.tmp.cleanup()
 def save(self,rows,**kw):
  d=dict(schema_version=1,source_field='ra_review_result_new',dataset='1009',date='2026-10-19',snapshot_revision='a'*64,last_success_at=datetime.now(timezone.utc).isoformat(),rows=rows);d.update(kw)
  (self.folder/'snapshots/1009-2026-10-19.json').write_text(json.dumps(d));return d
 def row(self,i,status='filled',value='失败',**kw):
  r=dict(issue_id=f'cn{i}',dataset='1009',date='2026-10-19',version='1.gen4-release-20261009.594',reason='low',te_status=status,te_value=value);r.update(kw);return r
 def test_status_does_not_shrink_denominator_and_exports_same_scope(self):
  self.save([self.row(1),self.row(2,'unfilled',None),self.row(3,'unknown',None),self.row(4,value=0,reason='sample')])
  data,rows=project(self.root,te_status='filled');self.assertEqual(data['summary']['total'],4);self.assertEqual(data['summary']['filled'],2);self.assertEqual(data['summary']['unknown'],1);self.assertEqual(data['total'],2)
  self.assertEqual({r['issue_id'] for r in rows},{'cn1','cn4'});self.assertIn('cn4',export_csv(rows))
  low,_=project(self.root,reason='low');self.assertEqual(low['summary']['total'],3)
 def test_scope_guards(self):
  for v in ['1.gen4-release-20260924.1','1.gen4-release-202610090.1']:
   self.save([self.row(1,version=v)])
   with self.assertRaises(ValueError):project(self.root)
  with self.assertRaises(ValueError):project(self.root,dataset='0924')
  with self.assertRaises(ValueError):project(self.root,day='../../secrets')
  with self.assertRaises(ValueError):project(self.root,size=101)
 def test_missing_stale_and_failed_sources(self):
  d,_=project(self.root);self.assertIsNone(d['summary']);self.assertEqual(d['source_status'],'unavailable')
  self.save([self.row(1)],last_success_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat())
  d,_=project(self.root);self.assertEqual(d['source_status'],'stale');self.assertEqual(d['summary']['filled'],1)
  (self.folder/'status').mkdir();(self.folder/'status/1009-2026-10-19.json').write_text('{"status":"error","error":"/private/secret"}')
  d,_=project(self.root);self.assertEqual(d['source_status'],'error');self.assertNotIn('secret',json.dumps(d))
 def test_revision_and_private_fields(self):
  self.save([self.row(1,private_path='/secret')])
  d,_=project(self.root);self.assertNotIn('secret',json.dumps(d))
  with self.assertRaises(SnapshotChanged):project(self.root,revision='b'*64)
 def test_empty_and_duplicate(self):
  self.save([]);d,_=project(self.root);self.assertIsNone(d['summary']['rate'])
  self.save([self.row(1),self.row(1)])
  with self.assertRaises(ValueError):project(self.root)
 def test_symlink(self):
  p=self.folder/'snapshots/1009-2026-10-19.json';p.symlink_to('/etc/passwd')
  with self.assertRaises(ValueError):project(self.root)
 def test_actual_javascript_scope_ownership(self):
  app=Path(__file__).resolve().parents[1]
  subprocess.run(['node',str(app/'tests/daily_review_ui.cjs'),str(app/'static/js/daily-review.js')],check=True,capture_output=True,text=True)
 def test_daily_chart_keeps_daily_denominators_and_bounds_reads(self):
  for day in range(1,17):
   date=f'2026-10-{day:02d}'
   d=self.save([self.row(day,date=date),self.row(day+100,'unfilled',None,date=date)],date=date)
   (self.folder/f'snapshots/1009-{date}.json').write_text(json.dumps(d))
  (self.folder/'snapshots/1009-2026-10-19.json').unlink()
  current,_=project(self.root,day='2026-10-16',te_status='filled')
  chart=daily_overview(self.root,current)
  self.assertEqual(len(chart),14);self.assertEqual(chart[0]['date'],'2026-10-03')
  self.assertEqual(chart[-1]['date'],'2026-10-16')
  self.assertTrue(all(x['summary']['total']==2 and x['summary']['filled']==1 for x in chart))
  self.assertEqual(current['total'],1)
  self.assertTrue(all('items' not in x and 'rows' not in x for x in chart))
 def test_daily_chart_bad_day_is_unknown_and_frozen_set_has_no_daily_chart(self):
  self.save([self.row(1)])
  (self.folder/'snapshots/1009-2026-10-18.json').write_text('{bad json')
  current,_=project(self.root,day='2026-10-19')
  chart=daily_overview(self.root,current)
  self.assertIsNone(chart[0]['summary']);self.assertEqual(chart[0]['source_status'],'error')
  self.assertEqual(chart[1]['summary']['total'],1)
  frozen,_=project(self.root,dataset='0821');self.assertEqual(daily_overview(self.root,frozen),[])
 def test_csv_formula(self):
  self.assertIn("'=1+1",export_csv([self.row(1,value='=1+1')]))

if __name__=='__main__':unittest.main()
