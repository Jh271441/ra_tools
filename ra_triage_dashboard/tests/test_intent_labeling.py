from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.shared import IntentAnnotationConflictError
from ra_triage_dashboard.app.intent_dataset_registry import IntentDatasetIndex
from ra_triage_dashboard.app.intent_experiments import build_intent_experiment_assignments


class IntentDatasetIndexTest(unittest.TestCase):
    def test_repository_registry_declares_four_exact_dataset_partitions(self) -> None:
        registry = json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "intent_datasets.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [(item["display_name"], item["expected_case_count"]) for item in registry["datasets"]],
            [
                ("0206 · 1335", 1335),
                ("0508 · 1071", 1071),
                ("0522 · 100", 100),
                ("0626 · 300", 300),
            ],
        )
        self.assertTrue(
            all(item["membership_format"] == "source-rows-json-v1" for item in registry["datasets"])
        )

    def test_source_rows_membership_is_release_and_sha_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bev_root = root / "bev"
            case_id = "cn12345_1770000000000"
            (bev_root / case_id).mkdir(parents=True)
            membership = bev_root / "source_rows.json"
            membership.write_text(
                json.dumps([
                    {
                        "issue_id": "cn12345",
                        "capture_timestamp_ms": 1770000000000,
                        "dataset_release": "0206",
                    }
                ]),
                encoding="utf-8",
            )
            import hashlib
            digest = hashlib.sha256(membership.read_bytes()).hexdigest()
            config = root / "intent.json"
            config.write_text(json.dumps({"datasets": [{
                "id": "0206-1-v1",
                "scene_set": "0206",
                "expected_case_count": 1,
                "bev_root": str(bev_root),
                "membership_file": membership.name,
                "membership_format": "source-rows-json-v1",
                "membership_file_sha256": digest,
            }]}), encoding="utf-8")
            index = IntentDatasetIndex.from_file(config)
            index.refresh()
            self.assertEqual(index.case_ids("0206-1-v1"), (case_id,))
            self.assertTrue(index.public_datasets()[0]["available"])
            membership.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                index.refresh()

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

    def test_annotators_have_independent_heads_and_shared_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.sqlite3")
            database.init()
            case_id = "cn12345_1770000000000"
            alice = database.save_intent_labels(
                dataset_id="0206-1335-v1",
                case_id=case_id,
                routing_default="left_turn",
                lane_change_default="no_lane_change",
                overrides=[],
                expected_revision_id=None,
                author="Alice",
            )
            bob = database.save_intent_labels(
                dataset_id="0206-1335-v1",
                case_id=case_id,
                routing_default="right_turn",
                lane_change_default="lane_change",
                overrides=[],
                expected_revision_id=None,
                author="Bob",
            )
            self.assertEqual(
                database.get_intent_labels("0206-1335-v1", case_id, "alice")["revision_id"],
                alice["revision_id"],
            )
            self.assertEqual(
                database.get_intent_labels("0206-1335-v1", case_id, "bob")["revision_id"],
                bob["revision_id"],
            )
            contributors = database.list_intent_contributors("0206-1335-v1", case_id)
            self.assertEqual([item["username"] for item in contributors], ["alice", "bob"])
            comment = database.create_intent_comment(
                dataset_id="0206-1335-v1",
                case_id=case_id,
                body="需要确认掉头口径",
                author="Alice",
                author_source="sso",
                author_verified=True,
            )
            self.assertEqual(comment["author"], "alice")
            self.assertEqual(
                database.list_intent_comments("0206-1335-v1", case_id)[0]["body"],
                "需要确认掉头口径",
            )


