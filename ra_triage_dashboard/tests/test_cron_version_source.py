from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app.cron_version_source import version_queue_states, version_status


class VersionStatusTest(unittest.TestCase):
    def test_missing_queue_is_unknown_and_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'missing'
            self.assertIsNone(version_queue_states(root))
            self.assertFalse(root.exists())

    def test_versions_use_queue_not_import_states_and_media_uses_exact_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'ra_auto_triage_deploy/state/version_incremental_v3'
            state.mkdir(parents=True)
            (state / 'control.json').write_text(json.dumps({'enabled': True}))
            (state / 'heartbeat.json').write_text(json.dumps({'states': {'published': 8},
                'families': ['20261009', '20261016', '20261023', '20261030'], 'checked_at': time.time()}))
            ledger = state / 'ledger.sqlite3'
            with sqlite3.connect(ledger) as db:
                db.execute('CREATE TABLE items(family TEXT,state TEXT)')
                db.executemany('INSERT INTO items VALUES(?,?)', [('20261009','published'),
                    ('20261009','waiting_metadata'), ('20261016','running'), ('20261023','published'),
                    ('20261030','waiting_metadata')])
            before = hashlib.sha256(ledger.read_bytes()).hexdigest()
            datasets = [{'id': f'd{i}', 'release_family': f, 'states': {'published': 99}}
                        for i, f in enumerate(['20261009','20261016','20261023'])]
            db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
            self.addCleanup(db.close)
            db.executescript('CREATE TABLE version_datasets(id TEXT,release_family TEXT);'
                            'CREATE TABLE version_dataset_items(dataset_id TEXT,issue_id TEXT,is_target INTEGER);')
            db.executemany('INSERT INTO version_datasets VALUES(?,?)', [(d['id'],d['release_family']) for d in datasets])
            db.executemany('INSERT INTO version_dataset_items VALUES(?,?,?)',
                           [('d0','cn1',1),('d0','cnRetired',0),('d1','cn2',1),('d2','cn3',1)])
            @contextmanager
            def connect():
                yield db
            database = SimpleNamespace(connect=connect, list_version_datasets=lambda: datasets)
            outbox = state / 'outbox'; outbox.mkdir()
            (outbox / 'one.receipt.json').write_text(json.dumps({'media': {
                'reused_ids':['cn1','cnRetired'], 'queued_ids':['cn1','cn2','cn3']}}))
            media = root / 'ra_auto_triage/reports/manual_sidecar_20261019/versions/20261023/batch'
            (media / 'media-publication').mkdir(parents=True)
            (media / 'media-publication/cn3.json').write_text(json.dumps({'state':'verified','issue_id':'cn3'}))
            (media / 'final-failures.json').write_text(json.dumps({'failures':[{'issue_id':'cn2'},{'issue_id':'cn3'}]}))
            runtime = SimpleNamespace(database=database)
            with patch.dict(sys.modules, {'ra_triage_dashboard.app.runtime': runtime}), patch(
                'ra_triage_dashboard.app.cron_incremental_history.incremental_history', return_value={'status':'empty','items':[]}):
                result = version_status(root / 'ra_auto_triage')
                versions = {v['family']:v for v in result['versions']}
                self.assertEqual(len(versions),4)
                self.assertEqual(versions['20261009']['states'], {'published':1,'waiting_metadata':1})
                self.assertEqual(versions['20261016']['states'], {'running':1})
                self.assertEqual(versions['20261030']['media']['selected'],0)
                self.assertEqual(versions['20261009']['media']['verified'],1)
                self.assertEqual(versions['20261016']['media']['failure_count'],1)
                self.assertEqual(versions['20261023']['media']['failure_count'],0)
                self.assertEqual(result['media']['verified'],2)
                self.assertEqual(sum(v['media']['selected'] for v in versions.values()),result['media']['selected'])
                with patch('ra_triage_dashboard.app.cron_version_source.version_queue_states', return_value=None):
                    unavailable=version_status(root / 'ra_auto_triage')
                self.assertTrue(all(v['states_status']=='unavailable' and v['states'] is None for v in unavailable['versions']))
                self.assertEqual(unavailable['media'],result['media'])
            self.assertEqual(before,hashlib.sha256(ledger.read_bytes()).hexdigest())
