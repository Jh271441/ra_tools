"""Failure isolation and small-result recovery across native task outcomes."""
import io
import json
from pathlib import Path
import shutil
import struct
import sys
import tarfile
import tempfile
from types import SimpleNamespace
from contextlib import nullcontext
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app.planning_text_artifact import identity, object_key, write_artifact
from ra_triage_dashboard.app.planning_text_daily import register_owner, read_daily_window
from ra_triage_dashboard.scripts.planning_text import hook, import_results, worker
from ra_triage_dashboard.scripts.planning_text import runner
from ra_triage_dashboard.tests.test_planning_text_daily import ANCHOR, MEMBER, observation


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def scan(self, parse_error=None, extract_error=None):
        path = self.root/'acquired.bag'
        path.touch()
        class Message:
            def ParseFromString(self, raw):
                if parse_error:
                    raise parse_error
            def IsInitialized(self):
                return True
        class Bag:
            def __init__(self, _path):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read_messages(self, **_):
                yield '/planning/planning_debug', (None, struct.pack('<I', 1)+b'x', None, None, Message), SimpleNamespace(to_nsec=lambda: ANCHOR*1000000)
        modules = {'voy_vbag': SimpleNamespace(Bag=Bag),
                   'rospy': SimpleNamespace(Time=lambda *args: args),
                   'google.protobuf.message': SimpleNamespace(DecodeError=type('DecodeError', (Exception,), {}))}
        with patch.dict(sys.modules, modules), patch.object(worker, 'schema_sha', return_value='b'*64), patch.object(worker, 'extract_frame', side_effect=extract_error, return_value=observation(0)['frame']):
            return worker.scan(dict(start_ms=ANCHOR-100, end_ms=ANCHOR+100, inputs=[str(path)]))

    def test_resource_and_extractor_faults_never_become_malformed_messages(self):
        with self.assertRaises(MemoryError):
            self.scan(parse_error=MemoryError())
        with self.assertRaises(AttributeError):
            self.scan(extract_error=AttributeError('incompatible schema'))
        self.assertEqual(self.scan(parse_error=ValueError('invalid bytes'))[0]['decode'], 'failed')
        self.assertEqual(self.scan()[0]['decode'], 'passed')

    def test_export_failure_never_raises_into_video_preparation(self):
        with patch.object(hook, 'context', side_effect=RuntimeError('injected')):
            manifest = self.root/'manifest.json'
            manifest.write_text('{}')
            with patch.dict('os.environ', PLANNING_TEXT_MANIFEST=str(manifest)):
                hook.before_reduce([], 'trip-unit', self.root/'prepared')
        state = json.loads((self.root/'planning-text-prepared/state.json').read_text())
        self.assertEqual(state, dict(state='text_requires_review', error_type='RuntimeError'))

    def test_native_context_queries_task_args_and_validates_all_identity_fields(self):
        member = dict(MEMBER, owner='owner', extract=True)
        task = dict(id=1100000000, job_id=11, version=0, task_args={
            '--issue-id': member['issue_id'], '--trip-id': member['trip_id'],
            '--capture-timestamp-ms': str(member['anchor_ms'])})
        from unittest.mock import Mock
        accessor = SimpleNamespace(query_one_page=Mock(return_value=[task]))
        modules = {'orion.model.constants': SimpleNamespace(TaskEnvirons=SimpleNamespace(
                       TASK_ID='ORION_TASK_ID', JOB_ID='ORION_JOB_ID', VERSION='ORION_TASK_VERSION')),
                   'orion.db_accessor.task_accessor': SimpleNamespace(TaskAccessor=accessor),
                   'voy_data_utils.regions': SimpleNamespace(Regions=SimpleNamespace(CN='CN'), TrailRegionMgr=lambda _: nullcontext())}
        env = dict(ORION_JOB_ID='11', ORION_TASK_ID='1100000000', ORION_TASK_VERSION='0')
        manifest = dict(members=[member], worker_source_sha256='d'*64, base_tool_sha256='e'*64)
        with patch.dict(sys.modules, modules), patch.dict('os.environ', env):
            actual, producer = hook.context(member['trip_id'], manifest)
            self.assertEqual(actual, member)
            self.assertEqual(producer['task_id'], task['id'])
            accessor.query_one_page.assert_called_with(dict(id=task['id'], extra_fields='task_args'), 1, 2, timeout=10, max_attempts=1)
            task['version'] = 1
            with self.assertRaisesRegex(ValueError, 'native_identity_mismatch'):
                hook.context(member['trip_id'], manifest)

    def test_archive_links_and_extra_files_are_rejected_before_extraction(self):
        archive = self.root/'unsafe.tgz'
        with tarfile.open(archive, 'w:gz') as stream:
            for name in ('frames.jsonl', 'result.json', 'receipt.json'):
                member = tarfile.TarInfo(name)
                member.type = tarfile.SYMTYPE
                member.linkname = '../escape'
                stream.addfile(member)
        with self.assertRaisesRegex(ValueError, 'invalid_planning_archive'):
            import_results.unpack(archive, self.root/'unpacked')
        self.assertFalse((self.root/'unpacked').exists())

    def test_overlay_fault_falls_back_to_original_video_config(self):
        from unittest.mock import Mock
        import copy
        baseline = dict(output=str(self.root/'video'), target='orion', orion=dict(tool_bundle_locator='frozen-base'))
        cli = SimpleNamespace(run_workflow=Mock(return_value='unchanged-video'))
        def broken(config, _profile):
            config['orion']['tool_bundle_locator'] = 'injected-bad-overlay'
            raise RuntimeError('injected')
        with patch.dict(sys.modules, {'ares_animation': SimpleNamespace(cli=cli)}), patch.object(runner, 'selected_control', return_value={'enabled': True}), patch.object(runner, 'overlay_config', side_effect=broken):
            original = cli.run_workflow
            installed = runner.install()
            self.assertEqual(installed.run_workflow(copy.deepcopy(baseline)), 'unchanged-video')
            original.assert_called_once_with(baseline)
        self.assertEqual(json.loads((self.root/'video/.control/planning-text/error.json').read_text())['state'], 'text_requires_review')

    def test_failed_video_task_can_publish_early_text_once_without_any_bag_read(self):
        data = self.root/'data'
        member = dict(MEMBER, owner='original-owner', extract=True)
        key = identity(member)
        register_owner(data, member, member['owner'])
        producer = dict(kind='orion', job_id=11, task_id=1100000000, task_version=0,
                        owner=member['owner'], worker_source_sha256='d'*64)
        artifact = self.root/'worker-artifact'
        write_artifact(artifact, member, [observation(0)], producer)
        archive = self.root/'worker-result.tgz'
        with tarfile.open(archive, 'w:gz') as stream:
            for name in ('frames.jsonl', 'result.json', 'receipt.json'):
                stream.add(artifact/name, arcname=name)
        run = self.root/'failed-native-run'
        hook.save(run/'launch.receipt.json', dict(status='submitted', job_id=11))
        hook.save(data/'planning_constraints/runs/run.json', dict(run=str(run), members=[member], worker_source_sha256='d'*64))
        file = dict(job_id=11, task_id=1100000000, task_version=0,
                    file_size=archive.stat().st_size, capture_key=key,
                    storage_location='gift3x:cn_nmg:'+object_key(member, 11, 1100000000, 0))
        observed = dict(files=[file], missing=[], job_state=2, pending_task_count=1, next_cursor=0)
        state = {}
        with patch.object(import_results, 'list_files', return_value=observed) as listing, patch.object(import_results, 'download', side_effect=lambda _, target: shutil.copyfile(archive, target)) as download, patch.object(worker, 'scan', side_effect=AssertionError('No Bag reads')):
            import_results.tick(dict(data_dir=str(data)), state)
            self.assertEqual(read_daily_window(data, member['issue_id'], 0)['matched_frame']['object_id'], 0)
            import_results.tick(dict(data_dir=str(data)), state)
        self.assertEqual(state['imported'], 1)
        self.assertEqual(listing.call_count, 1)
        self.assertEqual(download.call_count, 1)

    def test_native_observation_timeout_preserves_last_success_and_pending_owner(self):
        data = self.root/'data'
        member = dict(MEMBER, owner='owner', extract=True)
        register_owner(data, member, member['owner'])
        run = self.root/'run'
        hook.save(run/'launch.receipt.json', dict(status='submitted', job_id=11))
        hook.save(data/'planning_constraints/runs/run.json', dict(run=str(run), members=[member], worker_source_sha256='d'*64))
        state = dict(native_observations={'11': dict(last_success_at=123)})
        with patch.object(import_results, 'list_files', side_effect=TimeoutError):
            import_results.tick(dict(data_dir=str(data)), state)
        self.assertEqual(state['native_observations']['11']['last_success_at'], 123)
        self.assertEqual(state['native_observations']['11']['error'], 'TimeoutError')
        self.assertEqual(read_daily_window(data, member['issue_id'], 0)['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
