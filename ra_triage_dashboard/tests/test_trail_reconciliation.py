from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from ra_triage_dashboard.app import trail_exclusion_sources as sources
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.trail_exclusion_contracts import trail_update_details
from types import SimpleNamespace

class ReconciliationTest(unittest.TestCase):
    def test_union_uses_baseline_issue_key_and_history_never_becomes_local_reason(self):
        local=[dict(issue_id=f'cn{i:08}',baseline_id='0508',comment='local') for i in range(45)]
        historical=[dict(issue_id=f'cn{i:08}',baseline_id='0508',source={'filename':'fixture'}) for i in range(15)]
        historical.append(dict(issue_id='cn32171803',baseline_id='0508',source={'filename':'fixture'}))
        evidence={'cn32171803':{'local_excluded':False,'legacy_reviews':[{'id':128,'note':'historical note','is_excluded':False}]}}
        union=sources.merge_reconciliation_items(local,historical,evidence)
        self.assertEqual(len(union),46)
        self.assertEqual(sum(row['source_kind']=='both' for row in union),15)
        only=next(row for row in union if row['readonly'])
        self.assertFalse(only['local_selected']);self.assertEqual(only['comment'],'')
        self.assertEqual(only['trail_update_status'],'querying')
        self.assertEqual(only['local_evidence'],evidence['cn32171803'])
        # Different baseline membership is not collapsed into one row.
        self.assertEqual(len(sources.merge_reconciliation_items(local,[{**historical[0],'baseline_id':'0821'}],{})),46)
        for marker in [True,False,None]:
            snapshot=SimpleNamespace(complete=True,rows=[{'issue_id':only['issue_id'],'info':{'ra_triage_dashboard':{'should_exclude':marker}}}])
            detail=trail_update_details(snapshot,[only['issue_id']],info_field='info')[only['issue_id']]
            self.assertIs(detail['trail_should_exclude'],marker)
            snapshot.complete=False
            self.assertEqual(trail_update_details(snapshot,[only['issue_id']],info_field='info')[only['issue_id']]['state'],'query_failed')

    def test_source_inventory_fingerprint_membership_and_unavailable(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sources,'_SOURCES',(('0508','subset.json','full.jsonl','2026-09-30T00:00:00Z'),)):
            sources._cache.clear()
            unavailable=sources.load_historical_trail_exclusions(root,['0508'])
            self.assertFalse(unavailable['available']);self.assertEqual(unavailable['items'],[])
            rows=[{'issue_id':'cn00000001','should_exclude':True},{'issue_id':'cn00000002','should_exclude':False}]
            Path(root,'subset.json').write_text(json.dumps(rows[:1]))
            Path(root,'full.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            sources._cache.clear();available=sources.load_historical_trail_exclusions(root,['0508'])
            self.assertTrue(available['available']);self.assertEqual(len(available['items']),1)
            self.assertEqual(len(available['sources'][0]['sha256']),64)
            Path(root,'subset.json').write_text(json.dumps([{'issue_id':'cn00000003','should_exclude':True}]))
            sources._cache.clear();self.assertFalse(sources.load_historical_trail_exclusions(root,['0508'])['available'])
            self.assertEqual(sources.load_historical_trail_exclusions(root,['0821'])['items'],[])

    def test_stored_evidence_is_read_only_and_audit_preserves_change(self):
        with tempfile.TemporaryDirectory() as root:
            db=Database(Path(root)/'test.sqlite');db.init()
            db.upsert_issues([{'issue_id':'cn00000001','gt_label':'误触发','title':'Evidence'}],source='test',replace_gt=True,baseline_scope='scope')
            before=db.trail_exclusion_evidence(['cn00000001'])
            self.assertIsNone(before['cn00000001']['local_excluded'])
            saved=db.create_label_revision(issue_id='cn00000001',expected_output='误触发',tags=[],evidence_gaps=[],rationale='',is_excluded=False,author='alice',author_source='test',author_verified=True,expected_previous_revision_id=None)
            evidence=db.trail_exclusion_evidence(['cn00000001'])
            self.assertIs(evidence['cn00000001']['local_excluded'],False)
            self.assertEqual(evidence['cn00000001']['legacy_reviews'],[])
            self.assertEqual(evidence['cn00000001']['migrated_revisions'],[])
            self.assertEqual(db.trail_exclusion_evidence(['cn00000001'],model_run_id='absent'),{})
            change={'intent':'reason_only','before':{'should_exclude':True,'should_exclude_comment':'old'},'after':{'should_exclude':True,'should_exclude_comment':'new'},'reason_source':{'revision_id':3},'local_fingerprint':'abc'}
            db.upsert_trail_issue_exclusion_history(operation_id='audit-test',actor='alice',actor_source='test',actor_verified=True,status='synced',requested_count=1,synced_count=1,failed_count=0,entries=[{'issue_id':'cn00000001','comment':'new','status':'synced','change':change}],message='test')
            history=db.list_trail_issue_exclusion_history()
            self.assertEqual(history['items'][0]['entries'][0]['change'],change)
