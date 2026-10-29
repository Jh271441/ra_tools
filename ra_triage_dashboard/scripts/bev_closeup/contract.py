"""Frozen closeup recipe, complete decoding and atomic publication."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from fractions import Fraction

SOURCE_ID = "bev_closeup"
RECIPE_ID = "ego30-forward4-1080p-10fps-v1"
LAYOUT = "RA_stuck_swag_with_planning_panel"
ORIGINAL_SHA = "52272f85a2475d4637891947469fe8034b2d0272fccf22e96cd144c9169fea64"
RENDERED_SHA = "613e4a6c1a0c000475e1eba24f1718acb5fb4bfd04dadfd3abd4035da8aa2575"


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pending")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def verify_metadata(meta, row):
    anchor = row["capture_timestamp_ms"]
    require(meta.get("status") == "captured" and not meta.get("errors"), "capture_failed")
    require(meta.get("issue_id") == row["issue_id"] and meta.get("trip_id") == row["trip_id"], "source_identity_mismatch")
    require(meta.get("timestamp_source") == "capture_timestamp_ms" and meta.get("request_timestamp_ms") == anchor, "anchor_mismatch")
    source = meta.get("source_row") or {}
    require(all(source.get(k) == row[k] for k in ("issue_id", "trip_id", "capture_timestamp_ms")), "source_row_mismatch")
    video = meta["render_metadata"]["videos"][0]
    require(video["capture_mode"] == "frame_seek" and video["requested_start_ms"] == anchor - 20000 and video["requested_end_ms"] == anchor + 20000 and video["effective_start_ms"] == anchor - 20000, "interval_mismatch")
    require(video["frame_step_ms"] == 100 and video["frame_count"] == 400 and video["visible_duration_ms"] == 40000, "frame_recipe_mismatch")
    require(video["seek_commit_check"] == "blurred_actual_current_time_and_paused_before_screenshot", "missing_committed_time_gate")
    observations = video["frame_observations"]
    require(len(observations) == 400, "missing_time_observations")
    for n, observed in enumerate(observations):
        target = anchor - 20000 + n * 100
        require(observed["target_ms"] == target and type(observed["actual_ms"]) in (int, float) and abs(observed["actual_ms"] - target) <= 1 and observed["paused"] is True and observed["editing"] is False, f"frame_time_mismatch:{n}")
    require(video["timeline_loading_gate"] == "hidden_before_every_frame" and video["per_frame_scene_gate"] == "canvas_present_and_no_missing_scene_message", "missing_readiness_gate")
    require(video["source_context"] == dict(padding_ms=1000, start_ms=anchor - 21000, end_ms=anchor + 21000, frame_timestamps_unchanged=True), "source_context_mismatch")
    view = video["view_override"]
    require(view["visual_distance"] == 30 and view["ego_target_offset_m"] == [4, 0, 0] and view["bev_only"] is True and view["persisted_to_cloud"] is False, "view_mismatch")
    require(view["original_layout_sha256"] == ORIGINAL_SHA and view["rendered_layout_sha256"] == RENDERED_SHA, "layout_drift")
    return video


def verify_case(folder, row, evidence):
    folder, evidence = Path(folder).resolve(), Path(evidence)
    meta_path = folder / "meta.json"
    video = verify_metadata(json.loads(meta_path.read_text()), row)
    path = (folder / video["relative_path"]).resolve()
    require(path.is_relative_to(folder) and path.suffix == ".mp4", "invalid_video_path")
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_read_frames:format=duration", "-of", "json", str(path)], text=True, timeout=180))
    stream = probe["streams"][0]
    require(stream["codec_name"] == "h264" and (stream["width"], stream["height"]) == (1920, 1080), "codec_dimensions_mismatch")
    require(int(stream["nb_read_frames"]) == 400 and Fraction(stream["r_frame_rate"]) == 10 and abs(float(probe["format"]["duration"]) - 40) <= .001, "decoded_timeline_mismatch")
    hashes = subprocess.check_output(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"], text=True, timeout=180)
    decoded = [line.split(",")[-1].strip() for line in hashes.splitlines() if line and not line.startswith("#")]
    require(len(decoded) == 400 and len(set(decoded)) > 1, "decode_incomplete_or_frozen")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "frames.md5").write_text(hashes)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf", "select=eq(n\\,0)+eq(n\\,200)+eq(n\\,399)", "-vsync", "0", str(evidence / "%02d.png")], check=True, timeout=120)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "20", "-i", str(path), "-frames:v", "1", "-q:v", "2", str(evidence / "poster.jpg")], check=True, timeout=120)
    result = dict(status="verified", source_id=SOURCE_ID, recipe_id=RECIPE_ID,
                  issue_id=row["issue_id"], trip_id=row["trip_id"], anchor_ms=row["capture_timestamp_ms"],
                  anchor_source=row["anchor_source"], version=row["version"], scopes=row.get("scopes", []),
                  duration_ms=40000, frame_step_ms=100, frame_count=400, event_time_sec=20,
                  full_decode_passed=True, time_observations_verified=True,
                  sha256=sha(path), size_bytes=path.stat().st_size, meta_sha256=sha(meta_path),
                  unique_decoded_hashes=len(set(decoded)), verified_at=time.time(),
                  seek_retry_count=video.get("seek_retry_count"), page_recovery_count=video.get("page_recovery_count"),
                  qa_frame_indices=[0, 200, 399], visual_review="pending")
    save(evidence / "verification.json", result)
    return path, result


def publish(path, meta_path, evidence, result, root):
    root, evidence = Path(root).resolve(), Path(evidence)
    key = hashlib.sha256(f'{result["trip_id"]}:{result["anchor_ms"]}:{RECIPE_ID}'.encode()).hexdigest()[:24]
    dest = root / "objects" / result["issue_id"] / key
    dest.mkdir(parents=True, exist_ok=True)
    for source, name in ((path, "video.mp4"), (Path(meta_path), "meta.json"), (evidence / "poster.jpg", "poster.jpg")):
        target = dest / name
        if target.exists():
            require(sha(source) == sha(target), "published_content_conflict")
        else:
            pending = target.with_suffix(target.suffix + ".pending")
            try:
                os.link(source, pending)
            except OSError:
                shutil.copyfile(source, pending)
            pending.replace(target)
    receipt = dict(result, video_path=str((dest / "video.mp4").relative_to(root)), poster_path=str((dest / "poster.jpg").relative_to(root)), meta_path=str((dest / "meta.json").relative_to(root)))
    save(dest / "verification.json", receipt)
    save(root / "issues" / result["issue_id"] / "receipt.json", receipt)
    return receipt
