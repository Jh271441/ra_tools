"""Lossless, disposable fragmented copies of ready short-GOP playback videos.

Only the MP4 container changes. Every compressed sample and presentation time
is checked against the existing playback copy before publishing its byte index.
HTTP requests only queue preparation; they never wait for ffmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import struct

from .video_playback import VideoPlaybackCache, source_identity

RECIPE = "segments-v1"
MAX_INDEX_BYTES = 128 * 1024


def _boxes(data: bytes, start: int = 0, end: int | None = None):
    end = len(data) if end is None else end
    while start < end:
        if start + 8 > end:
            raise ValueError("truncated MP4 box")
        size, kind = struct.unpack_from(">I4s", data, start)
        header = 8
        if size == 1:
            if start + 16 > end:
                raise ValueError("truncated MP4 box")
            size = struct.unpack_from(">Q", data, start + 8)[0]
            header = 16
        if size < header or start + size > end:
            raise ValueError("invalid MP4 box")
        yield kind, start + header, start + size
        start += size


def _child(data: bytes, kind: bytes) -> bytes:
    matches = [data[a:b] for name, a, b in _boxes(data) if name == kind]
    if len(matches) != 1:
        raise ValueError("unsupported MP4 structure")
    return matches[0]


def _track(data: bytes) -> tuple[int, str, str]:
    mdia = _child(_child(data, b"trak"), b"mdia")
    mdhd = _child(mdia, b"mdhd")
    timescale = struct.unpack_from(">I", mdhd, 20 if mdhd[0] == 1 else 12)[0]
    stsd = _child(_child(_child(mdia, b"minf"), b"stbl"), b"stsd")
    avc1 = _child(stsd[8:], b"avc1")
    config = _child(avc1[78:], b"avcC")
    if not timescale or len(config) < 4 or config[0] != 1:
        raise ValueError("unsupported MP4 codec")
    return timescale, "avc1." + config[1:4].hex(), "SHA256:" + hashlib.sha256(config).hexdigest()


def _samples(data: bytes):
    """Read the restricted single-track fragments produced by our recipe."""
    traf = _child(data, b"traf")
    tfhd, tfdt, trun = (_child(traf, name) for name in (b"tfhd", b"tfdt", b"trun"))
    flags = int.from_bytes(tfhd[1:4], "big")
    if not flags & 0x020000 or flags & 0x000003:
        raise ValueError("unsupported fragment base")
    at = 8
    defaults = []
    for flag in (0x8, 0x10, 0x20):
        defaults.append(struct.unpack_from(">I", tfhd, at)[0] if flags & flag else 0)
        if flags & flag:
            at += 4
    decode = struct.unpack_from(">Q" if tfdt[0] == 1 else ">I", tfdt, 4)[0]
    flags = int.from_bytes(trun[1:4], "big")
    count = struct.unpack_from(">I", trun, 4)[0]
    if not flags & 1 or not 0 < count <= 7200 or trun[0] not in (0, 1):
        raise ValueError("unsupported fragment samples")
    offset = struct.unpack_from(">i", trun, 8)[0]
    at = 12
    first_flags = struct.unpack_from(">I", trun, at)[0] if flags & 4 else defaults[2]
    if flags & 4:
        at += 4
    rows = []
    for i in range(count):
        values = []
        for flag, default in zip((0x100, 0x200, 0x400, 0x800), (*defaults, 0)):
            signed = flag == 0x800 and trun[0] == 1
            values.append(struct.unpack_from(">i" if signed else ">I", trun, at)[0]
                          if flags & flag else default)
            if flags & flag:
                at += 4
        duration, size, sample_flags, composition = values
        if i == 0 and flags & 4:
            sample_flags = first_flags
        if not duration or not size or (i == 0 and sample_flags & 0x10000):
            raise ValueError("fragment has no independent start")
        rows.append((decode + composition, duration, size))
        decode += duration
    if at != len(trun):
        raise ValueError("unexpected fragment sample fields")
    return offset, rows


def fragment_index(path: Path, before: dict) -> dict:
    """Verify exact compressed samples and raw MP4 presentation timestamps.

    ffprobe adds a reorder delay to negative-CTO fragmented files, although MSE
    uses their raw timestamps. Reading tfdt/trun avoids applying that delay a
    second time and shifting the displayed frames by two or more frame steps.
    """
    stream, = before["streams"]  # Audio/multiple tracks retain native playback.
    packets = before["packets"]
    total = float(stream["duration"])
    if (stream["codec_name"] != "h264" or not 0 < total <= 120 or not 0 < len(packets) <= 7200
            or stream["width"] < 1280):
        # Native and MSE demuxers infer different colors for untagged SD files.
        # Keep those on the existing native path rather than changing colors.
        raise ValueError("unsupported stream")
    length = path.stat().st_size
    segments, packet_at = [], 0
    init_end = timescale = None
    codec = ""
    with path.open("rb") as handle:
        while handle.tell() < length:
            at = handle.tell()
            header = handle.read(8)
            if len(header) != 8:
                raise ValueError("truncated MP4")
            size, kind = struct.unpack(">I4s", header)
            header_size = 8
            if size == 1:
                size = struct.unpack(">Q", handle.read(8))[0]
                header_size = 16
            if size < header_size or at + size > length:
                raise ValueError("invalid MP4 length")
            if kind == b"moov":
                if timescale is not None or size > 1024 * 1024 or segments:
                    raise ValueError("invalid init")
                timescale, codec, config_hash = _track(handle.read(size - header_size))
                if config_hash != stream["extradata_hash"]:
                    raise ValueError("video decoder configuration changed")
            elif kind == b"moof":
                if not timescale or size > 1024 * 1024:
                    raise ValueError("invalid fragment")
                if init_end is None:
                    init_end = at
                offset, samples = _samples(handle.read(size - header_size))
                mdat = handle.read(8)
                if len(mdat) != 8:
                    raise ValueError("missing fragment data")
                data_size, data_kind = struct.unpack(">I4s", mdat)
                if (data_kind != b"mdat" or data_size < 8 or handle.tell() != at + offset
                        or at + size + data_size > length
                        or sum(row[2] for row in samples) != data_size - 8):
                    raise ValueError("invalid fragment data range")
                for pts, duration, sample_size in samples:
                    if packet_at >= len(packets):
                        raise ValueError("extra frame")
                    packet = packets[packet_at]
                    digest = "SHA256:" + hashlib.sha256(handle.read(sample_size)).hexdigest()
                    if (digest != packet["data_hash"]
                            or abs(pts / timescale - float(packet["pts_time"])) > .000001
                            or abs(duration / timescale - float(packet["duration_time"])) > .000001):
                        raise ValueError("compressed video or frame timing changed")
                    packet_at += 1
                start = min(p for p, _, _ in samples) / timescale
                end = max(p + d for p, d, _ in samples) / timescale
                previous = segments[-1]["end"] if segments else 0
                if abs(start - previous) > .000001 or end - start > 2.2:
                    raise ValueError("non-contiguous fragment timeline")
                segments.append(dict(start=start, end=end, first=at, last=handle.tell() - 1))
                continue
            elif kind not in (b"ftyp", b"sidx", b"mfra", b"free"):
                raise ValueError("unexpected top-level MP4 box")
            handle.seek(at + size)
    if (packet_at != len(packets) or not segments or init_end is None or init_end > 64 * 1024
            or abs(segments[-1]["end"] - total) > .001):
        raise ValueError("incomplete fragment timeline")
    with path.open("rb") as handle:
        init = base64.b64encode(handle.read(init_end)).decode("ascii")
    return dict(recipe=RECIPE, codec=codec, duration=total, size=length,
                init=init, segments=segments)


@dataclass(frozen=True)
class StreamCopy:
    path: Path
    manifest: dict


class VideoStreamCache(VideoPlaybackCache):
    """Reuse the bounded jobs/process lifecycle; input is a verified copy."""

    def get(self, source: Path) -> StreamCopy | None:
        try:
            _, key = source_identity(source)
            folder = self._folder(key)
            receipt = folder / "receipt.json"
            receipt.resolve().relative_to(self.root)
            if receipt.stat().st_size > MAX_INDEX_BYTES:
                return None
            row = json.loads(receipt.read_text())
            output = (folder / "video.mp4").resolve()
            output.relative_to(folder)
            stat = output.stat()
            manifest = row["manifest"]
            if (row["recipe"] == RECIPE and row["source_key"] == key and row["verified"] is True
                    and output.is_file() and row["size_bytes"] == manifest["size"] == stat.st_size > 0
                    and row["mtime_ns"] == stat.st_mtime_ns and manifest["recipe"] == RECIPE
                    and len(manifest["fingerprint"]) == 64):
                return StreamCopy(output, manifest)
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            pass
        return None

    def _probe(self, path: Path) -> dict:
        return json.loads(self._run([
            "ffprobe", "-v", "error", "-show_streams", "-show_packets", "-show_data_hash", "sha256",
            "-show_entries", "stream=codec_name,width,duration,extradata_hash:packet=pts_time,duration_time,data_hash",
            "-of", "json", str(path),
        ], timeout=60))

    def build(self, source: Path) -> StreamCopy | None:
        ready = self.get(source)
        if ready:
            return ready
        path, key = source_identity(source)
        folder = self._folder(key)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "build.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return None
            ready = self.get(path)
            if ready:
                return ready
            if shutil.disk_usage(folder).free < max(5 * 1024**3, path.stat().st_size * 4):
                return None
            before = self._probe(path)
            if (len(before.get("streams", [])) != 1 or before["streams"][0].get("codec_name") != "h264"
                    or before["streams"][0].get("width", 0) < 1280):
                return None
            temp, pending = folder / "pending.mp4", folder / "pending.json"
            try:
                self._run([
                    "nice", "-n", "10", "ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(path),
                    "-map", "0:v:0", "-c", "copy", "-movflags",
                    "+frag_keyframe+empty_moov+default_base_moof+global_sidx+negative_cts_offsets", str(temp),
                ])
                manifest = fragment_index(temp, before)
                if source_identity(path)[1] != key:
                    return None
                output = folder / "video.mp4"
                temp.replace(output)
                stat = output.stat()
                manifest["fingerprint"] = hashlib.sha256(
                    f"{RECIPE}:{key}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
                row = dict(recipe=RECIPE, source_key=key, verified=True, size_bytes=stat.st_size,
                           mtime_ns=stat.st_mtime_ns, manifest=manifest)
                pending.write_text(json.dumps(row, separators=(",", ":")))
                pending.replace(folder / "receipt.json")
                return StreamCopy(output, manifest)
            finally:
                temp.unlink(missing_ok=True)
                pending.unlink(missing_ok=True)
