"""Compressed public frontend assets; API/media responses keep their own policy."""
from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
import re

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles
from starlette.types import Scope


def build_frontend_bundle(directory: Path | str) -> bytes:
    """Keep source ownership separate while shipping one classic script."""
    modules = Path(directory) / "js"
    names = [line.strip() for line in (modules / "MANIFEST").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not names or len(names) != len(set(names)):
        raise RuntimeError("Frontend MANIFEST must contain unique modules")
    if any(not re.fullmatch(r"[a-z][a-z0-9-]+\.js", name) for name in names):
        raise RuntimeError("Invalid frontend module name")
    return b"\n;\n".join((modules / name).read_bytes() for name in names)


class CachedStaticFiles(StaticFiles):
    def __init__(self, directory: Path | str):
        super().__init__(directory=directory)
        # Build once during application construction, never on a request or
        # from runtime/user data. Both representations are immutable in memory.
        body = build_frontend_bundle(directory)
        self.frontend_bundles = {
            "identity": body,
            "gzip": gzip.compress(body, compresslevel=5, mtime=0),
        }
        self.frontend_etags = {
            encoding: '"' + hashlib.sha256(value).hexdigest() + '"'
            for encoding, value in self.frontend_bundles.items()
        }

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path != "app-bundle.js":
            return await super().get_response(path, scope)
        if scope["method"] not in {"GET", "HEAD"}:
            raise HTTPException(status_code=405)
        request_headers = Headers(scope=scope)
        encoding = "gzip" if "gzip" in request_headers.get("accept-encoding", "") else "identity"
        body = self.frontend_bundles[encoding]
        headers = {
            "Cache-Control": "public, max-age=604800, immutable",
            "ETag": self.frontend_etags[encoding],
            "Vary": "Accept-Encoding",
        }
        if encoding == "gzip":
            headers["Content-Encoding"] = "gzip"
        if self.is_not_modified(Headers(headers), request_headers):
            return NotModifiedResponse(headers)
        headers["Content-Length"] = str(len(body))
        return Response(b"" if scope["method"] == "HEAD" else body,
                        media_type="text/javascript", headers=headers)

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
