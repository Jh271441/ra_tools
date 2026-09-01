from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.shared import IntentAnnotationConflictError
from ra_triage_dashboard.app.intent_dataset_registry import IntentDatasetIndex


class IntentDatasetIndexTest(unittest.TestCase):
    def test_membership_file_cannot_escape_bev_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bev_root = root / "bev"
            bev_root.mkdir()
            config = root / "intent.json"
            config.write_text(
                json.dumps(
                    {
                        "datasets": [
                            {
                                "id": "test-v1",
                                "bev_root": str(bev_root),
                                "membership_file": "../outside.txt",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "membership_file"):
                IntentDatasetIndex.from_file(config)

    def test_arbitrary_timepoints_pair_camera_by_explicit_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bev_root = root / "bev"
            camera_root = root / "camera"
            case_id = "cn12345_1770000000000"
            frames = bev_root / case_id / "frames"
            frames.mkdir(parents=True)
            for offset in (-2000, -1000, 0, 1000, 2000):
                sign = "+" if offset >= 0 else "-"
                (frames / f"bev_default_t{sign}{abs(offset):05d}ms.png").write_bytes(b"bev")
            camera = camera_root / case_id / "after_compress"
            camera.mkdir(parents=True)
            for index in range(3):
                (camera / f"{index}.jpg").write_bytes(b"camera")
            (bev_root / "membership.txt").write_text(
                f"deadbeef  {case_id}/frames/bev_default_t+00000ms.png\n",
                encoding="utf-8",
            )
            config = root / "intent.json"
            config.write_text(
                json.dumps(
                    {
                        "datasets": [
                            {
                                "id": "test-v1",
                                "display_name": "Test",
                                "expected_case_count": 1,
                                "bev_root": str(bev_root),
                                "camera_root": str(camera_root),
                                "membership_file": "membership.txt",
                                "camera_offsets_ms": [-2000, 0, 2000],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            index = IntentDatasetIndex.from_file(config, base_path="/manual")
            index.refresh()
            timeline = index.timeline("test-v1", case_id)
            self.assertEqual([item["offset_ms"] for item in timeline], [-2000, -1000, 0, 1000, 2000])
            self.assertIsNotNone(timeline[0]["camera"])
            self.assertIsNone(timeline[1]["camera"])
            self.assertIn("/manual/api/intent-datasets/", timeline[2]["bev"]["url"])
            path, media_type = index.resolve_asset("test-v1", case_id, "camera_+0")
            self.assertEqual(path.name, "1.jpg")
            self.assertEqual(media_type, "image/jpeg")

    def test_camera41_manifest_uses_exact_episode_offsets_and_confined_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bev_root = root / "bev"
            camera_root = root / "camera41"
            case_id = "cn12345_1770000000000"
            frames = bev_root / case_id / "frames"
            frames.mkdir(parents=True)
            (frames / "bev_default_t-01000ms.png").write_bytes(b"bev")
            (bev_root / "membership.txt").write_text(
                f"deadbeef  {case_id}/frames/bev_default_t-01000ms.png\n",
                encoding="utf-8",
            )
            copied = camera_root / "frames" / case_id
            copied.mkdir(parents=True)
            (copied / "camera_t-1000ms.jpg").write_bytes(b"camera")
            (copied / "camera_t+0ms.jpg").write_bytes(b"camera")
            manifest = root / "camera41.jsonl"
            manifest.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "schema": "routing_camera41_frame_asset_v1",
                            "episode": case_id,
                            "frame_offset_ms": offset,
                            "selection_diff_ms": delta,
                            # The deployed copy never trusts or serves this source path.
                            "image_path": f"/unmounted/source/frame_{index:03d}.jpg",
                        }
                    )
                    for index, (offset, delta) in enumerate(((-1000, 42), (0, -17)))
                )
                + "\n",
                encoding="utf-8",
            )
            config = root / "intent.json"
            config.write_text(
                json.dumps(
                    {
                        "datasets": [
                            {
                                "id": "test-v1",
                                "bev_root": str(bev_root),
                                "camera_root": str(camera_root),
                                "camera_manifest": str(manifest),
                                "camera_manifest_frame_subdir": "frames",
                                "membership_file": "membership.txt",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            index = IntentDatasetIndex.from_file(config)
            index.refresh()
            timeline = index.timeline("test-v1", case_id)
            self.assertEqual([item["offset_ms"] for item in timeline], [-1000, 0])
            self.assertEqual([item["camera_delta_ms"] for item in timeline], [42, -17])
            self.assertEqual(index.public_datasets()[0]["camera_frame_count"], 2)
            path, media_type = index.resolve_asset("test-v1", case_id, "camera_-1000")
            self.assertEqual(path, (copied / "camera_t-1000ms.jpg").resolve())
            self.assertEqual(media_type, "image/jpeg")


class IntentLabelStorageTest(unittest.TestCase):
    def test_case_defaults_sparse_override_and_optimistic_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.sqlite3")
            database.init()
            first = database.save_intent_labels(
                dataset_id="test-v1",
                case_id="cn12345_1770000000000",
                routing_default="straight",
                lane_change_default="no_lane_change",
                overrides=[
                    {
                        "timepoint_id": "t:+1000",
                        "offset_ms": 1000,
                        "routing_intent": "left_turn",
                        "lane_change_intent": "no_lane_change",
                    }
                ],
                expected_revision_id=None,
                author="tester",
            )
            self.assertEqual(first["routing_default"], "straight")
            self.assertEqual(first["overrides"], [
                {
                    "timepoint_id": "t:+1000",
                    "offset_ms": 1000,
                    "routing_intent": "left_turn",
                    "lane_change_intent": "",
                }
            ])
            restored = database.get_intent_labels("test-v1", "cn12345_1770000000000")
            self.assertEqual(restored, first)
            second = database.save_intent_labels(
                dataset_id="test-v1",
                case_id="cn12345_1770000000000",
                routing_default="right_turn",
                lane_change_default="no_lane_change",
                overrides=first["overrides"],
                expected_revision_id=first["revision_id"],
                author="tester",
            )
            self.assertGreater(second["revision_id"], first["revision_id"])
            self.assertEqual(second["overrides"][0]["routing_intent"], "left_turn")
            with self.assertRaises(IntentAnnotationConflictError):
                database.save_intent_labels(
                    dataset_id="test-v1",
                    case_id="cn12345_1770000000000",
                    routing_default="parking",
                    lane_change_default="lane_change",
                    overrides=[],
                    expected_revision_id=first["revision_id"],
                    author="stale",
                )


if __name__ == "__main__":
    unittest.main()
