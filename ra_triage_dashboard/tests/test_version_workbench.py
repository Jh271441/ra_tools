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

    def test_composition_is_mutually_exclusive_and_ignores_gallery_filters(self):
        for iid,state,sample,low in [('cn4','published',False,False),('cn5','excluded',True,True),('cn6','waiting_metadata',True,False)]:
            self.rows.append(dict(self.rows[2],issue_id=iid,state=state,is_sample=sample,is_low=low))
        value,_=self.read(mode='low',te_status='filled',q='cn1')
        c=value['composition'];self.assertEqual(c['total'],3)
        self.assertEqual({g['key']:g['count'] for g in c['groups']},{'low':1,'sample':1,'other':1})
        self.assertAlmostEqual(sum(g['ratio'] for g in c['groups']),1)
        self.assertEqual(c['pending'],2);self.assertEqual(c['excluded'],1)
        self.assertEqual(value['te']['summary']['total'],1)
        # The date filter scopes composition, while low/sample page filters never do.
        self.rows[-3]['issue_time']=1792566000000
        day=self.read()[0]['items'][0]['date']
        chosen,_=self.read(date=day)
        self.assertEqual(chosen['composition']['total'],2)
        self.assertEqual(chosen['composition']['groups'][2]['count'],0)

    def test_te_observation_delta_does_not_expose_raw_audit_ids(self):
        saved=json.loads((self.folder/'1009.json').read_text())
        saved['changes']=dict(te=[dict(issue_id='cn-secret')],added=['private'],removed=[])
        (self.folder/'1009.json').write_text(json.dumps(saved))
        value,_=self.read()
        self.assertEqual(value['te']['observed_changes'],dict(te=1,added=1,removed=0))
        self.assertNotIn('cn-secret',json.dumps(value));self.assertNotIn('private',json.dumps(value))

    def test_selected_old_occurrence_day_stays_in_bounded_chart(self):
        for day in range(1,17):
            at=datetime(2026,10,day,12,tzinfo=timezone.utc).timestamp()*1000
            self.rows.append(dict(self.rows[0],issue_id='cn'+str(100+day),issue_time=at))
        value,_=self.read(date='2026-10-01')
        self.assertEqual(len(value['te']['daily']),14)
        self.assertIn('2026-10-01',{d['date'] for d in value['te']['daily']})
        self.assertEqual(value['te']['daily'][0]['summary']['total'],1)


class VersionMetricScopeTests(unittest.TestCase):
    def test_global_scope_partitions_exclusions_and_preserves_sampling_denominator(self):
        from ra_triage_dashboard.app.version_workbench import count_scope
        rows=[dict(state='published',is_target=True,is_sample=True,is_low=True),
              dict(state='published',is_target=False,is_sample=False,is_low=False),
              dict(state='waiting_metadata',is_target=False,is_sample=True),
              dict(state='excluded',is_target=False,error='trigger_source_excluded',trigger='CZ_TL'),
              dict(state='excluded',is_target=False,error='trigger_source_excluded',trigger='StuckModel')]
        for i,row in enumerate(rows):row['issue_id']='cn'+str(i+1)
        scope=count_scope(rows)
        self.assertEqual(scope['total'],5);self.assertEqual(scope['completed'],2)
        self.assertEqual(scope['sampled'],1);self.assertEqual(scope['low_only'],0)
        self.assertEqual(scope['targets'],1)
        self.assertEqual({x['type']:x['count'] for x in scope['exclusions']},{'CZ_TL':1,'other_exclusion':1})
        self.assertIsNone(count_scope(rows,historical=True)['sampling_probability'])

    def test_metric_case_links_are_exact_modes_and_do_not_inherit_gallery_scope(self):
        fixture=VersionWorkbenchTest();fixture.setUp()
        try:
            fixture.rows.extend([
                dict(fixture.rows[2],issue_id='cn4',state='excluded',error='trigger_source_excluded',trigger='CZ_TL'),
                dict(fixture.rows[2],issue_id='cn5',state='waiting_metadata'),
                dict(fixture.rows[2],issue_id='cn6',state='needs_attention',is_sample=True)])
            counts={mode:fixture.read(mode=mode)[0]['total'] for mode in ['all','published','excluded','source_waiting','targets','sampled_targets']}
            self.assertEqual(counts,dict(all=6,published=2,excluded=1,source_waiting=1,targets=2,sampled_targets=1))
            scoped=fixture.read(mode='excluded',te_status='filled',q='cn4')[0]
            self.assertEqual(scoped['count_scope']['total'],6)
            self.assertEqual(scoped['count_scope']['sampled'],1)
            self.assertEqual(scoped['count_scope']['completed'],2)
        finally:fixture.doCleanups()


