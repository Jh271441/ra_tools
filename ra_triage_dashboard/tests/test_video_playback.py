import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app.video_playback import RECIPE, VideoPlaybackCache, source_identity


def boxes(*names):
    return b"".join((8).to_bytes(4, "big") + name for name in names)


def probe():
    return {"streams": [{"codec_name": "h264", "width": 2560, "height": 1440,
                          "pix_fmt": "yuv420p", "r_frame_rate": "10/1", "duration": "40"}],
            "packets": [{"pts_time": str(i / 10), "flags": "K_" if i % 20 == 0 else "__"}
                        for i in range(400)]}


class VideoPlaybackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(boxes(b"ftyp", b"mdat", b"moov"))
        self.cache = VideoPlaybackCache(self.root / "cache")
        self.addCleanup(self.cache.shutdown)

    def ready_copy(self):
        _, key = source_identity(self.source)
        folder = self.cache._folder(key)
        folder.mkdir(parents=True)
        output = folder / "video.mp4"
        output.write_bytes(boxes(b"ftyp", b"moov", b"mdat"))
        stat = output.stat()
        row = dict(recipe=RECIPE, source_key=key, verified=True,
                   size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        (folder / "receipt.json").write_text(json.dumps(row))
        return output, folder

    def test_source_and_output_replacements_invalidate_copy(self):
        output, folder = self.ready_copy()
        self.assertEqual(self.cache.get(self.source), output)
        output.write_bytes(b"truncated")
        self.assertIsNone(self.cache.get(self.source))
        self.source.write_bytes(b"new capture")
        self.assertIsNone(self.cache.get(self.source))

    def test_unverified_pending_or_escaped_copy_is_never_served(self):
        output, folder = self.ready_copy()
        receipt = folder / "receipt.json"
        row = json.loads(receipt.read_text())
        for update in [dict(verified=False), dict(source_key="other"), dict(recipe="other")]:
            receipt.write_text(json.dumps(dict(row, **update)))
            self.assertIsNone(self.cache.get(self.source))
        receipt.write_text(json.dumps(row))
        output.unlink()
        output.symlink_to(self.source)
        self.assertIsNone(self.cache.get(self.source))
        receipt.write_text("[]")
        self.assertIsNone(self.cache.get(self.source))

    def test_http_request_is_nonblocking_and_single_flight(self):
        started, finish = threading.Event(), threading.Event()
        def build(_path):
            started.set()
            finish.wait(5)
        try:
            with patch.object(self.cache, "build", side_effect=build) as build_mock:
                before = time.monotonic()
                self.assertIsNone(self.cache.request(self.source))
                self.assertLess(time.monotonic() - before, .1)
                self.assertTrue(started.wait(1))
                for _ in range(20):
                    self.assertIsNone(self.cache.request(self.source))
                build_mock.assert_called_once()
                finish.set()
                self.cache.shutdown()
        finally:
            finish.set()

    def test_validation_rejects_geometry_timing_missing_t0_and_tail_index(self):
        output = self.root / "output.mp4"
        output.write_bytes(boxes(b"ftyp", b"moov", b"mdat"))
        good = probe()
        self.cache._validate(good, good, output)
        for kind in ["geometry", "timestamp", "dropped", "keyframes", "midpoint"]:
            bad = copy.deepcopy(good)
            if kind == "geometry": bad["streams"][0]["width"] = 1920
            if kind == "timestamp": bad["packets"][200]["pts_time"] = "20.01"
            if kind == "dropped": bad["packets"].pop()
            if kind == "keyframes":
                for p in bad["packets"][1:]: p["flags"] = "__"
            if kind == "midpoint": bad["packets"][200]["flags"] = "__"
            with self.assertRaises(ValueError, msg=kind):
                self.cache._validate(good, bad, output)
        output.write_bytes(boxes(b"ftyp", b"mdat", b"moov"))
        with self.assertRaises(ValueError): self.cache._validate(good, good, output)

    def test_failed_build_never_publishes_receipt_or_modifies_original(self):
        original = self.source.read_bytes()
        with patch.object(self.cache, "_probe", return_value=probe()), \
             patch.object(self.cache, "_run", side_effect=RuntimeError("encode failed")), \
             patch("ra_triage_dashboard.app.video_playback.shutil.disk_usage") as usage:
            usage.return_value.free = 10 * 1024**3
            with self.assertRaises(RuntimeError): self.cache.build(self.source)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertIsNone(self.cache.get(self.source))
        self.assertEqual(list(self.cache.root.rglob("receipt.json")), [])
        self.assertEqual(list(self.cache.root.rglob("pending.mp4")), [])

    def test_low_disk_preserves_original_and_does_no_encoding(self):
        with patch("ra_triage_dashboard.app.video_playback.shutil.disk_usage") as usage, \
             patch.object(self.cache, "_run") as run:
            usage.return_value.free = 1024
            self.assertIsNone(self.cache.build(self.source))
            run.assert_not_called()

    def test_warmer_uses_latest_indexed_capture_not_old_or_unreferenced_mp4(self):
        from ra_triage_dashboard.scripts.warm_video_playback import indexed_sources
        media = self.root / "media_layouts" / "dataset"
        for stamp in [100, 200]:
            folder = media / "issues" / f"cn1234_{stamp}"
            folder.mkdir(parents=True)
            (folder / "clip.mp4").write_bytes(b"capture")
            meta = folder / "meta.json"
            meta.write_text(json.dumps({"issue_id": "cn1234", "status": "captured",
                "capture_plan": {"variants": [{"video_relative_path": "clip.mp4"}]}}))
            os.utime(meta, ns=(stamp, stamp))
        (media / "unindexed.mp4").write_bytes(b"unindexed")
        self.assertEqual(indexed_sources(media.parent), {(media / "issues/cn1234_200/clip.mp4").resolve()})


if __name__ == "__main__":
    unittest.main()
