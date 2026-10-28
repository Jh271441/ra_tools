import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as N
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ra_triage_dashboard.app.planning_constraint_extract import extract_frame
from ra_triage_dashboard.app import planning_constraints as service


def fixture():
    search = N(dominant_constraint_ix=0, dominant_constraint_obj_id=0,
               earliest_brake_time_ix=-1, search_result='FAIL',
               constraints=[N(unique_constraint_id='search-id')])
    speed = N(primitive_constraints=[N(unique_constraint_id='tl-30004052-lane-75940685-RED-soft')],
              speed_solver_debugs=[N(search_debug=search)])
    meta = N(is_selected=True, label='candidate-0', speed_ix=0)
    maneuver = N(type='DECOUPLED_LANE_FOLLOW', trajectory_selection_debug=N(trajectory_meta_debugs=[meta]),
                 single_lane_sequence_plan_debug=[N(single_intention_plan_debug=[N(candidate_identifier='candidate-1', speed_generator_debug=speed)])])
    return N(timestamp=900, behavior_reasoner_debug=N(decoupled_maneuvers=[maneuver])), search, speed, meta, maneuver


class PlanningFactsTest(unittest.TestCase):
    def setUp(self):
        service._stopping = False

    def tearDown(self):
        service._active.clear()
        service._failures.clear()

    def test_exact_raw_traffic_light_zero_and_negative_brake(self):
        message, *_ = fixture()
        row = extract_frame(message, 1000)
        self.assertEqual(row['raw'], 'Non gap align. Dominant constraint: tl-30004052-lane-75940685-RED-soft, Object id: 0. Earliest search brake time ix: -1')
        self.assertEqual(row['object_id'], 0)
        self.assertEqual(row['timestamp_ms'], 1000)
        self.assertEqual(row['planning_timestamp_ms'], 900)

    def test_search_fallback_and_gap(self):
        message, search, speed, *_ = fixture()
        speed.primitive_constraints = []
        search.search_result = 'SUCCESS_WITH_GAP_ALIGN'
        self.assertEqual(extract_frame(message, 1)['constraint_id'], 'search-id')
        self.assertTrue(extract_frame(message, 1)['raw'].startswith('Gap align.'))

    def test_missing_ambiguous_candidate_or_solver_fail_closed(self):
        message, search, speed, meta, maneuver = fixture()
        meta.is_selected = False
        self.assertEqual(extract_frame(message, 1)['status'], 'unresolved')
        meta.is_selected = True
        meta.speed_ix = 5
        self.assertEqual(extract_frame(message, 1)['status'], 'unresolved')
        meta.speed_ix = 0
        maneuver.trajectory_selection_debug.trajectory_meta_debugs.append(meta)
        self.assertEqual(extract_frame(message, 1)['status'], 'unresolved')

    def test_no_constraint_and_unresolved_not_stale(self):
        message, search, speed, *_ = fixture()
        for ix in [-1, 3]:
            search.dominant_constraint_ix = ix
            result = extract_frame(message, 1)
            self.assertEqual(result['status'], 'no_constraint')
            self.assertIsNone(result['constraint_id'])
            self.assertIn('No dominant constraint.', result['raw'])
        search.dominant_constraint_ix = 0
        speed.primitive_constraints[0].unique_constraint_id = ''
        self.assertEqual(extract_frame(message, 1)['status'], 'unresolved')

    def test_cache_identity_bucket_bounds_singleflight_and_backoff(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(service.threading, 'Thread') as thread:
            root = Path(temp)
            with patch.object(service.shutil, 'disk_usage', return_value=N(free=5 * 1024**3)):
                first = service.read_window(root, 'cn1', 'trip1', 100000, -1)
                self.assertEqual(first['bucket'], -1)
                self.assertEqual(first['window_start_ms'], 91800)
                self.assertEqual(first['window_end_ms'], 100200)
                self.assertEqual(service.read_window(root, 'cn1', 'trip1', 100000, -2)['status'], 'loading')
                self.assertEqual(service.read_window(root, 'cn2', 'trip1', 100000, -1)['status'], 'busy')
                thread.assert_called_once()
                key = next(iter(service._active))
                service._active.clear()
                (root/'planning_constraints'/f'{key}.json').write_text(json.dumps({'key':key,'frames':[]}))
                self.assertEqual(service.read_window(root, 'cn1', 'trip1', 100000, -1)['status'], 'ready')
                service._failures[key] = service.time.monotonic()
                (root/'planning_constraints'/f'{key}.json').unlink()
                self.assertEqual(service.read_window(root, 'cn1', 'trip1', 100000, -1)['status'], 'error')

    def test_invalid_trip_and_low_disk_never_start_worker(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(service.threading, 'Thread') as thread:
            self.assertEqual(service.read_window(Path(temp), 'cn1', '../x', 1000, 0)['status'], 'unavailable')
            with patch.object(service.shutil, 'disk_usage', return_value=N(free=0)):
                self.assertEqual(service.read_window(Path(temp), 'cn1', 'trip1', 1000, 0)['status'], 'unavailable')
            thread.assert_not_called()

    def test_timeout_kills_before_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            process = MagicMock()
            process.communicate.side_effect = service.subprocess.TimeoutExpired('worker', 120)
            process.poll.return_value = None
            with patch.object(service.subprocess, 'Popen', return_value=process), patch.object(service.os, 'killpg') as kill:
                service._extract(Path(temp), Path(temp)/'dest.json', 'key', 'trip1', 1, 2)
                kill.assert_called_once()
                process.wait.assert_called_once()
                self.assertEqual(list(Path(temp).glob('window-*')), [])
                self.assertIn('key', service._failures)


if __name__ == '__main__':
    unittest.main()
