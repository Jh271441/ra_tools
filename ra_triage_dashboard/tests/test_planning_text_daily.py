import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app.planning_text_artifact import build_result, identity, write_artifact, load_artifact
from ra_triage_dashboard.app.planning_text_daily import register_owner, import_artifact, read_daily_window, index_path, cohort_counts, transfer_owner, capture_owner
from ra_triage_dashboard.app.planning_constraint_index import read_saved_window

ANCHOR = 1790000000000
MEMBER = dict(issue_id='cn1234', trip_id='trip-unit', anchor_ms=ANCHOR, version='1016', datasets=['version-20261016'])


def observation(ms, *, status='ready', ns=0, failed=False):
    stamp = (ANCHOR+ms)*1000000+ns
    return dict(publish_ns=str(stamp), raw_bytes=100, raw_sha256='a'*64, schema_sha256='b'*64,
                decode='failed' if failed else 'passed', full_protobuf_decode=not failed,
                frame=None if failed else dict(timestamp_ms=stamp//1000000,
                planning_timestamp_ms=ANCHOR+ms-75, status=status, object_id=0,
                constraint_id='original-<id>' if status == 'ready' else None,
                raw='Non gap align. Dominant constraint: original-<id>, Object id: 0.'))


class PlanningTextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data, self.artifact = self.root/'data', self.root/'artifact'
        self.member, self.owner = dict(MEMBER), 'unit-owner'
        self.producer = dict(kind='local', attempt_id='unit-attempt')

    def publish(self, rows=None, **kwargs):
        rows = rows if rows is not None else [observation(-100), observation(100, status='no_constraint'), observation(200, status='unresolved')]
        write_artifact(self.artifact, self.member, rows, self.producer, **kwargs)
        register_owner(self.data, self.member, self.owner)
        return import_artifact(self.data, self.artifact, self.member, self.owner)

    def test_exact_identity_raw_object_zero_and_causal_gap(self):
        imported = self.publish()
        self.assertEqual(imported['frame_count'], 3)
        result = read_saved_window(self.data, self.member['issue_id'], 0)
        self.assertEqual(result['read_source'], 'daily_index')
        self.assertEqual(result['matched_frame']['object_id'], 0)
        self.assertEqual(result['matched_frame']['constraint_id'], 'original-<id>')
        self.assertIsNone(read_daily_window(self.data, 'cn1234', 99)['matched_frame'])
        self.assertEqual(read_daily_window(self.data, 'cn1234', 100)['matched_frame']['status'], 'no_constraint')
        self.assertEqual(read_daily_window(self.data, 'cn1234', 200)['matched_frame']['status'], 'unresolved')
        self.assertIsNone(read_daily_window(self.data, 'cn1234', 351)['matched_frame'])
        self.assertIsNone(read_daily_window(self.data, 'cn1234', 0, trip_id='other'))

    def test_native_nanoseconds_are_lossless_and_equal_ms_selects_latest(self):
        rows = [observation(-1, ns=1), observation(-1, ns=999999)]
        rows[1]['frame']['raw'] = 'second exact raw'
        self.publish(rows)
        value = read_daily_window(self.data, 'cn1234', 0)
        self.assertEqual(len(value['frames']), 2)
        self.assertEqual(value['matched_frame']['publish_ns'], str((ANCHOR-1)*1000000+999999))
        self.assertEqual(value['matched_frame']['raw'], 'second exact raw')

    def test_malformed_observation_cuts_prior_constraint_at_failure(self):
        self.publish([observation(-100), observation(-20, failed=True), observation(100)])
        value = read_daily_window(self.data, 'cn1234', 0)
        self.assertEqual(value['source_status'], 'failed')
        self.assertIsNone(value['matched_frame'])
        self.assertEqual(read_daily_window(self.data, 'cn1234', -21)['matched_frame']['constraint_id'], 'original-<id>')
        self.assertEqual(len(value['frames']), 2)

    def test_only_a_full_window_is_collected_and_no_constraint_is_a_frame(self):
        rows = [observation(t, status='no_constraint') for t in range(-20000, 20000, 100)]
        result = build_result(self.member, rows)
        self.assertEqual(result['extraction_status'], 'collected')
        self.assertEqual(result['gaps_ms'], [])
        self.assertEqual(result['frame_count'], 400)
        self.assertEqual(result['t0']['status'], 'no_constraint')
        self.assertEqual(build_result(self.member, [])['extraction_status'], 'partial_source')
        with self.assertRaisesRegex(ValueError, 'full_decode'):
            rows[0]['full_protobuf_decode'] = False
            build_result(self.member, rows)

    def test_owner_and_receipt_are_idempotent_and_conflicts_never_overwrite(self):
        first = self.publish()
        self.assertTrue(import_artifact(self.data, self.artifact, self.member, self.owner)['reused'])
        other = register_owner(self.data, self.member, 'other-worker')
        self.assertFalse(other['claimed'])
        with self.assertRaisesRegex(ValueError, 'owner_mismatch'):
            import_artifact(self.data, self.artifact, self.member, 'other-worker')
        folder = self.root/'different'
        write_artifact(folder, self.member, [observation(0)], self.producer)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            import_artifact(self.data, folder, self.member, self.owner)
        self.assertEqual(read_daily_window(self.data, 'cn1234', 0)['receipt_sha256'], first['receipt_sha256'])

    def test_ambiguous_captures_are_not_last_write_wins(self):
        self.publish()
        register_owner(self.data, {**self.member, 'anchor_ms': ANCHOR+1}, 'other')
        self.assertEqual(read_daily_window(self.data, 'cn1234', 0)['reason'], 'identity_conflict')
        self.assertEqual(read_daily_window(self.data, 'cn1234', 0, anchor_ms=ANCHOR)['status'], 'ready')

    def test_pending_never_starts_a_lazy_bag_worker_and_wal_hides_uncommitted_rows(self):
        register_owner(self.data, self.member, self.owner)
        with patch('ra_triage_dashboard.app.planning_constraints.threading.Thread') as worker:
            from ra_triage_dashboard.app.planning_constraints import read_window
            self.assertEqual(read_window(self.data, 'cn1234', 'trip-unit', ANCHOR, 0)['status'], 'pending')
            worker.assert_not_called()
        with sqlite3.connect(index_path(self.data)) as db:
            db.execute("UPDATE captures SET state='failed'")
            self.assertEqual(read_daily_window(self.data, 'cn1234', 0)['status'], 'pending')
            db.rollback()
        self.assertEqual(index_path(self.data).stat().st_mode & 0o777, 0o600)

    def test_damage_is_closed_and_foreign_schema_is_never_stamped(self):
        path = index_path(self.data)
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE foreign_schema(value TEXT)')
        with self.assertRaises(ValueError):
            register_owner(self.data, self.member, self.owner)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0], 0)
        self.assertEqual(read_daily_window(self.data, 'cn1234', 0)['reason'], 'index_unavailable')

    def test_archive_validation_rebuilds_coverage_and_checks_all_bytes(self):
        self.publish()
        result, _, _ = load_artifact(self.artifact, self.member)
        self.assertEqual(result['capture_key'], identity(self.member))
        with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
            load_artifact(self.artifact, {**self.member, 'anchor_ms': ANCHOR+1})
        (self.artifact/'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'sha_mismatch'):
            load_artifact(self.artifact)

    def test_same_native_time_conflicts_and_signed_int64_limits_are_rejected(self):
        first, second = observation(0), observation(0)
        self.assertEqual(build_result(self.member, [first, second])['frame_count'], 1)
        second['raw_sha256'] = 'c'*64
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            build_result(self.member, [first, second])
        with self.assertRaises(ValueError):
            identity({**self.member, 'anchor_ms': 9223372036855})

    def test_cohort_counts_only_exact_identity_and_published_real_frames(self):
        self.publish()
        targets = {'cn1234': dict(trip_id='trip-unit', ra_start_timestamp=ANCHOR),
                   'cn5678': dict(trip_id='trip-other', ra_start_timestamp=ANCHOR)}
        value = cohort_counts(self.data, targets)
        self.assertEqual((value['selected'], value['with_frames'], value['partial_source'], value['unknown']), (2, 1, 1, 1))
        targets['cn1234']['trip_id'] = 'different'
        self.assertEqual(cohort_counts(self.data, targets)['with_frames'], 0)

    def test_native_owner_transfer_requires_proven_terminal_absence_and_preserves_receipts(self):
        register_owner(self.data, self.member, self.owner, context=dict(run='first'))
        evidence = dict(kind='native_terminal_no_object', job_id=11, task_id=1100000000,
                        job_state=2, task_status=4, missing_confirmed=True)
        with self.assertRaisesRegex(ValueError, 'requires_native_evidence'):
            transfer_owner(self.data, self.member, self.owner, 'next', {}, dict(evidence, missing_confirmed=False))
        self.assertEqual(capture_owner(self.data, self.member)['owner'], self.owner)
        self.assertTrue(transfer_owner(self.data, self.member, self.owner, 'next', dict(run='retry'), evidence))
        self.assertFalse(transfer_owner(self.data, self.member, self.owner, 'other', {}, evidence))
        write_artifact(self.artifact, self.member, [observation(0)], self.producer)
        import_artifact(self.data, self.artifact, self.member, 'next')
        self.assertFalse(transfer_owner(self.data, self.member, 'next', 'third', {}, evidence))
        with sqlite3.connect(index_path(self.data)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM owner_events').fetchone()[0], 1)

    def test_import_never_supersedes_an_exact_authoritative_history_window(self):
        write_artifact(self.artifact, self.member, [observation(0)], self.producer)
        register_owner(self.data, self.member, self.owner)
        with patch('ra_triage_dashboard.app.planning_constraint_index._read_history_window', return_value=dict(status='ready')):
            with self.assertRaisesRegex(ValueError, 'history_already_authoritative'):
                import_artifact(self.data, self.artifact, self.member, self.owner)
        self.assertEqual(read_daily_window(self.data, self.member['issue_id'], 0)['status'], 'pending')
