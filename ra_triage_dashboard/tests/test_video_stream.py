import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app.video_stream import VideoStreamCache, fragment_index


def box(kind, data=b""):
    return struct.pack(">I4s", len(data) + 8, kind) + data


def fixture():
    # Decode order contains B frames with negative composition offsets.
    times = [0, 400, 200, 100, 300, 500]
    samples = [f"compressed sample {i}".encode() for i in range(len(times))]
    config = box(b"avcC", bytes.fromhex("01640032"))
    stsd = box(b"stsd", b"\0" * 4 + struct.pack(">I", 1) + box(b"avc1", b"\0" * 78 + config))
    mdhd = box(b"mdhd", b"\0" * 12 + struct.pack(">I", 1000))
    moov = box(b"moov", box(b"trak", box(b"mdia", mdhd + box(b"minf", box(b"stbl", stsd)))))
    init = box(b"ftyp") + moov
    tfhd = box(b"tfhd", bytes.fromhex("00020038") + struct.pack(">IIII", 1, 100, 0, 0x01010000))
    tfdt = box(b"tfdt", b"\1\0\0\0" + struct.pack(">Q", 0))
    def moof(offset):
        rows = b"".join(struct.pack(">Ii", len(sample), pts - i * 100)
                        for i, (pts, sample) in enumerate(zip(times, samples)))
        trun = box(b"trun", bytes.fromhex("01000a05")
                   + struct.pack(">IiI", len(samples), offset, 0x02000000) + rows)
        return box(b"moof", box(b"traf", tfhd + tfdt + trun))
    fragment = moof(len(moof(0)) + 8) + box(b"mdat", b"".join(samples))
    before = {"streams": [{"codec_name": "h264", "width": 1280, "duration": ".6",
                           "extradata_hash": "SHA256:" + hashlib.sha256(bytes.fromhex("01640032")).hexdigest()}],
              "packets": [{"pts_time": str(pts / 1000), "duration_time": ".1",
                           "data_hash": "SHA256:" + hashlib.sha256(sample).hexdigest()}
                          for pts, sample in zip(times, samples)]}
    return init + fragment, before


class VideoStreamTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "fragment.mp4"
        self.data, self.before = fixture()
        self.output.write_bytes(self.data)

    def test_raw_composition_times_and_every_compressed_sample_are_preserved(self):
        manifest = fragment_index(self.output, self.before)
        self.assertEqual(manifest["codec"], "avc1.640032")
        self.assertEqual(manifest["duration"], .6)
        segment, = manifest["segments"]
        self.assertEqual((segment["start"], segment["end"]), (0, .6))
        self.assertEqual(segment["last"], len(self.data) - 1)
        self.assertEqual(base64.b64decode(manifest["init"]), self.data[:segment["first"]])
        for kind in ("shift", "duration", "dropped", "payload", "config", "sd", "audio"):
            before = copy.deepcopy(self.before)
            if kind == "shift": before["packets"][2]["pts_time"] = ".4"
            if kind == "duration": before["packets"][2]["duration_time"] = ".2"
            if kind == "dropped": before["packets"].pop()
            if kind == "payload": before["packets"][2]["data_hash"] = "other"
            if kind == "config": before["streams"][0]["extradata_hash"] = "other"
            if kind == "sd": before["streams"][0]["width"] = 320
            if kind == "audio": before["streams"].append({"codec_name": "aac"})
            with self.assertRaises(ValueError, msg=kind): fragment_index(self.output, before)
        self.output.write_bytes(self.data[:-1])
        with self.assertRaises(ValueError): fragment_index(self.output, self.before)

    def test_atomic_publication_invalidation_and_root_confinement(self):
        source = self.root / "ready-playback.mp4"
        source.write_bytes(b"existing verified copy")
        cache = VideoStreamCache(self.root / "cache")
        self.addCleanup(cache.shutdown)
        # Check the actual ffmpeg output argument; no codec encoder is invoked.
        def run(args):
            self.assertEqual(args[args.index("-c") + 1], "copy")
            Path(args[-1]).write_bytes(self.data)
        with patch.object(cache, "_probe", return_value=self.before), patch.object(cache, "_run", side_effect=run), \
             patch("ra_triage_dashboard.app.video_stream.shutil.disk_usage") as usage:
            usage.return_value.free = 10 * 1024**3
            ready = cache.build(source)
        self.assertIsNotNone(ready)
        self.assertEqual(cache.get(source), ready)
        self.assertEqual(len(ready.manifest["fingerprint"]), 64)
        self.assertNotIn("path", json.dumps(ready.manifest))
        ready.path.unlink()
        ready.path.symlink_to(self.output)
        self.assertIsNone(cache.get(source))
        ready.path.unlink()
        ready.path.write_bytes(self.data)
        self.assertIsNone(cache.get(source))  # Even same bytes require a new receipt.
        source.write_bytes(b"replacement playback copy")
        self.assertIsNone(cache.get(source))

    def test_failed_or_low_disk_build_leaves_input_and_no_ready_receipt(self):
        cache = VideoStreamCache(self.root / "cache")
        self.addCleanup(cache.shutdown)
        original = self.output.read_bytes()
        with patch("ra_triage_dashboard.app.video_stream.shutil.disk_usage") as usage, patch.object(cache, "_probe") as probe:
            usage.return_value.free = 1024
            self.assertIsNone(cache.build(self.output))
            probe.assert_not_called()
        with patch("ra_triage_dashboard.app.video_stream.shutil.disk_usage") as usage, \
             patch.object(cache, "_probe", return_value=self.before), \
             patch.object(cache, "_run", side_effect=RuntimeError("remux failed")):
            usage.return_value.free = 10 * 1024**3
            with self.assertRaises(RuntimeError): cache.build(self.output)
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(list(cache.root.rglob("receipt.json")), [])
        self.assertEqual(list(cache.root.rglob("pending.*")), [])
