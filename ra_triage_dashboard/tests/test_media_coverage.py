"""Coverage must describe dataset members, independently of shared roots."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.assets import AssetIndex, CameraIndex, VideoIndex
from ra_triage_dashboard.app.media_registry import MediaRegistry, ProductLayoutProvider


class MediaCoverageTest(unittest.TestCase):
    def camera(self, root, issue, stamp="100", frames=9):
        folder = root / f"{issue}_{stamp}" / "after_compress"
        folder.mkdir(parents=True)
        for i in range(frames):
            (folder / f"{i}.jpg").write_bytes(b"frame")

    def video(self, root, issue, layout="flat", exists=True):
        folder = {"flat": root / f"{issue}_100", "shard": root / "shard-001-of-002" / f"{issue}_100",
                  "issues": root / "issues" / issue, "timestamped": root / "issues" / f"{issue}_100"}[layout]
        folder.mkdir(parents=True)
        if exists:
            (folder / "clip.mp4").write_bytes(b"video")
        (folder / "meta.json").write_text(json.dumps({"issue_id": issue, "status": "captured", "capture_plan": {
            "variants": [{"video_relative_path": "clip.mp4", "video_duration_ms": 40000}]}}))
        return folder

    def test_member_intersection_and_independent_media_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            camera, video = root / "camera", root / "video"
            for issue in ("cn1", "cn999"):
                self.camera(camera, issue)
                self.video(video, issue)
            self.camera(camera, "cn2", frames=8)
            self.video(video, "cn2", exists=False)
            self.camera(camera, "cn1", stamp="200")
            manifest = root / "manifest.jsonl"
            manifest.write_text("\n".join(json.dumps({"issue_id": i, "meta_path": f"issues/{i}/meta.json"}) for i in ("cn1", "cn2", "cn999")))
            provider = ProductLayoutProvider(asset_index=AssetIndex(ra_root=root, manifest_path=manifest),
                camera_index=CameraIndex(camera), video_index=VideoIndex(video))
            registry = MediaRegistry(by_id={"scope": provider}, by_scope={"dataset": provider})
            registry.set_memberships({"scope": frozenset({"cn1", "cn2"})})
            summary = registry.media_ready_by_id()["scope"]
            self.assertEqual(summary["bev_indexed_issues"], 2)
            self.assertEqual(summary["video_indexed_issues"], 1)
            self.assertEqual(summary["camera_indexed_issues"], 1)
            registry.set_memberships({"scope": frozenset()})
            self.assertEqual(registry.media_ready_by_id()["scope"]["camera_indexed_issues"], 0)

    def test_video_layouts_missing_files_invalid_metadata_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for issue, layout in (("cn1", "flat"), ("cn2", "shard"), ("cn3", "issues"), ("cn4", "timestamped")):
                self.video(root, issue, layout)
            bad = self.video(root, "cn5")
            (bad / "meta.json").write_text("[]")
            self.video(root, "cn6", exists=False)
            mismatch = self.video(root, "cn7")
            payload = json.loads((mismatch / "meta.json").read_text())
            payload["issue_id"] = "cn8"
            (mismatch / "meta.json").write_text(json.dumps(payload))
            index = VideoIndex(root)
            with patch.object(index, "_scan_issue_ids", wraps=index._scan_issue_ids) as scan:
                self.assertEqual(index.indexed_issue_ids(), frozenset({"cn1", "cn2", "cn3", "cn4"}))
                self.assertEqual(index.indexed_issue_ids(), index.indexed_issue_ids())
                self.assertEqual(scan.call_count, 1)

    def test_outside_root_media_cannot_count_as_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video, camera, outside = root / "video", root / "camera", root / "outside"
            video.mkdir(); camera.mkdir()
            folder = self.video(outside, "cn1")
            (video / folder.name).symlink_to(folder, target_is_directory=True)
            self.camera(outside / "camera", "cn1")
            (camera / "cn1_100").symlink_to(outside / "camera/cn1_100", target_is_directory=True)
            self.assertEqual(VideoIndex(video).indexed_issue_ids(), frozenset())
            self.assertEqual(CameraIndex(camera).indexed_issue_ids(), frozenset())

    def test_nonblocking_snapshot_coalesces_reads_and_discards_old_membership(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        class Provider:
            def media_ready_summary(self, members):
                calls.append(members)
                if members == frozenset({"cn1"}):
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError("test barrier timed out")
                return {"camera_indexed_issues": len(members)}
        registry = MediaRegistry(by_id={"scope": Provider()}, by_scope={})
        registry.set_memberships({"scope": frozenset({"cn1"})})
        first = registry.media_status_by_id()["scope"]
        self.assertEqual(first["coverage_status"], "pending")
        self.assertNotIn("camera_indexed_issues", first)
        self.assertTrue(entered.wait(3))
        old = registry._status_thread
        self.assertEqual(registry.media_status_by_id()["scope"]["coverage_status"], "pending")
        self.assertEqual(len(calls), 1)
        registry.set_memberships({"scope": frozenset({"cn1", "cn2"})})
        registry.media_status_by_id()
        current = registry._status_thread
        release.set()
        old.join(3); current.join(3)
        self.assertFalse(current.is_alive())
        result = registry.media_status_by_id()["scope"]
        self.assertEqual(result["coverage_status"], "ready")
        self.assertEqual(result["camera_indexed_issues"], 2)
        registry.set_memberships({"scope": frozenset({"cn1", "cn2", "cn3"})})
        registry.media_status_by_id()
        registry._status_thread.join(3)
        self.assertEqual(registry.media_status_by_id()["scope"]["camera_indexed_issues"], 3)

    def test_background_failure_is_unknown_and_retries_are_backed_off(self):
        calls = []
        class Provider:
            def media_ready_summary(self, members):
                calls.append(members)
                raise OSError("unavailable")
        registry = MediaRegistry(by_id={"scope": Provider()}, by_scope={})
        registry.media_status_by_id()
        registry._status_thread.join(3)
        result = registry.media_status_by_id()["scope"]
        self.assertEqual(result["coverage_status"], "error")
        self.assertNotIn("camera_indexed_issues", result)
        self.assertEqual(len(calls), 1)
