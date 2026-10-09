import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'scripts/deploy_8786.py'
spec = importlib.util.spec_from_file_location('deploy_8786', PATH)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
SHA = 'a' * 40
OLD = 'b' * 40


class SmokeDeployTest(unittest.TestCase):
    def archive(self, root, name='ra_triage_dashboard/app/main.py', identity=SHA, link=False):
        path = root / 'source.tar.gz'
        with tarfile.open(path, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': identity}) as tar:
            item = tarfile.TarInfo(name)
            if link:
                item.type = tarfile.SYMTYPE
                item.linkname = '/tmp/outside'
                tar.addfile(item)
            else:
                data = b'print("test")\n'
                item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
        return path

    def test_archive_rejects_wrong_commit_traversal_and_links_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, identity, link in [
                ('ra_triage_dashboard/app/main.py', OLD, False),
                ('../outside', SHA, False),
                ('/absolute', SHA, False),
                ('ra_triage_dashboard/link', SHA, True),
            ]:
                with self.subTest(name=name, identity=identity, link=link):
                    with self.assertRaises(RuntimeError):
                        deploy.archive_contents(self.archive(root, name, identity, link), SHA)
                    self.assertFalse((root / ('source-' + SHA)).exists())

    def test_existing_source_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = deploy.archive_contents(self.archive(root), SHA)
            source = deploy.stage_source(root, SHA, files)
            self.assertEqual(deploy.stage_source(root, SHA, files), source)
            with self.assertRaisesRegex(RuntimeError, 'immutable'):
                deploy.stage_source(root, SHA, {**files, 'ra_triage_dashboard/app/main.py': b'changed'})

    def prepare(self, root):
        (root / 'config').mkdir()
        (root / 'config/source_sha').write_text(OLD + '\n')
        (root / 'config/postgres_url').write_text('fixture only')
        (root / 'config/service_env.json').write_text('{}')
        return deploy.config_fingerprints(root)

    def test_config_race_stops_before_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.prepare(root)
            (root / 'config/service_env.json').write_text('{"changed":true}')
            with patch.object(deploy.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'configuration changed'):
                    deploy.activate(root, SHA, OLD, config)
                run.assert_not_called()
            self.assertEqual((root / 'config/source_sha').read_text().strip(), OLD)

    def test_failed_health_restores_previous_source_and_same_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.prepare(root)
            with patch.object(deploy, 'health', return_value={'build_commit': 'production'}), \
                 patch.object(deploy.subprocess, 'run') as run, \
                 patch.object(deploy, 'wait_health', side_effect=[RuntimeError('bad candidate'), {'ok': True}]) as health:
                with self.assertRaisesRegex(RuntimeError, 'bad candidate'):
                    deploy.activate(root, SHA, OLD, config)
                self.assertEqual((root / 'config/source_sha').read_text().strip(), OLD)
                self.assertEqual(health.call_args_list[-1].args, (OLD,))
                restarts = [x.args[0] for x in run.call_args_list if 'supervisorctl' in x.args[0]]
                self.assertEqual(restarts, [['sudo', 'supervisorctl', 'restart', deploy.PROGRAM]] * 2)
