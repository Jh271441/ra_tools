import json
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.assets import VideoIndex


class VideoIndexTest(unittest.TestCase):
    def _write_capture(
        self,
        root: Path,
        *,
        issue_id: str = "cn31842459",
        relative_path: str = "videos/video_only.mp4",
    ) -> tuple[Path, Path]:
        capture = root / "shard-006-of-008" / f"{issue_id}_1778504337849"
        video = capture / "videos" / "video_only.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"not-a-real-video")
        metadata = {
            "status": "captured",
            "issue_id": issue_id,
            "capture_plan": {
                "variants": [
                    {
                        "video_relative_path": relative_path,
                        "video_start_offset_sec": -20,
                        "video_duration_ms": 40000,
                        "video_frame_step_ms": 100,
                        "video_capture_mode": "frame_seek",
                        "video_size": {"width": 2560, "height": 1440},
                    }
                ]
            },
            "render_metadata": {
                "videos": [
                    {
                        "relative_path": relative_path,
                        "visible_duration_ms": 40000,
                        "frame_step_ms": 100,
                        "frame_count": 400,
                        "capture_mode": "frame_seek",
                    }
                ]
            },
        }
        meta_path = capture / "meta.json"
        meta_path.write_text(json.dumps(metadata), encoding="utf-8")
        return meta_path, video

    def test_resolves_root_confined_video_and_timeline_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, video_path = self._write_capture(root)
            index = VideoIndex(root)

            video = index.get_video("cn31842459")

            self.assertIsNotNone(video)
            self.assertEqual(video["url"], "/api/assets/cn31842459/bev-video-0")
            self.assertEqual(video["duration_ms"], 40000)
            self.assertEqual(video["start_offset_sec"], -20)
            self.assertEqual(video["event_time_sec"], 20)
            self.assertEqual(video["frame_step_ms"], 100)
            self.assertEqual(video["frame_count"], 400)
            self.assertEqual(
                index.get_asset_path("cn31842459", "bev-video-0"),
                video_path.resolve(),
            )

    def test_rejects_path_escape_and_invalid_issue_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "videos"
            root.mkdir()
            outside = Path(directory) / "outside.mp4"
            outside.write_bytes(b"outside")
            self._write_capture(root, relative_path="../../../outside.mp4")
            index = VideoIndex(root)

            self.assertIsNone(index.get_video("cn31842459"))
            self.assertIsNone(index.get_video("../cn31842459"))
            self.assertIsNone(
                index.get_asset_path("cn31842459", "bev-video-0")
            )

    def test_public_video_url_uses_configured_base_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_capture(root)
            index = VideoIndex(root, base_path="/dashboard")

            video = index.get_video("cn31842459")

            self.assertIsNotNone(video)
            self.assertEqual(
                video["url"],
                "/dashboard/api/assets/cn31842459/bev-video-0",
            )


if __name__ == "__main__":
    unittest.main()
