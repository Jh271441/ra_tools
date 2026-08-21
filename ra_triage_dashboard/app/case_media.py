"""Progressive Issue-media resolution shared by detail routes.

The Issue detail record is small and is needed before a reviewer can read or
edit a Review.  BEV/video/camera discovery is filesystem-bound and can be much
slower on a cold network volume.  This module keeps that optional work out of
the core detail response and resolves independent sources concurrently.
"""

from __future__ import annotations

import asyncio
from typing import Any


def empty_case_media(issue_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the stable no-media shape used by both detail endpoints."""

    return (
        {"available": False, "issue_id": issue_id, "frames": [], "capture": {}},
        {"available": False, "issue_id": issue_id, "frames": [], "capture": {}},
    )


def _video_with_poster(
    video: dict[str, Any] | None,
    assets: dict[str, Any],
) -> dict[str, Any] | None:
    """Attach the nearest BEV frame as a cheap video poster when available."""

    if not isinstance(video, dict):
        return video
    frames = assets.get("frames") if isinstance(assets, dict) else None
    candidates = [frame for frame in (frames or []) if isinstance(frame, dict)]
    if not candidates:
        return dict(video)

    def distance(frame: dict[str, Any]) -> float:
        raw = frame.get("offset_ms")
        if raw is None and frame.get("offset_sec") is not None:
            raw = frame.get("offset_sec") * 1000
        try:
            return abs(float(raw))
        except (TypeError, ValueError):
            return float("inf")

    poster = min(candidates, key=distance)
    poster_url = str(poster.get("url") or "").strip()
    result = dict(video)
    if poster_url:
        result["poster_url"] = poster_url
    return result


async def resolve_case_media(
    provider: Any,
    issue_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve BEV/video/camera without serialising independent I/O.

    BEV and captured video use unrelated indexes, so they start together.  The
    camera folder selection depends on the BEV timestamp and starts as soon as
    BEV is available; it overlaps the remainder of video discovery.
    """

    asset_task = asyncio.create_task(asyncio.to_thread(provider.get_assets, issue_id))
    video_task = asyncio.create_task(asyncio.to_thread(provider.get_video, issue_id))
    tasks: list[asyncio.Task[Any]] = [asset_task, video_task]
    try:
        assets = await asset_task
        timestamp_ms = (assets.get("capture") or {}).get("timestamp_ms")
        camera_task = asyncio.create_task(
            asyncio.to_thread(provider.get_camera_assets, issue_id, timestamp_ms)
        )
        tasks.append(camera_task)
        captured_video, camera = await asyncio.gather(video_task, camera_task)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    # Preserve the dashboard's existing preference for captured video while
    # never mutating a cached descriptor returned by a provider.
    public_assets = dict(assets) if isinstance(assets, dict) else {}
    video = _video_with_poster(captured_video, public_assets)
    if video is not None:
        public_assets["video"] = video
        public_assets["available"] = True
    return public_assets, camera if isinstance(camera, dict) else {}
