"""Prebuild disposable playback copies; never rewrites captures or metadata.

Use published media roots only. The HTTP route independently requires its normal
Issue/scope/index checks before any cached copy is served.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import json
from pathlib import Path
import signal
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ra_triage_dashboard.app.video_playback import VideoPlaybackCache, source_identity
from ra_triage_dashboard.app.video_stream import VideoStreamCache
from ra_triage_dashboard.app.assets import VideoIndex
from ra_triage_dashboard.app.closeup_video import CloseupVideoIndex, ASSET_ID


def indexed_sources(root: Path) -> set[Path]:
    """Reuse live indexes; never encode unreferenced/historical MP4 objects."""
    containers = [p for p in root.iterdir() if p.is_dir()] if root.name == "media_layouts" else [root]
    paths = set()
    for container in containers:
        if container.name == "bev_closeup":
            index = CloseupVideoIndex(container)
            for receipt in container.glob("issues/*/receipt.json"):
                try:
                    if receipt.stat().st_size > 32768:
                        continue
                    row = json.loads(receipt.read_text())
                    scopes = row.get("scopes") or []
                    path = index.asset_path(receipt.parent.name, scopes[0] if scopes else "", ASSET_ID)
                    if path:
                        paths.add(path)
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
            continue
        video_root = container / "video" if (container / "video").is_dir() else container
        index = VideoIndex(video_root)
        for issue in index.indexed_issue_ids():
            video = index.get_video(issue)
            for track in ([video, *video.get("tracks", [])] if video else []):
                asset = unquote(urlsplit(track["url"]).path.rsplit("/", 1)[-1])
                path = index.get_asset_path(issue, asset)
                if path:
                    paths.add(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, action="append", default=[])
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--segments", action="store_true", help="Remux ready playback copies without encoding")
    parser.add_argument("--playback-cache-root", type=Path, help="Existing short-GOP cache (required with --segments)")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--watch", action="store_true", help="Rescan published roots every 60 seconds")
    args = parser.parse_args()
    if not args.source_root and not args.source:
        parser.error("provide at least one published source root or source")
    if args.segments and (not args.playback_cache_root or args.cache_root.resolve() == args.playback_cache_root.resolve()):
        parser.error("segments require a separate playback-cache-root")
    roots = [root.resolve(strict=True) for root in args.source_root]
    cache = VideoStreamCache(args.cache_root) if args.segments else VideoPlaybackCache(args.cache_root)
    playback_cache = VideoPlaybackCache(args.playback_cache_root) if args.segments else None
    cache.root.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    def shutdown(_signum, _frame):
        stop.set()
        cache.shutdown()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    # One owned inventory worker; per-source build locks also coordinate HTTP.
    with (cache.root / "warmer.lock").open("a") as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("playback warmer already running")
        while not stop.is_set():
            paths = {path.resolve(strict=True) for path in args.source}
            for root in roots:
                paths.update(indexed_sources(root))
            source_total = len(paths)
            if playback_cache:
                paths = {ready for path in paths if (ready := playback_cache.get(path))}
            state = {"recipe": "segments-v1" if args.segments else "short-gop-v1", "total": len(paths), "ready": 0, "built": 0,
                     "unavailable": 0, "failed": 0, "workers": args.workers,
                     "source_total": source_total, "source_unavailable": source_total - len(paths),
                     "started_at": time.time(), "status": "running"}
            def save():
                state["updated_at"] = time.time()
                args.report.parent.mkdir(parents=True, exist_ok=True)
                temp = args.report.with_suffix(".pending.json")
                temp.write_text(json.dumps(state, indent=2) + "\n")
                temp.replace(args.report)
            pending = []
            # New media gets prepared first; existing valid copies are cheap.
            ordered = []
            for path in paths:
                try:
                    ordered.append((path.stat().st_mtime_ns, path))
                except OSError:
                    continue  # A capture may expire or be replaced during inventory.
            state["total"] = len(ordered)
            for _, path in sorted(ordered, reverse=True):
                if cache.get(path):
                    state["ready"] += 1
                else:
                    pending.append(path)
            save()
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                iterator = iter(pending)
                active = {}
                last_save = time.monotonic()
                while not stop.is_set():
                    while len(active) < args.workers:
                        path = next(iterator, None)
                        if path is None:
                            break
                        active[executor.submit(cache.build, path)] = path
                    if not active:
                        break
                    done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
                    for future in done:
                        path = active.pop(future)
                        try:
                            if future.result():
                                state["ready"] += 1
                                state["built"] += 1
                            else:
                                state["unavailable"] += 1
                        except Exception:
                            state["failed"] += 1
                            print(json.dumps({"failed_source": source_identity(path)[1][:12]}), flush=True)
                    if time.monotonic() - last_save >= 10:
                        save()
                        print(json.dumps(state), flush=True)
                        last_save = time.monotonic()
            state["status"] = "stopped" if stop.is_set() else "partial" if state["failed"] or state["unavailable"] else "complete"
            save()
            print(json.dumps(state), flush=True)
            if not args.watch or stop.wait(60):
                break
    cache.shutdown()
    if playback_cache:
        playback_cache.shutdown()


if __name__ == "__main__":
    main()
