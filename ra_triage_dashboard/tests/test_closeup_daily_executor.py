"""Budget, admission and publication gates for the owned offline sidecar."""
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ra_triage_dashboard.scripts.bev_closeup import offline_daily as daily


class CloseupDailyExecutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.row = dict(issue_id='cn1', trip_id='trip', capture_timestamp_ms=1000,
                        version='1009', scopes=['version-20261009'])
        self.db = sqlite3.connect(self.root/'queue.sqlite3')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE jobs(issue_id TEXT, row_json TEXT, state TEXT, error TEXT, finished_at REAL, batch TEXT)')
        self.db.execute('INSERT INTO jobs(issue_id,row_json,state) VALUES(?,?,?)',
                        ('cn1', json.dumps(self.row), 'running'))
        self.db.commit()

    def job(self, attempt=1, job_id=1, state='terminal', counts=None):
        run = self.root/'orion'/str(job_id)
        daily.save(run/'source-rows.json', [self.row])
        daily.save(run/'status.json', dict(job_id=job_id, total=1, counts=counts or dict(failed=1)))
        daily.save(run/'native-failed-tasks.json', [dict(job_id=job_id, signature='cn1-1000-0', status=4)])
        return dict(run=str(run), source_rows=str(run/'source-rows.json'),
                    source_sha256=daily.sha(run/'source-rows.json'), count=1,
                    job_id=job_id, state=state, attempt_number=attempt)

    def test_single_orion_retry_then_local_without_replaying_old_attempt3(self):
        first = self.job()
        result = daily.recovery_plan(self.root, [first], set())
        self.assertEqual((len(result['retry']), len(result['local'])), (1, 0))
        second = self.job(2, 2)
        result = daily.recovery_plan(self.root, [first, second], set())
        self.assertEqual((len(result['retry']), len(result['local'])), (0, 1))
        third = self.job(3, 3)
        result = daily.recovery_plan(self.root, [first, second, third], set())
        self.assertFalse(result['local'] or result['retry'])

    def test_published_and_proven_source_failures_are_never_readmitted(self):
        job = self.job()
        self.assertFalse(daily.recovery_plan(self.root, [job], {daily.identity(self.row)})['retry'])
        daily.save(self.root/'local-fallback/old/state.json', dict(remaining=[dict(
            issue_id='cn1', trip_id='trip', anchor_ms=1000, disposition='source_planning_message_malformed')]))
        self.assertFalse(daily.recovery_plan(self.root, [job], set())['retry'])

    def test_unknown_submission_and_wrong_native_identity_fail_closed(self):
        job = self.job()
        with self.assertRaisesRegex(ValueError, 'unresolved_submission'):
            daily.recovery_plan(self.root, [dict(job, job_id=None)], set())
        daily.save(Path(job['run'])/'native-failed-tasks.json', [dict(job_id=1, signature='cn1-999-0', status=4)])
        with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
            daily.failed_rows(job, self.root)
        daily.save(Path(job['run'])/'native-failed-tasks.json', [dict(job_id=1, signature='cn1-1000-0', status=3)])
        with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
            daily.failed_rows(job, self.root)

    def test_native_running_does_not_advance_to_recovery(self):
        job = self.job(state='submitted', counts=dict(running=1))
        result = daily.recovery_plan(self.root, [job], set())
        self.assertFalse(result['retry'] or result['local'])
        job['state'] = 'terminal'
        with self.assertRaisesRegex(ValueError, 'terminal_status'):
            daily.failed_rows(job, self.root)

    def test_delayed_download_and_unprocessed_batch_keep_controller_active(self):
        failures = dict(cn1=dict(retryable=True, attempts=1, next_retry_at=200))
        pending, due = daily.completed_pending({'cn1':self.row}, ['cn1'], set(), failures, now=100)
        self.assertEqual((pending, due), (['cn1'], []))
        self.assertEqual(daily.completed_pending({'cn1':self.row}, ['cn1'], set(), {}, now=100), (['cn1'], ['cn1']))
        failures['cn1']['attempts'] = 3
        self.assertEqual(daily.completed_pending({'cn1':self.row}, ['cn1'], set(), failures), ([], []))
        self.assertEqual(daily.completed_pending({'cn1':self.row}, ['cn1'], {'cn1'}, {}), ([], []))

    def test_not_before_gate_does_not_submit_or_start_early(self):
        self.assertFalse(daily.enabled(dict(not_before=200), now=199))
        self.assertTrue(daily.enabled(dict(not_before=200), now=200))
        with patch.object(daily.time, 'time', return_value=199), patch.object(daily.subprocess, 'run') as run:
            daily.retry_tick(self.root, [], self.db, dict(not_before=200), 'python')
            run.assert_not_called()

    def test_uncertain_network_submission_persists_intent_and_cannot_replay(self):
        job = self.job()
        jobs = [job]
        with patch.object(daily.subprocess, 'run', side_effect=subprocess.TimeoutExpired('submit', 1)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                daily.retry_tick(self.root, jobs, self.db, dict(not_before=0, layout='frozen-layout'), 'python')
            self.assertEqual(run.call_count, 1)
            intent = daily.read(self.root/'orion/jobs.json', [])[-1]
            self.assertEqual(intent['state'], 'preparing')
            self.assertNotIn('job_id', intent)
            with self.assertRaisesRegex(ValueError, 'unresolved_submission'):
                daily.retry_tick(self.root, jobs, self.db, dict(not_before=0, layout='frozen-layout'), 'python')
            self.assertEqual(run.call_count, 1)

    def test_original_global_slots_block_closeup_and_no_claim_is_consumed(self):
        first, second = self.job(), self.job(2, 2)
        daily.save(self.root/'orion/jobs.json', [first, second])
        bags = self.root/'bags'
        for number in (1, 2):
            daily.save(bags/f'daily/day/recovery/local/cn{number}/1/claim.json', {})
        code = Path(__file__).resolve().parents[1]
        profile = dict(not_before=0, code=str(code))
        c = SimpleNamespace(BAGS=bags, PY='python')
        recovery = SimpleNamespace(alive=lambda s: True, session_for=lambda a: str(a))
        with patch.object(daily, 'control', return_value=profile), patch.object(daily.subprocess, 'run') as run:
            daily.local_tick(c, recovery, self.root)
            run.assert_not_called()
        self.assertFalse(list(bags.glob('versions/*/*/recovery/local/*/*/claim.json')))

    def test_local_render_is_published_only_after_strict_verification(self):
        bags = self.root/'bags/manual_sidecar_20261019'
        attempt = bags/'versions/20261009/bev-closeup-2/recovery/local/cn1/1'
        daily.save(attempt/'claim.json', dict(row=self.row, closeup_task_root=str(self.root)))
        daily.save(attempt/'result.json', dict(state='rendered'))
        output = attempt/'runs/cn1/outputs/cn1_1000'
        output.mkdir(parents=True)
        (output/'animation.mp4').write_bytes(b'video')
        (output/'report.json').write_text('{}')
        calls = []
        def verify(*args):
            calls.append('verify')
            raise ValueError('actual_time_mismatch')
        pipeline = SimpleNamespace(verify_download=verify, publish=lambda *args: calls.append('publish'))
        with patch.object(daily, 'REPO', self.root):
            daily.publish_local_ready(self.root, self.db, pipeline, dict(not_before=0))
        self.assertEqual(calls, ['verify'])
        self.assertEqual(daily.read(attempt/'result.json')['state'], 'failed')
        self.assertEqual(self.db.execute('SELECT state FROM jobs').fetchone()[0], 'running')


if __name__ == '__main__':
    unittest.main()
