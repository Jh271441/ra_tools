import json
from pathlib import Path
import tempfile
import time
import unittest
import sqlite3
import hashlib

from ra_triage_dashboard.app.cron_closeup_source import closeup_status, CloseupCohort, task_root
from ra_triage_dashboard.app.closeup_video import RECIPE_ID
from ra_triage_dashboard.app.cron_closeup_fallback import CloseupFallback, LAYOUT_SHA


class CloseupStatusTest(unittest.TestCase):
    def test_same_cohort_intersection_identity_scope_and_legacy_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = task_root(root / 'ra_auto_triage')
            queue.mkdir(parents=True)
            media = root / 'media'
            published = media / 'bev_closeup'
            targets = {iid: dict(trip_id='trip', capture_timestamp_ms=1000, scope='scope')
                       for iid in ['cn1','cn2','cn3','cn4','cn5','cn6']}
            with sqlite3.connect(queue / 'queue.sqlite3') as db:
                db.execute('CREATE TABLE jobs(issue_id TEXT,row_json TEXT,state TEXT)')
                for iid, state in [('cn1','verified'),('cn2','verified'),('cn3','running'),('cn4','queued')]:
                    db.execute('INSERT INTO jobs VALUES(?,?,?)', (iid,json.dumps(dict(issue_id=iid,trip_id='trip',capture_timestamp_ms=1000)),state))
            def receipt(iid, **overrides):
                folder = published / 'issues' / iid
                folder.mkdir(parents=True)
                (folder / 'video.mp4').touch(); (folder / 'poster.jpg').touch()
                row = dict(issue_id=iid,status='verified',source_id='bev_closeup',recipe_id=RECIPE_ID,
                           scopes=['scope'],trip_id='trip',anchor_ms=1000,duration_ms=40000,frame_count=400,
                           frame_step_ms=100,event_time_sec=20,full_decode_passed=True,time_observations_verified=True,
                           video_path=f'issues/{iid}/video.mp4',poster_path=f'issues/{iid}/poster.jpg',
                           private_log='/private/token')
                (folder/'receipt.json').write_text(json.dumps(dict(row,**overrides)))
            receipt('cn1',producer='ares_animation_local'); receipt('cn2'); receipt('cn5',anchor_ms=999); receipt('cn6',scopes=['other'])
            before = (queue/'queue.sqlite3').read_bytes()
            result = CloseupCohort(root/'ra_auto_triage',media).project(targets,{'cn1','cn3','cn5','retired'})
            self.assertEqual((result['verified'],result['triple_verified']), (2,1))
            self.assertEqual((result['queued'],result['attention'],result['unknown']), (1,1,2))
            self.assertEqual(result['attention_ids'],['cn3'])
            self.assertEqual(result['fallback']['verified'],1)
            self.assertEqual(result['fallback']['status'],'not_observed')
            self.assertNotIn('private',json.dumps(result))
            self.assertEqual(before,(queue/'queue.sqlite3').read_bytes())
            targets['cn1']['trip_id']='wrong'
            self.assertEqual(CloseupCohort(root/'ra_auto_triage',media).project(targets,{'cn1'})['triple_verified'],0)

    def test_missing_roots_remain_unknown_without_creating_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=CloseupCohort(root/'ra_auto_triage',root/'media').project({'cn1':{}},set())
            self.assertIsNone(result['verified'])
            self.assertIsNone(result['triple_verified'])
            self.assertEqual(result['status'],'unavailable')
            self.assertFalse(task_root(root/'ra_auto_triage').exists())
            self.assertIsNone(result['fallback']['verified'])

    def test_fallback_uses_frozen_identity_and_actual_execution_not_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / 'local-fallback/run'
            run.mkdir(parents=True)
            targets = {iid: dict(trip_id='trip',capture_timestamp_ms=1000,scope='scope')
                       for iid in ['cn1','cn2','cn3','cn4']}
            sources = dict(rows=[dict(issue_id=iid,**expected,scopes=['scope'])
                                for iid, expected in targets.items()])
            raw = json.dumps(sources).encode()
            (run/'source-rows.json').write_bytes(raw)
            registration = dict(recipe=RECIPE_ID,layout_sha256=LAYOUT_SHA,
                                source_rows_sha256=hashlib.sha256(raw).hexdigest())
            (run/'fallback-registration.json').write_text(json.dumps(registration))
            state = dict(updated_at=time.time(),pid=99999,cases={
                'cn1':dict(state='published_verified'),
                'cn2':dict(state='source_gap_first_3_frames_unpublishable',started_at=1),
                'cn3':dict(state='registered')},remaining=[
                    dict(issue_id=iid,trip_id='trip',anchor_ms=1000,
                         disposition='source_planning_message_malformed') for iid in ['cn2','cn3','cn4']])
            (run/'state.json').write_text(json.dumps(state))
            targets['cn4']['capture_timestamp_ms']=999
            fallback = CloseupFallback(root).project(targets,{'cn1'},{'cn1'},True)
            self.assertEqual(fallback['status'],'ready')
            self.assertEqual((fallback['registered'],fallback['attempted_cases'],fallback['verified'],fallback['source_blocked']),(3,2,1,2))
            self.assertEqual(fallback['source_blocked_ids'],['cn2','cn3'])
            self.assertNotIn('pid',fallback)
            self.assertNotIn('running',json.dumps(fallback))
            self.assertNotIn(tmp,json.dumps(fallback))
            # A claimed publication without a valid in-scope media receipt is not verified.
            self.assertEqual(CloseupFallback(root).project(targets,set(),set(),True)['verified'],0)
            # Modified source identity or escaped files cannot leak plausible counts.
            (run/'source-rows.json').write_text('{}')
            self.assertEqual(CloseupFallback(root).status,'unavailable')
            (run/'source-rows.json').unlink()
            outside=root.parent/(root.name+'-outside.json')
            try:
                outside.write_bytes(raw)
                (run/'source-rows.json').symlink_to(outside)
                self.assertEqual(CloseupFallback(root).status,'unavailable')
            finally:
                outside.unlink(missing_ok=True)

    def test_status_projects_counts_without_private_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029/progress.json"
            self.assertIsNone(closeup_status(root / "ra_auto_triage"))
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(state="collecting", checked_at=time.time(), pid=123, cwd="/private/source", batch="/private/log", total=4461, verified=3, states={"verified":3, "queued":4458}, versions={"1009":{"queued":1480}}, source_members={"1009":{"published:ready":1480}})))
            result = closeup_status(root / "ra_auto_triage")
            self.assertEqual(result["verified"], 3)
            self.assertFalse(result["stale"])
            self.assertNotIn("private", json.dumps(result))
            path.write_text(json.dumps(dict(state='scheduled', checked_at=time.time(), next_action_at=1793444400)))
            scheduled = closeup_status(root/'ra_auto_triage')
            self.assertEqual((scheduled['state'], scheduled['next_action_at']), ('scheduled', 1793444400))
            path.write_text(json.dumps(dict(state="unrecognized", checked_at=0, total=-1, verified="3", versions={}, source_members={})))
            result = closeup_status(root / "ra_auto_triage")
            self.assertTrue(result["stale"])
            self.assertIsNone(result["total"])
            self.assertIsNone(result["verified"])
