import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts import core

ROOT = Path(__file__).resolve().parents[1]


class RefactorBoundariesTest(unittest.TestCase):
    def test_runtime_factory_and_catalog_import_without_initializing_services(self):
        code = """
import sys
from app import runtime_services, runtime_catalogs
assert 'app.runtime' not in sys.modules
assert not hasattr(runtime_services, 'database')
assert callable(runtime_services.build_runtime_services)
assert len(runtime_catalogs.REVIEW_TAG_CATALOG)>0
"""
        subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True, capture_output=True)

    def test_initializer_keeps_migration_before_single_locked_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'test.sqlite')
            db.backend = 'postgresql'
            events = []
            connection = object()
            manager = MagicMock()
            manager.__enter__.side_effect = lambda: (events.append('connect'), connection)[1]
            manager.__exit__.side_effect = lambda *args: events.append('commit')
            phases = ['schema', 'change_tracking', 'campaign_compat', 'columns', 'recovery']
            patches = []
            try:
                for phase in phases:
                    patcher = patch.object(core, 'initialize_' + phase,
                        side_effect=lambda instance, conn, name=phase: events.append((name, conn is connection)))
                    patches.append(patcher)
                    patcher.start()
                with patch.object(db, '_apply_postgres_migrations', side_effect=lambda: events.append('migrations')), \
                     patch.object(db, 'connect', return_value=manager) as connect:
                    db.init()
                    connect.assert_called_once()
                self.assertEqual(events, ['migrations', 'connect', *[(p, True) for p in phases], 'commit'])
            finally:
                for patcher in reversed(patches):
                    patcher.stop()

    def test_no_domain_module_imports_compatibility_facades(self):
        for pattern, forbidden in [('app/db_parts/labeling_*.py', 'labeling'),
                                   ('app/db_parts/run_collection_*.py', 'run_collections'),
                                   ('app/routers/labeling_api/*.py', 'labeling')]:
            for path in ROOT.glob(pattern):
                with self.subTest(path=path.name):
                    tree = ast.parse(path.read_text())
                    self.assertFalse(any(isinstance(n, ast.ImportFrom) and n.module == forbidden
                                         for n in ast.walk(tree)))
