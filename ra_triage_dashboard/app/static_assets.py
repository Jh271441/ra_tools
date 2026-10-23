"""Compressed public frontend assets; API/media responses keep their own policy."""
from __future__ import annotations

from pathlib import Path

from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class CachedStaticFiles(StaticFiles):
    def file_response(self, full_path, stat_result, scope: Scope, status_code: int = 200) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        path = str(scope.get("path") or "")
        if path.endswith((".js", ".css", ".woff2", ".woff", ".png", ".svg")):
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        return response


def dashboard_static_app(directory: Path | str) -> GZipMiddleware:
    # Negotiate encoding and Vary through Starlette. Scope to /static so large
    # video/range requests and authenticated JSON never enter this compressor.
    return GZipMiddleware(CachedStaticFiles(directory=directory), minimum_size=1024, compresslevel=5)
