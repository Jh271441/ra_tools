"""Standalone read-only artifact pages mounted under the dashboard origin.

These routes are intentionally absent from the Manual Workbench navigation shell.
HTML templates are rendered once at import time with the configured base path so
request handling performs zero blocking filesystem I/O.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..runtime import settings
from ..web_paths import render_index_html

router = APIRouter()

ARCHITECTURE_ORIGINAL_330_HTML = render_index_html(
    (
        settings.static_dir
        / "artifacts"
        / "architecture-original-330"
        / "index.html"
    ).read_text(encoding="utf-8"),
    settings.base_path,
)


@router.get("/architecture-original-330", include_in_schema=False)
@router.get("/architecture-original-330/", include_in_schema=False)
async def architecture_original_330_page() -> HTMLResponse:
    return HTMLResponse(
        content=ARCHITECTURE_ORIGINAL_330_HTML,
        headers={"Cache-Control": "no-store, max-age=0"},
    )
