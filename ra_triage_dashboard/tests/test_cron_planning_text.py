import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from ra_triage_dashboard.app.cron_planning_text import TextPipeline
from ra_triage_dashboard.app.planning_text_artifact import identity


class TextPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = self.root / 'planning_constraints'
        self.directory.mkdir()
        self.member = dict(issue_id='cn123', trip_id='road_trip', anchor_ms=1793500000000, version='20261030')
        self.key = ('cn123', 'road_trip', self.member['anchor_ms'])
        self.targets = {'cn123': dict(trip_id='road_trip', ra_start_timestamp=self.member['anchor_ms'], scope='manual_sidecar_version_20261030')}

    def counts(self, state='partial_source', frames=397):
        return dict(status='ready', selected=1, collected=int(state == 'collected'),
                    partial_source=int(state == 'partial_source'), failed=int(state == 'failed'), with_frames=int(frames > 0))

    def queue(self, state, detail=None, member=None):
        row = member or self.member
        path = self.directory / 'text-queue.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS work(capture_key TEXT PRIMARY KEY,member_json TEXT,state TEXT,detail_json TEXT,updated_at REAL)')
            db.execute('INSERT OR REPLACE INTO work VALUES(?,?,?,?,?)', (identity(row), json.dumps(row), state, json.dumps(detail or {}), 950))
        return path

    def runtime(self, status=2, **updates):
        row = dict(self.member, capture_key=identity(self.member), state='orion_running', native_status=status, native_at=995)
        value = dict(schema_version=1, execution_target='orion', at=995, max_concurrency=500,
                     jobs=[dict(job_id=123)], members=[row], observation_error=False)
        value.update(updates)
        path = self.directory / 'orion-runtime.json'
        path.write_text(json.dumps(value))
        return path

    def test_completed_gaps_survive_idle_restart_and_lost_heartbeat(self):
        path = self.queue('complete', dict(operator_recovery=True))
        before = path.read_bytes()
        runtime = self.runtime()
        for state in ('partial_source', 'failed'):
            saved = {self.key: (state, 397, dict(terminal_source_error=True))}
            first = TextPipeline(self.root, saved, now=1000).project(self.targets, self.counts(state))
            self.assertTrue(all(first['stages'][name]['state'] == 'complete' for name in ('text-input', 'text-export', 'text-verify', 'text-index', 'text-recover', 'text-source')))
            runtime.unlink(missing_ok=True)
            after = TextPipeline(self.root, saved, now=2000).project(self.targets, self.counts(state))
            self.assertEqual(first['stages'], after['stages'])
            self.assertEqual(after['runtime']['status'], 'unavailable')
            self.assertEqual(after['quality']['failed'], int(state == 'failed'))
        self.assertEqual(before, path.read_bytes())

    def test_native_running_and_completion_are_not_saved_text(self):
        self.queue('orion_running')
        self.runtime()
        counts = dict(status='ready', selected=1, with_frames=0, collected=0, partial_source=0, failed=0)
        result = TextPipeline(self.root, {}, now=1000).project(self.targets, counts)
        self.assertEqual(result['stages']['text-input']['state'], 'complete')
        self.assertEqual(result['stages']['text-export']['state'], 'running')
        self.assertEqual(result['stages']['text-export']['completed'], 0)
        for status in (1, 3, 4, True):
            self.runtime(status)
            projected = TextPipeline(self.root, {}, now=1000).project(self.targets, counts)
            self.assertEqual(projected['stages']['text-index']['completed'], 0)
            self.assertNotEqual(projected['stages']['text-export']['state'], 'complete')
            self.assertEqual(projected['runtime']['running'], 0)
        self.runtime()
        stale = TextPipeline(self.root, {}, now=2000).project(self.targets, counts)
        self.assertEqual(stale['runtime']['status'], 'stale')
        self.assertNotEqual(stale['stages']['text-export']['state'], 'running')

    def test_wrong_trip_anchor_or_version_cannot_color_another_cohort(self):
        self.queue('orion_running')
        self.runtime()
        for changes in (dict(trip_id='other_trip'), dict(ra_start_timestamp=self.member['anchor_ms'] + 1), dict(scope='manual_sidecar_version_20261023')):
            target = {'cn123': dict(self.targets['cn123'], **changes)}
            result = TextPipeline(self.root, {}, now=1000).project(target, self.counts('pending', 0))
            self.assertEqual(result['stages']['text-input']['completed'], 0)
            self.assertEqual(result['runtime']['running'], 0)

    def test_protected_review_is_not_started_or_reported_as_success(self):
        self.queue('review', dict(reason='previously_proven_media_source_block_no_automatic_reread'))
        self.runtime()  # A newer durable review supersedes this live snapshot.
        value = TextPipeline(self.root, {}, now=1000).project(self.targets, self.counts('pending', 0))
        self.assertEqual(value['stages']['text-export']['state'], 'blocked')
        self.assertEqual(value['stages']['text-index']['completed'], 0)
        self.assertEqual(value['stages']['text-source']['state'], 'blocked')
        self.assertEqual(value['runtime']['running'], 0)
        self.assertFalse(value['blocks_media'])

    def test_receipt_completion_does_not_invent_frames_or_execute_missing_work(self):
        value = TextPipeline(self.root, {self.key: ('partial_source', 0)}, now=1000).project(self.targets, self.counts(frames=0))
        self.assertEqual(value['stages']['text-index']['state'], 'complete')
        self.assertEqual(value['quality']['with_frames'], 0)
        self.assertEqual(value['durable_queue'], 'unavailable')
        self.assertEqual(list(self.directory.iterdir()), [])
        value = TextPipeline(self.root, {}, now=1000).project({}, dict(status='ready', selected=0, collected=0, partial_source=0, failed=0, with_frames=0))
        self.assertEqual(value['stages']['text-input']['state'], 'pending')
        self.assertEqual(value['stages']['text-recover']['state'], 'not_required')

    def test_bad_runtime_and_symlink_queue_preserve_only_index_proof(self):
        self.runtime(at=1500)
        elsewhere = self.root / 'other.sqlite3'
        elsewhere.write_text('untrusted')
        (self.directory/'text-queue.sqlite3').symlink_to(elsewhere)
        value = TextPipeline(self.root, {self.key: ('collected', 400)}, now=1000).project(self.targets, self.counts('collected', 400))
        self.assertEqual(value['runtime']['status'], 'unavailable')
        self.assertEqual(value['stages']['text-index']['state'], 'complete')
        self.assertEqual(elsewhere.read_text(), 'untrusted')

    def test_resource_failure_receipt_is_not_a_completed_source(self):
        from ra_triage_dashboard.app.planning_text_daily import _cohort_evidence
        for errors in ([], [dict(code='worker_error', error_type='resource_wait')], None):
            saved = {self.key: ('failed', 0, _cohort_evidence(dict(errors=errors)))}
            result = TextPipeline(self.root, saved, now=1000).project(self.targets, self.counts('failed', 0))
            self.assertEqual(result['stages']['text-export']['state'], 'blocked')
            self.assertEqual(result['stages']['text-index']['completed'], 0)
            self.assertEqual(result['stages']['text-source']['completed'], 0)

    def test_actual_graph_keeps_completed_stages_green_and_running_yellow(self):
        static = Path(__file__).resolve().parents[1]/'static/js'
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ctx=vm.createContext({window:{},document:{addEventListener(){}},state:{colorTheme:'dark'},uiText:(zh,en)=>zh,$:()=>null,Date,assert});
for(const f of process.argv.slice(1))vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
vm.runInContext(`
const v={stale:true,states:{published:67},media:{selected:67,verified:67},datasets:[],
planning_text:{status:'ready',selected:67,with_frames:67,collected:15,partial_source:52,failed:0,pending:0,unknown:0}};
const task=id=>buildIncrementalCronGraph(v).lanes.flatMap(l=>l.nodes).find(n=>n.id===id).data;
for(const id of ['text-input','text-export','text-verify','text-index','text-source'])assert.equal(task(id).status,'success');
assert.equal(task('text-index').progress.done,67);
dailyCronState.error=true;
assert.equal(task('text-index').status,'success');
assert.equal(task('text-index').progress.stale,true);
dailyCronState.error=false;
v.planning_text={status:'ready',selected:2,with_frames:1,collected:1,partial_source:0,failed:0,pending:1,unknown:0,
pipeline:{status:'ready',runtime:{status:'ready',running:1,queued:0},stages:{
'text-input':{state:'complete',total:2,completed:2,running:0,blocked:0},
'text-export':{state:'running',total:2,completed:1,running:1,blocked:0}}}};
assert.equal(task('text-export').status,'running');
v.planning_text.pipeline.runtime.status='stale';
assert.equal(task('text-export').status,'unknown');
assert.equal(task('text-input').status,'success');
const edges=buildIncrementalCronGraph(v).edges;
assert.ok(edges.some(e=>e.source==='media-source'&&e.target==='text-input'));
assert.ok(!edges.some(e=>e.source.startsWith('text-')&&e.target.startsWith('media-')));
assert.ok(!edges.some(e=>['media-orion','media-closeup'].includes(e.source)&&e.target==='text-input'));
`,ctx);
'''
        result = subprocess.run(['node', '-e', script, str(static/'daily-cron.js'), str(static/'daily-cron-text.js'), str(static/'daily-cron-graph.js')], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
