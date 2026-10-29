import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from ra_triage_dashboard.app.closeup_video import CloseupVideoIndex, WithCloseupVideo


class CloseupVideoTest(unittest.TestCase):
    def fixture(self, tmp):
        root = Path(tmp)
        (root / "objects").mkdir()
        (root / "objects/video.mp4").write_bytes(b"video")
        (root / "objects/poster.jpg").write_bytes(b"poster")
        receipt = dict(issue_id="cn123", status="verified", source_id="bev_closeup", recipe_id="ego30-forward4-1080p-10fps-v1",
                       scopes=["version_scope"], duration_ms=40000, frame_count=400, frame_step_ms=100, event_time_sec=20,
                       full_decode_passed=True, time_observations_verified=True, anchor_ms=1792050235800, trip_id="trip1",
                       video_path="objects/video.mp4", poster_path="objects/poster.jpg")
        path = root / "issues/cn123/receipt.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(receipt))
        return root, path, receipt

    def test_scope_and_root_confinement_and_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, path, receipt = self.fixture(tmp)
            index = CloseupVideoIndex(root, "/manual")
            self.assertEqual(index.descriptor("cn123", "version_scope")["url"], "/manual/api/assets/cn123/bev-closeup-video")
            self.assertIsNone(index.descriptor("cn123", "other_scope"))
            self.assertIsNone(index.descriptor("../cn123", "version_scope"))
            self.assertEqual(index.asset_path("cn123", "version_scope", "bev-closeup-poster"), (root / "objects/poster.jpg").resolve())
            for patch in (dict(video_path="../../outside.mp4"), dict(time_observations_verified=False), dict(frame_count=399), dict(recipe_id="old-preview")):
                path.write_text(json.dumps(dict(receipt, **patch)))
                self.assertIsNone(CloseupVideoIndex(root).descriptor("cn123", "version_scope"))

    def test_tracks_preserve_original_and_reject_anchor_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, receipt = self.fixture(tmp)
            original = dict(url="/api/assets/cn123/bev-video-0", duration_ms=40000, event_time_sec=20,
                            anchor_ms=receipt["anchor_ms"], trip_id="trip1", tracks=[dict(url="/api/assets/cn123/bev-video-0", label="BEV 视频"), dict(url="/api/assets/cn123/camera-video", label="Camera102 视频")])
            provider = MagicMock()
            provider.get_video.return_value = original
            wrapped = WithCloseupVideo(provider, CloseupVideoIndex(root), "version_scope")
            video = wrapped.get_video("cn123")
            self.assertEqual(video["url"], original["url"])
            self.assertEqual(len(video["tracks"]), 3)
            self.assertEqual(len(original["tracks"]), 2)
            self.assertTrue(video["tracks"][2]["poster_url"].endswith("bev-closeup-poster"))
            provider.get_assets.assert_not_called()
            provider.get_video.return_value = dict(original, anchor_ms=receipt["anchor_ms"]+100)
            self.assertEqual(len(wrapped.get_video("cn123")["tracks"]), 2)
            provider.get_video.return_value = None
            self.assertEqual(wrapped.get_video("cn123")["source_id"], "bev_closeup")


if __name__ == "__main__":
    unittest.main()
