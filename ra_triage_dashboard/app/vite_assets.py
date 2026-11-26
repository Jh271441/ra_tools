"""Load Vite build manifest once at startup; zero Node.js dependency at runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .static_assets import build_frontend_bundle, build_frontend_styles

_SAFE_ASSET_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _safe_dist_path(raw: str) -> str:
    cleaned = str(raw or "").lstrip("/")
    if not cleaned or ".." in cleaned or not _SAFE_ASSET_RE.fullmatch(cleaned):
        raise RuntimeError(f"Unsafe Vite manifest asset path: {raw!r}")
    return cleaned


def load_vite_assets(
    static_dir: Path | str,
    *,
    entry: str = "src/main.tsx",
) -> dict[str, Any]:
    """Return ordered JS entry + CSS asset paths relative to /static/dist/."""
    dist_dir = Path(static_dir) / "dist"
    manifest_path = dist_dir / ".vite" / "manifest.json"
    if not manifest_path.is_file():
        return {"js": [], "css": []}
    raw: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("Invalid Vite manifest.json payload")
    record = raw.get(entry)
    if not isinstance(record, dict) or not record.get("file"):
        record = next(
            (v for v in raw.values() if isinstance(v, dict) and v.get("isEntry")),
            None,
        )
    if not isinstance(record, dict) or not record.get("file"):
        return {"js": [], "css": []}

    js_files: list[str] = [_safe_dist_path(str(record["file"]))]
    css_files: list[str] = []
    visited: set[str] = set()

    def collect_css(chunk: dict[str, Any]) -> None:
        for css in chunk.get("css") or []:
            safe_css = _safe_dist_path(str(css))
            if safe_css not in css_files:
                css_files.append(safe_css)
        for imp in chunk.get("imports") or []:
            if imp in visited:
                continue
            visited.add(imp)
            imported = raw.get(imp)
            if isinstance(imported, dict):
                collect_css(imported)

    collect_css(record)
    # The shell can start the current island while the entry bundle downloads.
    # Only follow static imports. Other pages and on-demand dialogs stay lazy.
    page_chunks = {
        "/review": "ReviewGalleryIsland",
        "/review-assignments": "ReviewAssignmentsPage",
        "/version-metrics": "VersionMetricsPage",
    }
    preload_by_route = {}
    for route, name in page_chunks.items():
        files = dict.fromkeys(js_files)
        def visit(key: str) -> None:
            item = raw.get(key)
            if not isinstance(item, dict) or not item.get("file"):
                return
            path = _safe_dist_path(str(item["file"]))
            if path in files:
                return
            files[path] = None
            for dep in item.get("imports") or []:
                visit(dep)

        visit(f"src/pages/{name}.tsx")
        preload_by_route[route] = list(files)
    return {"js": js_files, "css": css_files, "preloadByRoute": preload_by_route}


def render_vite_assets_json(
    static_dir: Path | str,
    *,
    entry: str = "src/main.tsx",
) -> str:
    """Serialize validated Vite assets for safe inline HTML bootstrap."""
    payload: dict[str, Any] = dict(load_vite_assets(static_dir, entry=entry))
    static_path = Path(static_dir)
    if payload.get("js") and (static_path / "js").is_dir():
        bundle_bytes = build_frontend_bundle(static_path)
        payload["bundleRev"] = hashlib.sha256(bundle_bytes).hexdigest()[:10]
    if payload.get("js") and (static_path / "index.html").is_file():
        css_bytes = build_frontend_styles(static_path)
        payload["cssRev"] = hashlib.sha256(css_bytes).hexdigest()[:10]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).replace(
        "</", "<\\/"
    )