class IntentExperimentTest(unittest.TestCase):
    def test_blind_assignment_is_balanced_and_overlap_is_independent(self) -> None:
        cases = [f"cn12345_{index}" for index in range(10)]
        assignments = build_intent_experiment_assignments(
            cases, ["alice", "bob", "charlie"], "blind", 0.3, 42
        )
        base = [item for item in assignments if item["assignment_kind"] == "base"]
        cross = [item for item in assignments if item["assignment_kind"] == "cross"]
        self.assertEqual(len(base), 10)
        self.assertEqual(len(cross), 3)
        base_owner = {item["case_id"]: item["username"] for item in base}
        self.assertTrue(all(base_owner[item["case_id"]] != item["username"] for item in cross))
        base_counts = {
            member: sum(item["username"] == member for item in base)
            for member in ("alice", "bob", "charlie")
        }
        self.assertLessEqual(max(base_counts.values()) - min(base_counts.values()), 1)

    def test_blind_assignment_supports_three_reviewers_per_overlap_case(self) -> None:
        cases = [f"cn12345_{index}" for index in range(10)]
        assignments = build_intent_experiment_assignments(
            cases, ["alice", "bob", "charlie", "dora"], "blind", 0.4, 42, 3
        )
        by_case: dict[str, list[dict[str, object]]] = {}
        for assignment in assignments:
            by_case.setdefault(str(assignment["case_id"]), []).append(assignment)
        three_reviewer_cases = [items for items in by_case.values() if len(items) == 3]
        self.assertEqual(len(three_reviewer_cases), 4)
        self.assertTrue(
            all(len({str(item["username"]) for item in items}) == 3 for items in three_reviewer_cases)
        )

    def test_full_assignment_and_storage_snapshot(self) -> None:
        cases = ["cn1_1", "cn2_2"]
        assignments = build_intent_experiment_assignments(cases, ["alice", "bob"], "full", 1, 7)
        self.assertEqual(len(assignments), 4)
        self.assertTrue(all(item["assignment_kind"] == "full" for item in assignments))
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.sqlite3")
            database.init()
            experiment = database.create_intent_experiment(
                experiment_id="experiment-1",
                dataset_id="test-v1",
                name="双盲一轮",
                annotation_mode="full",
                overlap_ratio=1,
                case_count=2,
                seed=7,
                assignments=assignments,
                created_by="admin",
                created_by_source="test",
                created_by_verified=True,
            )
            self.assertEqual(experiment["member_count"], 2)
            self.assertEqual(experiment["assignment_count"], 4)
            self.assertEqual(experiment["overlap_reviewers"], 2)
            self.assertEqual({item["total"] for item in experiment["members"]}, {2})
            closed = database.close_intent_experiment("experiment-1", closed_by="admin")
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(closed["assignment_count"], 4)

    def test_active_assignment_owner_filter_uses_same_experiment_intersection(self) -> None:
        assignments = [
            {"case_id": "cn1_1", "username": "alice", "assignment_kind": "base", "ordinal": 1},
            {"case_id": "cn2_2", "username": "alice", "assignment_kind": "base", "ordinal": 2},
            {"case_id": "cn1_1", "username": "bob", "assignment_kind": "cross", "ordinal": 1},
            {"case_id": "cn3_3", "username": "bob", "assignment_kind": "base", "ordinal": 2},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "test.sqlite3")
            database.init()
            database.create_intent_experiment(
                experiment_id="experiment-filter",
                dataset_id="test-v1",
                name="交叉筛选",
                annotation_mode="blind",
                overlap_ratio=0.5,
                case_count=3,
                seed=9,
                assignments=assignments,
                created_by="admin",
                created_by_source="test",
                created_by_verified=True,
            )
            owners = database.list_intent_assignment_assignees("test-v1")
            self.assertEqual(
                [(item["username"], item["case_count"]) for item in owners],
                [("alice", 2), ("bob", 2)],
            )
            self.assertEqual(
                database.intent_assigned_case_ids("test-v1", ["alice"]),
                ("cn1_1", "cn2_2"),
            )
            self.assertEqual(
                database.intent_assigned_case_ids("test-v1", ["alice", "bob"]),
                ("cn1_1",),
            )
            database.close_intent_experiment("experiment-filter", closed_by="admin")
            self.assertEqual(database.list_intent_assignment_assignees("test-v1"), [])
            self.assertEqual(database.intent_assigned_case_ids("test-v1", ["alice"]), ())


if __name__ == "__main__":
    unittest.main()
