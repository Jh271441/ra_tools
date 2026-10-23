"""The operational dataset selector and labeling activation share one mapping."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from ra_triage_dashboard.app.baseline_registry import BaselineEntry, BaselineRegistry
from ra_triage_dashboard.app.routers import core


class LabelingBaselineConfigTests(TestCase):
    def setUp(self):
        self.registry = BaselineRegistry(tuple(
            BaselineEntry(id=i, label=label, scope=scope, loader='test', xlsx=Path('unused'))
            for i, label, scope in [
                ('0508', '0508', 'legacy'),
                ('1009-2026-10-15', '1009 daily', 'old-daily'),
            ]
        ))
        self.db = Mock()
        self.db.default_model_run_id.return_value = ''
        self.db.list_version_datasets.return_value = [
            dict(release_family='20261009', name='1009 复核集', targets=624),
            dict(release_family='20261016', name='1016 复核集', targets=79),
        ]
        self.db.labeling_scope_states.return_value = [
            dict(baseline_scope=scope, status='active')
            for scope in ['legacy', 'old-daily', 'manual_sidecar_version_20261009',
                          'manual_sidecar_version_20261016', 'unregistered-scope']
        ]

    def payload(self):
        with patch.object(core, 'database', self.db), \
             patch.object(core, 'baseline_registry', self.registry), \
             patch.object(core, 'runtime_state', dict(baseline={}, trail_sync={})), \
             patch.object(core, 'gt_sync_status', return_value={}), \
             patch.object(core, '_missing_evidence_catalog', return_value=[]), \
             patch.object(core, '_review_tag_catalog', return_value=[]), \
             patch.object(core.model_catalog, 'status', return_value={}):
            return core._dashboard_config_payload()

    def test_active_versions_are_accessible_and_legacy_deep_links_survive(self):
        payload = self.payload()
        visible = {b['id']: b for b in payload['baselines']}
        self.assertEqual(visible['version-20261009']['count'], 624)
        self.assertEqual(visible['version-20261016']['count'], 79)
        self.assertNotIn('1009-2026-10-15', visible)
        self.assertEqual(payload['case_labeling']['active_baseline_ids'], [
            '0508', '1009-2026-10-15', 'version-20261009', 'version-20261016',
        ])
        self.db.list_version_datasets.assert_called_once_with()
        self.assertIsNone(self.registry.scope_to_id('manual_sidecar_version_20261009'))

    def test_paused_and_unknown_scopes_do_not_become_active(self):
        self.db.labeling_scope_states.return_value[3]['status'] = 'paused'
        payload = self.payload()
        self.assertIn('version-20261016', [b['id'] for b in payload['baselines']])
        self.assertNotIn('version-20261016', payload['case_labeling']['active_baseline_ids'])
        self.db.list_version_datasets.return_value = []
        self.assertEqual(self.payload()['case_labeling']['active_baseline_ids'], ['0508', '1009-2026-10-15'])

    def test_empty_active_version_keeps_real_empty_state_and_fresh_activation(self):
        self.db.list_version_datasets.return_value[1]['targets'] = 0
        self.db.labeling_scope_states.return_value[3]['status'] = 'pending'
        self.assertNotIn('version-20261016', self.payload()['case_labeling']['active_baseline_ids'])
        self.db.labeling_scope_states.return_value[3]['status'] = 'active'
        self.assertIn('version-20261016', self.payload()['case_labeling']['active_baseline_ids'])
