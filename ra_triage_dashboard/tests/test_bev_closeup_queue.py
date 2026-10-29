"""Recovery/identity contracts for the independent closeup media queue."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts/bev_closeup"
sys.path.insert(0, str(SCRIPTS))
from contract import verify_metadata
from coordinator import connect, enqueue, key, pilot
from recovery import live_owned, recover
from unittest.mock import patch


def source(iid="cn100", version="1009", **extra):
    return dict(issue_id=iid, version=version, state="published", source_status="ready",
                trip_id="10370_20261015_153350", capture_timestamp_ms=1792050235800,
                anchor_source="version_registry_event", scopes=["scope"], **extra)


class CloseupQueueTest(unittest.TestCase):
    def test_process_identity_rejects_pid_reuse_and_detects_orphan_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / 'proc/1234'
            proc.mkdir(parents=True)
            fields = ['S'] + ['0'] * 19
            fields[19] = '88'
            (proc / 'stat').write_text('1234 (worker) ' + ' '.join(fields))
            (proc / 'cmdline').write_bytes(b'chromium\0--fixture\0')
            self.assertEqual(live_owned(root, [dict(pid=1234, start_ticks=77)], root / 'proc'), [])
            self.assertEqual(live_owned(root, [dict(pid=1234, start_ticks=88)], root / 'proc')[0]['pid'], 1234)
            fields[0] = 'Z'
            (proc / 'stat').write_text('1234 (worker) ' + ' '.join(fields))
            self.assertEqual(live_owned(root, [dict(pid=1234, start_ticks=88)], root / 'proc'), [])

    def test_recovery_respects_worker_lock_and_live_owned_children(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = connect(root)
            with (root / 'worker.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    recover(root, root / 'published', apply=True)
            with patch('recovery.live_owned', return_value=[dict(pid=999, start_ticks=1)]):
                with self.assertRaisesRegex(RuntimeError, 'owned_process_still_live'):
                    recover(root, root / 'published', apply=True)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_interrupted_recovery_reuses_valid_output_before_retrying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = connect(root)
            enqueue(db, dict(members=[source()], membership_sha256='sha'), True)
            batch = root / 'batches/first'
            batch.mkdir(parents=True)
            (batch / 'process.json').write_text(json.dumps(dict(pid=999, start_ticks=1, children=[])))
            db.execute("UPDATE jobs SET state='running',attempts=1,batch=?", (str(batch),))
            db.commit()
            with patch('recovery.live_owned', return_value=[]), patch('recovery.verify_case', return_value=(Path('video.mp4'), dict(sha256='verified-sha'))) as verify, patch('recovery.publish') as publish:
                self.assertEqual(recover(root, root / 'published')['claims'][0]['action'], 'verify_existing_then_retry_if_incomplete')
                verify.assert_not_called()
                result = recover(root, root / 'published', apply=True)
                self.assertEqual(result['claims'][0]['action'], 'verified_existing')
                publish.assert_called_once()
            self.assertEqual(db.execute('SELECT state FROM jobs').fetchone()[0], 'verified')

    def test_complete_membership_preserves_excluded_and_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(tmp)
            rows = [source("cn100"), source("cn101"), source("cn102")]
            rows[1]["state"] = "excluded"
            rows[2].update(state="waiting_metadata", source_status="missing_anchor")
            snapshot = dict(members=rows, membership_sha256="sha")
            enqueue(db, snapshot, True)
            enqueue(db, snapshot, True)
            self.assertEqual(db.execute("SELECT count(*) FROM members").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            rows[2].update(state="published", source_status="ready")
            enqueue(db, snapshot, False)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 2)

    def test_anchor_change_never_silently_enqueues_second_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(tmp)
            row = source()
            enqueue(db, dict(members=[row], membership_sha256="sha"), True)
            row["capture_timestamp_ms"] += 100
            enqueue(db, dict(members=[row], membership_sha256="sha"), False)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='anchor_conflict'").fetchone()[0], 1)

    def test_pilot_is_ten_per_version_not_target_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(tmp)
            rows = [source(f"cn{v}{i:03}", v) for v in ("0821", "1009", "1016") for i in range(15)]
            enqueue(db, dict(members=rows, membership_sha256="sha"), True)
            pilot(db)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 45)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE pilot=1").fetchone()[0], 30)
            pilot(db)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE pilot=1").fetchone()[0], 30)

    def test_actual_time_or_paused_state_drift_fails_metadata_gate(self):
        row = source()
        # Construct the valid 400-frame timing evidence independently of the
        # renderer, then corrupt one actual timestamp/state at the boundary.
        import contract
        a = row["capture_timestamp_ms"]
        video = dict(capture_mode="frame_seek", requested_start_ms=a-20000, requested_end_ms=a+20000,
                     effective_start_ms=a-20000, frame_step_ms=100, frame_count=400, visible_duration_ms=40000,
                     seek_commit_check="blurred_actual_current_time_and_paused_before_screenshot",
                     frame_observations=[dict(target_ms=a-20000+n*100, actual_ms=a-20000+n*100, paused=True, editing=False) for n in range(400)],
                     timeline_loading_gate="hidden_before_every_frame", per_frame_scene_gate="canvas_present_and_no_missing_scene_message",
                     source_context=dict(padding_ms=1000, start_ms=a-21000, end_ms=a+21000, frame_timestamps_unchanged=True),
                     view_override=dict(visual_distance=30, ego_target_offset_m=[4,0,0], bev_only=True, persisted_to_cloud=False,
                                        original_layout_sha256=contract.ORIGINAL_SHA, rendered_layout_sha256=contract.RENDERED_SHA))
        meta = dict(status="captured", issue_id=row["issue_id"], trip_id=row["trip_id"], source_row=row,
                    timestamp_source="capture_timestamp_ms", request_timestamp_ms=a, render_metadata=dict(videos=[video]))
        verify_metadata(meta, row)
        video["frame_observations"][-1]["actual_ms"] -= 100
        with self.assertRaisesRegex(ValueError, "frame_time_mismatch"):
            verify_metadata(meta, row)
        video["frame_observations"][-1].update(actual_ms=a+19900, editing=True)
        with self.assertRaisesRegex(ValueError, "frame_time_mismatch"):
            verify_metadata(meta, row)


if __name__ == "__main__":
    unittest.main()
