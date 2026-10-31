import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from ra_triage_dashboard.app.closeup_video import RECIPE_ID
from ra_triage_dashboard.app.cron_closeup_fallback import LAYOUT_SHA
from ra_triage_dashboard.app.cron_closeup_retries import CloseupRetries


class CloseupRetriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write('orion/registration.json', dict(
            recipe_id=RECIPE_ID, rendered_layout_sha256=LAYOUT_SHA))
        self.targets = {iid: dict(trip_id='trip', capture_timestamp_ms=1000, scope='scope')
                        for iid in ['cn1', 'cn2', 'cn3']}

    def write(self, file, data):
        path = self.root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def job(self, ids, attempt=2, counts=None, name='retry', job_id=42):
        rows = [dict(issue_id=iid, trip_id='trip', capture_timestamp_ms=1000,
                     scopes=['scope']) for iid in ids]
        source = self.write(name+'/source-rows.json', rows)
        self.write(name+'/status.json', dict(job_id=job_id, total=len(rows),
                   counts=counts or dict(completed=len(rows)), observed_at=time.time(),
                   private_sdk_log='secret-log-value'))
        return dict(run=str(source.parent), job_id=job_id, attempt_number=attempt,
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())

    def test_exact_cohort_only_and_legacy_attempt_does_not_reset_budget(self):
        self.write('orion/jobs.json', [self.job(['cn1', 'cn2']),
                    self.job(['cn3'], attempt=3, name='legacy', job_id=43)])
        self.targets['cn2']['scope'] = 'other'
        result = CloseupRetries(self.root).project(self.targets)
        self.assertEqual((result['status'], result['total'], result['completed']),
                         ('completed', 1, 1))
        self.assertEqual(result['legacy_extra_attempt_cases'], 1)
        self.assertNotIn('secret-log-value', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.targets['cn1']['trip_id'] = 'wrong'
        self.assertEqual(CloseupRetries(self.root).project(self.targets)['total'], 0)
        self.targets['cn1'].update(trip_id='trip', capture_timestamp_ms=999)
        self.assertEqual(CloseupRetries(self.root).project(self.targets)['total'], 0)

    def test_partial_failure_requires_exact_native_task_identity(self):
        self.write('orion/jobs.json', [self.job(['cn1', 'cn2'],
                   counts=dict(completed=1, failed=1))])
        task = dict(job_id=42, signature='cn2-1000-0', status=4, id=4200,
                    outcome='private-sdk-outcome')
        self.write('retry/native-failed-tasks.json', [task])
        result = CloseupRetries(self.root).project(self.targets)
        self.assertEqual((result['status'], result['processed'], result['completed'],
                          result['failed']), ('partial_failed', 2, 1, 1))
        self.assertNotIn('private-sdk-outcome', json.dumps(result))
        for change in [dict(job_id=43), dict(signature='cn2-999-0'),
                       dict(signature='cn3-1000-0'), dict(status=3)]:
            with self.subTest(change=change):
                self.write('retry/native-failed-tasks.json', [dict(task, **change)])
                self.assertEqual(CloseupRetries(self.root).status, 'unavailable')

    def test_unfinished_or_missing_evidence_never_claims_running_or_success(self):
        self.assertEqual(CloseupRetries(self.root).project(self.targets)['status'],
                         'not_observed')
        self.write('orion/jobs.json', [self.job(['cn1'], counts=dict(running=1))])
        result = CloseupRetries(self.root).project(self.targets)
        self.assertEqual((result['status'], result['processed']), ('unknown', 0))
        self.assertNotIn('running', json.dumps(result))
        (self.root/'retry/status.json').unlink()
        self.assertEqual(CloseupRetries(self.root).status, 'unavailable')

    def test_corrupt_status_or_source_is_unavailable(self):
        for invalid in [dict(completed=2), dict(completed=-1, running=2),
                        dict(completed=True)]:
            with self.subTest(invalid=invalid):
                self.write('orion/jobs.json', [self.job(['cn1'], counts=invalid)])
                self.assertEqual(CloseupRetries(self.root).status, 'unavailable')
        self.write('orion/jobs.json', [self.job(['cn1'])])
        self.write('retry/source-rows.json', [])
        self.assertEqual(CloseupRetries(self.root).status, 'unavailable')

    def test_escaped_paths_and_duplicate_automatic_attempts_are_unavailable(self):
        job = self.job(['cn1'])
        self.write('orion/jobs.json', [job, job])
        self.assertEqual(CloseupRetries(self.root).project(self.targets)['status'],
                         'unavailable')
        self.write('orion/jobs.json', [dict(job, run=str(self.root.parent))])
        self.assertEqual(CloseupRetries(self.root).status, 'unavailable')
        self.write('orion/jobs.json', [job])
        self.write('orion/registration.json', dict(recipe_id=RECIPE_ID,
                                                  rendered_layout_sha256='wrong'))
        self.assertEqual(CloseupRetries(self.root).status, 'unavailable')


class CloseupFrozenConfigTest(unittest.TestCase):
    def test_saved_layout_and_original_recovery_policy(self):
        folder = Path(__file__).resolve().parents[1]/'config/bev_closeup'
        manifest = json.loads((folder/'manifest.json').read_bytes())
        raw = (folder/'layout.json').read_bytes()
        self.assertEqual(len(raw), manifest['layout_size_bytes'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), LAYOUT_SHA)
        self.assertEqual(manifest['layout_sha256'], LAYOUT_SHA)
        layout = json.loads(raw)
        self.assertEqual(layout['layout'], 'Voyager3DPanel!2olm9lp')
        view = layout['configById'][layout['layout']]['viewBehaviorContextParams']['viewPoint']
        self.assertEqual(view['visualCameraToTargetDistance'], 30)
        # Transform the world target back into the frozen ego frame.
        matrix, center = view['prevInvertTransformMatrix'], view['viewCenter']
        ego = [sum(matrix[4*j+i]*center[j] for j in range(3))+matrix[12+i]
               for i in range(3)]
        self.assertAlmostEqual(ego[0], 4, places=6)
        self.assertAlmostEqual(ego[1], 0, places=6)
        policy_raw = (folder/'recovery-policy.json').read_bytes()
        self.assertEqual(hashlib.sha256(policy_raw).hexdigest(),
                         manifest['recovery_policy_sha256'])
        policy = json.loads(policy_raw)
        self.assertEqual([policy[k] for k in ['orion_retry_count', 'local_max_attempts',
                         'local_workers', 'local_deadline_seconds']], [1, 2, 2, 2400])
        self.assertEqual(manifest['recipe_id'], RECIPE_ID)
        self.assertEqual(manifest['activation'], 'daily_sidecar_control_required')
