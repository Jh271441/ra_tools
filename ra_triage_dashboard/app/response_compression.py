"""Compress complete page/JSON reads without buffering media or streams."""
from __future__ import annotations

import gzip

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _accepts_gzip(value: str) -> bool:
    qualities: dict[str, float] = {}
    for item in value.lower().split(","):
        encoding, *parameters = item.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            key, _, raw = parameter.strip().partition("=")
            if key == "q":
                try:
                    quality = float(raw)
                except ValueError:
                    quality = 0.0
        qualities[encoding] = quality
    return 0 < qualities.get("gzip", qualities.get("*", 0)) <= 1


class TextResponseCompressionMiddleware:
    """Keep existing cache/auth policy and leave streaming responses untouched.

    Installed inside the HTTP guards, this sees the complete HTMLResponse and
    JSONResponse body. A streaming response is forwarded from its first chunk;
    no body is accumulated and media/range/download/SSE never enter gzip.
    """

    def __init__(self, app: ASGIApp, minimum_size: int = 1024):
        self.app = app
        self.minimum_size = minimum_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET":
            await self.app(scope, receive, send)
            return
        request_headers = Headers(scope=scope)
        if "range" in request_headers:
            await self.app(scope, receive, send)
            return
        accepts_gzip = _accepts_gzip(request_headers.get("accept-encoding", ""))
        initial: Message | None = None

        async def send_response(message: Message) -> None:
            nonlocal initial
            if message["type"] == "http.response.start":
                initial = message
                return
            if initial is not None:
                headers = MutableHeaders(raw=initial["headers"])
                content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                body = message.get("body", b"")
                if (
                    message["type"] == "http.response.body"
                    and not message.get("more_body", False)
                    and initial["status"] == 200
                    and content_type in {"text/html", "application/json"}
                    and len(body) >= self.minimum_size
                    and "content-encoding" not in headers
                    and "content-range" not in headers
                    and "content-disposition" not in headers
                    and "no-transform" not in headers.get("cache-control", "").lower()
                ):
                    headers.add_vary_header("Accept-Encoding")
                    if accepts_gzip:
                        compressed = gzip.compress(body, compresslevel=5, mtime=0)
                        headers["Content-Encoding"] = "gzip"
                        headers["Content-Length"] = str(len(compressed))
                        if "etag" in headers and not headers["etag"].startswith("W/"):
                            headers["ETag"] = "W/" + headers["etag"]
                        message = {**message, "body": compressed}
                await send(initial)
                initial = None
            await send(message)

        await self.app(scope, receive, send_response)
