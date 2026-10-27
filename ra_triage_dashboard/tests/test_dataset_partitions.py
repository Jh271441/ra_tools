"""Frozen ODD memberships are selections, never rewrites of human/GT provenance."""
import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.baseline_registry import BaselineEntry, BaselineRegistry
from ra_triage_dashboard.app.dataset_partitions import load_partitions, SOURCE_IDS, SOURCE_SCOPES, PARTITION_IDS
from ra_triage_dashboard.app.support import baselines
from ra_triage_dashboard.app.routers import core, runs


class DatasetPartitionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ids = [f'cn{100000 + index}' for index in range(2005)]
        self.parts = dict(zip(PARTITION_IDS, [self.ids[:1026], self.ids[1026:]]))
        self.manifest = dict(schema='0821-odd-partitions-v1', partitions=self.parts,
                             membership_sha256=hashlib.sha256('\n'.join(sorted(self.ids)).encode()).hexdigest())
        self.path = self.root / 'dataset_partitions/0821.json'
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(self.manifest))
        self.db = Database(self.root / 'test.sqlite3')
        self.db.init()
        self.registry = BaselineRegistry(tuple(BaselineEntry(id=key, label=key, scope=scope,
            loader='test', xlsx=Path('unused'), default_selected=index == 0)
            for index, (key, scope) in enumerate(zip(SOURCE_IDS, SOURCE_SCOPES))))
        for index, scope in enumerate(SOURCE_SCOPES):
            self.db.upsert_issues([dict(issue_id=i, gt_label='误触发') for i in self.ids[index::3]],
                source='fixture', replace_gt=True, baseline_scope=scope)
        self.run, _ = self.db.import_model_run(name='saved', source_name='saved.json',
            source_sha256='saved-fixture', metadata={}, rows=[dict(issue_id=i, model_label='误触发') for i in self.ids])
        for name, value in [('settings', SimpleNamespace(data_dir=self.root)),
                            ('baseline_registry', self.registry), ('database', self.db)]:
            self.addCleanup(patch.stopall)
            patch.object(baselines, name, value).start()

    def test_frozen_disjoint_cover_and_fail_closed(self):
        parts = load_partitions(self.root)
        self.assertEqual([len(parts[key]) for key in PARTITION_IDS], [1026, 979])
        self.assertFalse(parts[PARTITION_IDS[0]] & parts[PARTITION_IDS[1]])
        self.manifest['partitions'][PARTITION_IDS[1]][0] = self.ids[0]
        self.path.write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):
            load_partitions(self.root)
        self.path.unlink()
        for raw in [PARTITION_IDS[0], [PARTITION_IDS[1]]]:
            with self.assertRaises(HTTPException) as caught:
                baselines.resolve_request_baseline_scopes(raw)
            self.assertEqual(caught.exception.status_code, 503)

    def test_csv_list_query_mixed_and_empty_intersections(self):
        for raw in [PARTITION_IDS[0], [PARTITION_IDS[0]]]:
            self.assertEqual(set(baselines.resolve_request_baseline_scopes(raw)), set(SOURCE_SCOPES))
            self.assertEqual(set(baselines.restrict_version_issue_ids(raw)), set(self.ids[:1026]))
        request = Request(dict(type='http', query_string=b'baselines=0821-nonodd2', headers=[]))
        self.assertEqual(len(baselines.restrict_version_issue_ids(request=request)), 979)
        self.assertEqual(len(baselines.restrict_version_issue_ids(list(PARTITION_IDS))), 2005)
        empty = baselines.restrict_version_issue_ids(PARTITION_IDS[0], issue_ids=[self.ids[-1]])
        self.assertTrue(empty)
        self.assertNotIn(self.ids[-1], empty)
        mixed = baselines.restrict_version_issue_ids([PARTITION_IDS[0], SOURCE_IDS[0]])
        self.assertEqual(set(mixed), set(self.ids[:1026]) | set(self.ids[::3]))

    def test_overview_runs_comparison_label_projection_share_membership(self):
        for key, expected in zip(PARTITION_IDS, [1026, 979]):
            selected = baselines.restrict_version_issue_ids(key)
            overview = self.db.overview(baseline_scopes=SOURCE_SCOPES, issue_ids=selected, model_run_id=self.run['id'])
            self.assertEqual((overview['issues'], overview['predictions']), (expected, expected))
            self.assertEqual(overview['label_state_counts']['none'], expected)
            run = self.db.list_model_runs(baseline_scopes=SOURCE_SCOPES, issue_ids=selected)[0]
            self.assertEqual(run['baseline_prediction_count'], expected)
            comparison = self.db.compare_model_runs(baseline_run_id='', candidate_run_id=self.run['id'],
                baseline_scopes=SOURCE_SCOPES, issue_ids=selected)
            self.assertEqual(comparison['total'], expected)
            projected, _ = self.db._project_labeling_cases(baseline_scopes=SOURCE_SCOPES, issue_ids=selected)
            self.assertEqual({row['issue_id'] for row in projected}, set(selected))
        counts = self.db.model_run_partition_coverage_map([self.run['id']], load_partitions(self.root))
        self.assertEqual(counts[self.run['id']], dict(zip(PARTITION_IDS, [1026, 979])))
        self.assertEqual(self.db.baseline_issue_ids(baseline_scopes=SOURCE_SCOPES), sorted(self.ids))

    def test_route_counts_and_comparison_detail_guard(self):
        request = Request(dict(type='http', query_string=b'baselines=0821-nonodd2', headers=[]))
        with patch.object(core, 'database', self.db):
            payload = asyncio.run(core.overview(request, model_run_id=self.run['id'], baselines=PARTITION_IDS[1]))
        self.assertEqual(payload['issues'], 979)
        with patch.object(runs, 'database', self.db):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(runs.comparison_case_inputs(request, self.ids[0], candidate_run_id=self.run['id'], baselines=PARTITION_IDS[1]))
        self.assertEqual(caught.exception.status_code, 404)

    def test_visible_catalog_preserves_sources(self):
        result = baselines.operational_baseline_summaries(self.registry.public_summaries(), self.db)
        self.assertEqual({row['id'] for row in result}, set(PARTITION_IDS))
        self.assertEqual(self.registry.allowed_ids(), set(SOURCE_IDS))
        hint = baselines.enrich_model_run_baseline_hint(self.run)
        self.assertEqual(hint['inferred_baseline_ids'], list(PARTITION_IDS))
        self.assertEqual(sum(row['prediction_count'] for row in hint['baseline_coverage']), 2005)

    def test_case_public_identity_is_partition_not_import_source(self):
        for index in [0, 1025, 1026, 2004]:
            self.assertEqual(baselines.issue_dataset_id(self.ids[index], SOURCE_IDS[index % 3]),
                             PARTITION_IDS[0 if index < 1026 else 1])
        self.assertEqual(baselines.issue_dataset_id('cnother', '0508'), '0508')
        with self.assertRaises(HTTPException):
            baselines.issue_dataset_id('cnmissing', SOURCE_IDS[0])
