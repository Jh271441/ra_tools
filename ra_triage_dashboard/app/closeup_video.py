"""Root-confined, independently verified closeup video track receipts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from urllib.parse import quote

from .timed_cache import TimedSingleFlightCache
from .web_paths import with_base_path

SOURCE_ID = "bev_closeup"
RECIPE_ID = "ego30-forward4-1080p-10fps-v1"
ASSET_ID = "bev-closeup-video"
POSTER_ID = "bev-closeup-poster"
ISSUE_RE = re.compile(r"[A-Za-z0-9_-]{3,128}")


class CloseupVideoIndex:
    def __init__(self, root: Path, base_path: str = ""):
        self.root = root.resolve()
        self.base_path = base_path
        self.cache = TimedSingleFlightCache(ttl_seconds=15, max_entries=4000)

    def receipt(self, issue_id: str, scope: str):
        if not ISSUE_RE.fullmatch(issue_id):
            return None
        return self.cache.get_or_load((issue_id, scope), lambda: self._load(issue_id, scope))

    def _load(self, issue_id, scope):
        try:
            path = (self.root / "issues" / issue_id / "receipt.json").resolve()
            path.relative_to(self.root)
            if path.stat().st_size > 32768:
                return None
            row = json.loads(path.read_text())
            if not isinstance(row, dict) or not isinstance(row.get("scopes"), list):
                return None
            if (row.get("issue_id") != issue_id or row.get("status") != "verified"
                    or row.get("source_id") != SOURCE_ID or row.get("recipe_id") != RECIPE_ID
                    or scope not in row.get("scopes", [])
                    or row.get("duration_ms") != 40000 or row.get("frame_count") != 400
                    or row.get("frame_step_ms") != 100 or row.get("event_time_sec") != 20
                    or row.get("full_decode_passed") is not True
                    or row.get("time_observations_verified") is not True
                    or type(row.get("anchor_ms")) is not int or row["anchor_ms"] <= 0):
                return None
            for key, suffix in (("video_path", ".mp4"), ("poster_path", ".jpg")):
                if not isinstance(row.get(key), str):
                    return None
                asset = (self.root / row[key]).resolve()
                asset.relative_to(self.root)
                if asset.suffix.lower() != suffix or not asset.is_file():
                    return None
            return row
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def descriptor(self, issue_id, scope):
        row = self.receipt(issue_id, scope)
        if not row:
            return None
        def url(asset):
            return with_base_path(self.base_path, f"/api/assets/{quote(issue_id)}/{asset}")
        return dict(id=ASSET_ID, source=SOURCE_ID, source_id=SOURCE_ID,
                    label="局部 BEV 视频", recipe_id=RECIPE_ID,
                    url=url(ASSET_ID), poster_url=url(POSTER_ID),
                    duration_ms=40000, start_offset_sec=-20, event_time_sec=20,
                    frame_step_ms=100, frame_count=400, width=1920, height=1080,
                    anchor_ms=row["anchor_ms"], trip_id=row.get("trip_id"),
                    anchor_source=row.get("anchor_source"))

    def asset_path(self, issue_id, scope, asset_id):
        if asset_id not in (ASSET_ID, POSTER_ID):
            return None
        row = self.receipt(issue_id, scope)
        if row:
            path = (self.root / row["video_path" if asset_id == ASSET_ID else "poster_path"]).resolve()
            try:
                path.relative_to(self.root)
            except ValueError:
                return None
            return path if path.is_file() else None
        return None


class WithCloseupVideo:
    def __init__(self, provider, index, scope):
        self.provider, self.index, self.scope = provider, index, scope

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def get_video(self, issue_id):
        original = self.provider.get_video(issue_id)
        closeup = self.index.descriptor(issue_id, self.scope)
        if not closeup:
            return original
        if not original:
            return dict(closeup, tracks=[dict(closeup)])
        capture = {} if original.get("anchor_ms") and original.get("trip_id") else self.provider.get_assets(issue_id).get("capture") or {}
        anchor = original.get("anchor_ms") or capture.get("timestamp_ms")
        trip = original.get("trip_id") or capture.get("trip_id")
        if anchor != closeup["anchor_ms"] or trip != closeup["trip_id"] or original.get("duration_ms") != 40000 or original.get("event_time_sec") != 20:
            return original
        result = copy.deepcopy(original)
        tracks = result.get("tracks") or [dict(result, label="BEV 视频")]
        result["tracks"] = [*tracks, closeup]
        return result

    def get_asset_path(self, issue_id, asset_id):
        if asset_id in (ASSET_ID, POSTER_ID):
            return self.index.asset_path(issue_id, self.scope, asset_id)
        return self.provider.get_asset_path(issue_id, asset_id)
