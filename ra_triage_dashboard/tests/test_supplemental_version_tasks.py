"""Explicit re-review tasks remain discoverable beside consolidated versions."""
import importlib.util
from pathlib import Path
import unittest
import json
import sqlite3
from types import SimpleNamespace

source = Path(__file__).parents[1] / 'app' / 'version_review_tasks.py'
spec = importlib.util.spec_from_file_location('supplemental_version_tasks', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SupplementalVersionTaskTests(unittest.TestCase):
    def setUp(self):
        self.parent = dict(split_id='canonical', model_run_id='run1009')
        self.supplemental = dict(split_id='recheck', model_run_id='run1009',
                                 filter_snapshot={'supplemental_review': True},
                                 workflow_mode='model_review_and_case_label')
        self.old_source = dict(split_id='old-source', model_run_id='run1009')
        self.other = dict(split_id='ordinary', model_run_id='another-run')

    def test_versions_view_includes_explicit_same_run_recheck(self):
        items = [self.parent, self.supplemental, self.old_source, self.other]
        self.assertEqual(module.merge_version_task_list([self.parent], items, version_only=True),
                         [self.parent, self.supplemental])

    def test_all_current_retains_other_runs_without_old_source_duplicates(self):
        items = [self.supplemental, self.parent, self.old_source, self.other]
        self.assertEqual(module.merge_version_task_list([self.parent], items),
                         [self.parent, self.supplemental, self.other])

    def test_supplemental_flag_requires_explicit_boolean(self):
        for value in ['true', 1, False, None]:
            item = dict(self.supplemental, filter_snapshot={'supplemental_review': value})
            self.assertEqual(module.merge_version_task_list([self.parent], [item], version_only=True),
                             [self.parent])

    def test_another_version_does_not_leak_into_versions_filter(self):
        item = dict(self.supplemental, model_run_id='other-version')
        self.assertEqual(module.merge_version_task_list([self.parent], [item], version_only=True),
                         [self.parent])

    def test_canonical_is_not_duplicated_even_with_flag(self):
        parent = dict(self.parent, filter_snapshot={'supplemental_review': True})
        self.assertEqual(module.merge_version_task_list([parent], [parent]), [parent])

    def test_empty_parent_scope_preserves_only_all_current_items(self):
        self.assertEqual(module.merge_version_task_list([], [self.supplemental], version_only=True), [])
        self.assertEqual(module.merge_version_task_list([], [self.supplemental]), [self.supplemental])

    def test_manual_tasks_and_recency_sorting_surface_new_tasks_first(self):
        old_ver = dict(self.parent, appendable=True, last_target_added_at='2026-10-23T10:00:00+00:00', created_at='2026-10-23T04:00:00+00:00')
        new_manual_same_run = dict(
            split_id='manual-on-version-run', model_run_id='run1009',
            filter_snapshot={'manual_task': True}, created_at='2026-11-24T05:19:00+00:00',
        )
        other_manual = dict(self.other, created_at='2026-11-01T00:00:00+00:00')
        merged = module.merge_version_task_list([old_ver], [other_manual, new_manual_same_run, self.old_source])
        self.assertEqual([item['split_id'] for item in merged], ['manual-on-version-run', 'ordinary', 'canonical'])
        manual_only = module.merge_version_task_list([old_ver], [other_manual, new_manual_same_run, self.old_source], manual_only=True)
        self.assertEqual([item['split_id'] for item in manual_only], ['manual-on-version-run', 'ordinary'])

    def test_automatic_version_tasks_keep_version_order_even_when_older_version_backfills_later(self):
        v1113_samp = dict(
            split_id='v1113-s', model_run_id='r1113', release_family='20261113',
            appendable=True, last_target_added_at='2026-11-23T08:00:00+00:00',
        )
        v1113_low = dict(
            split_id='v1113-l', model_run_id='r1113', release_family='20261113',
            appendable=True, last_target_added_at='2026-11-23T08:00:00+00:00',
        )
        v1106_backfill = dict(
            split_id='v1106-s', model_run_id='r1106', release_family='20261106',
            appendable=True, last_target_added_at='2026-11-24T04:00:00+00:00',
        )
        v1030 = dict(
            split_id='v1030', model_run_id='r1030', release_family='20261030',
            appendable=True, last_target_added_at='2026-11-10T00:00:00+00:00',
        )
        manual_newest = dict(
            split_id='manual-new', model_run_id='r0821',
            filter_snapshot={'manual_task': True}, created_at='2026-11-24T05:30:00+00:00',
        )
        manual_mid = dict(
            split_id='manual-mid', model_run_id='r0821',
            filter_snapshot={'manual_task': True}, created_at='2026-11-15T00:00:00+00:00',
        )
        # Deliberately pass parents out of order to verify version-family sorting + cohort tie-break
        parents = [v1030, v1106_backfill, v1113_samp, v1113_low]
        version_only = module.merge_version_task_list(parents, [manual_newest, manual_mid], version_only=True)
        self.assertEqual([item['split_id'] for item in version_only], ['v1113-s', 'v1113-l', 'v1106-s', 'v1030'])

        merged = module.merge_version_task_list(parents, [manual_mid, manual_newest])
        self.assertEqual(
            [item['split_id'] for item in merged],
            ['manual-new', 'v1113-s', 'v1113-l', 'v1106-s', 'manual-mid', 'v1030'],
        )


class SupplementalTaskDatasetTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
            CREATE TABLE issue_work_splits(id TEXT,filter_json TEXT);
            CREATE TABLE version_datasets(id TEXT,release_family TEXT);
            CREATE TABLE version_dataset_items(dataset_id TEXT,issue_id TEXT);
            CREATE TABLE campaign_issue_members(campaign_id TEXT,issue_id TEXT);
        ''')
        self.conn.execute('INSERT INTO issue_work_splits VALUES(?,?)',
                          ('recheck', json.dumps({'supplemental_review': True, 'dataset_id': 'version1009'})))
        self.conn.execute('INSERT INTO version_datasets VALUES(?,?)', ('version1009','20261009'))
        for iid in ['old-source-case','version-scope-case']:
            self.conn.execute('INSERT INTO version_dataset_items VALUES(?,?)', ('version1009',iid))
            self.conn.execute('INSERT INTO campaign_issue_members VALUES(?,?)', ('recheck',iid))
        self.db = SimpleNamespace(connect=lambda: self.conn)

    def test_all_original_scopes_resolve_to_public_version_id(self):
        self.assertEqual(module.supplemental_task_baseline_ids(self.db,'recheck'), ['version-20261009'])

    def test_outside_member_fails_without_broadening(self):
        self.conn.execute('INSERT INTO campaign_issue_members VALUES(?,?)', ('recheck','outside'))
        with self.assertRaises(ValueError):
            module.supplemental_task_baseline_ids(self.db,'recheck')

    def test_missing_task_preserves_existing_mapping(self):
        self.assertEqual(module.supplemental_task_baseline_ids(self.db,'missing'), [])

    def test_ordinary_task_preserves_existing_mapping(self):
        self.conn.execute('UPDATE issue_work_splits SET filter_json=?', ('{}',))
        self.assertEqual(module.supplemental_task_baseline_ids(self.db,'recheck'), [])

    def test_missing_version_does_not_invent_dataset(self):
        self.conn.execute('DELETE FROM version_datasets')
        self.assertEqual(module.supplemental_task_baseline_ids(self.db,'recheck'), [])

    def test_empty_task_fails_without_broadening(self):
        self.conn.execute('DELETE FROM campaign_issue_members')
        with self.assertRaises(ValueError):
            module.supplemental_task_baseline_ids(self.db,'recheck')


if __name__ == '__main__':
    unittest.main()