class TrailMetricLinkTests(unittest.TestCase):
    def test_native_trail_encoding_filters_exact_ids_and_empty_never_matches_all(self):
        from urllib.parse import parse_qs,urlsplit,unquote
        from ra_triage_dashboard.app.version_workbench import trail_case_filter
        url=trail_case_filter([{'issue_id':'cn2'},{'issue_id':'cn1'},{'issue_id':'cn2'}])
        self.assertEqual(urlsplit(url).hostname,'voyager.intra.xiaojukeji.com')
        fragment=urlsplit(url).fragment
        self.assertTrue(fragment.startswith('/issue/pool?'))
        # Native Trail splits keys after decodeURI, not form-query decoding.
        # An encoded '$' silently turns the array index into a dictionary key.
        raw_keys={pair.partition('=')[0] for pair in fragment.split('?',1)[1].split('&')}
        self.assertIn('query_attrs.$0',raw_keys)
        self.assertNotIn('query_attrs.%240',raw_keys)
        query=parse_qs(fragment.split('?',1)[1]);self.assertEqual(query['view_id~d'],['2410'])
        field,op,value,kind=query['query_attrs.$0'][0].split('|')
        self.assertEqual((field,op,kind),('issue_id','in','a_s'))
        self.assertEqual(unquote(value).split(','),['cn1','cn2'])
        self.assertIsNone(trail_case_filter([]))

    @staticmethod
    def conditions(url):
        from urllib.parse import parse_qs,urlsplit,unquote
        fragment=urlsplit(url).fragment
        raw_keys={item.partition('=')[0] for item in fragment.split('?',1)[1].split('&')}
        assert 'query_attrs.$0' in raw_keys and all('%24' not in k for k in raw_keys)
        decoded={}
        for key,value in parse_qs(fragment.split('?',1)[1]).items():
            if key.startswith('query_attrs.'):
                field,operator,val,kind=value[0].split('|')
                decoded[field]=(operator,unquote(val),kind)
        return decoded

    def test_reason_links_scope_eol_exception_to_1009_and_keep_version_business_filters(self):
        fixture=VersionWorkbenchTest();fixture.setUp()
        try:
            for family in ['20261009','20261016','20261023']:
                dataset='release-'+family+'-odd2'
                fixture.db.list_version_datasets=lambda dataset=dataset:[dict(id=dataset,revision=1)]
                value,_=workbench(fixture.db,fixture.root,dataset,mode='excluded',q='no-match',te_status='filled')
                self.assertEqual(value['total'],0)
                scope=value['count_scope']
                for mode,expected in [('published',('not_empty','','s')),
                                      ('targets',('in','目标集-低置信,目标集-抽样','a_s')),
                                      ('sampled_targets',('in','目标集-抽样','a_s'))]:
                    url=scope['trail_links'][mode];self.assertLess(len(url),800)
                    fields=self.conditions(url)
                    self.assertNotIn('issue_id',fields)
                    self.assertEqual(fields['version'],('like','1.gen4-release-'+family,'a_s'))
                    self.assertEqual(fields['trip_category'],('in','0','a_d'))
                    self.assertEqual(fields['ra_type'],('in','2,3','a_d'))
                    self.assertEqual(fields['trip_odd'],('in','ODD2','a_s'))
                    self.assertEqual(fields['ra_review_reason'],expected)
                    self.assertEqual(scope['trail_link_types'][mode],'reason_fields')
                    if family=='20261009':self.assertEqual(fields['ra_trigger'],('not_in','kEndOfLaneSequence','a_s'))
                    else:self.assertNotIn('ra_trigger',fields)
                self.assertIn('issue_id',self.conditions(scope['trail_links']['all']))
        finally:fixture.doCleanups()

    def test_frozen_and_source_waiting_links_stay_exact_and_empty_scopes_omit_links(self):
        from ra_triage_dashboard.app.version_workbench import count_scope
        rows=[dict(issue_id='cn1',state='published',is_target=True,is_sample=True),
              dict(issue_id='cn2',state='waiting_metadata')]
        live=count_scope(rows,family='20261009')
        self.assertEqual(self.conditions(live['trail_links']['source_waiting'])['issue_id'],('in','cn2','a_s'))
        self.assertIsNone(live['trail_links']['excluded'])
        frozen=count_scope(rows,family='20260821',historical=True)
        self.assertEqual(frozen['trail_link_types']['targets'],'case_ids')
        self.assertEqual(self.conditions(frozen['trail_links']['targets'])['issue_id'],('in','cn1','a_s'))
        self.assertEqual(frozen['trail_reason_exclusions'],[])
        self.assertTrue(all(link is None for link in count_scope([],family='20261009')['trail_links'].values()))
