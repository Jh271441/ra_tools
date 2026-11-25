"""Exercise raw ASGI bytes (HTTP clients often transparently decompress them)."""
import asyncio
import gzip
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Mount, Route

from ra_triage_dashboard.app.static_assets import dashboard_static_app


class StaticCompressionTest(unittest.TestCase):
    def request(self, path, encoding="gzip", extra_headers=(), method="GET"):
        static = Path(__file__).resolve().parents[1] / "static"
        async def api(_request):
            return Response(b"private-json" * 1000, media_type="application/json")
        app = Starlette(routes=[
            Mount("/manual/static", app=dashboard_static_app(static)),
            Route("/manual/api/example", api),
        ])
        async def run():
            messages = []
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message):
                messages.append(message)
            await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                       "method": method, "path": path, "raw_path": path.encode(), "root_path": "",
                       "query_string": b"v=manual-triage-611", "scheme": "http", "http_version": "1.1",
                       "headers": [(b"accept-encoding", encoding.encode()), *extra_headers]}, receive, send)
            return messages[0]["status"], dict(messages[0]["headers"]), b"".join(m.get("body", b"") for m in messages)
        return asyncio.run(run())

    def test_vite_entry_compression_identity_and_conditional_cache(self):
        static = Path(__file__).resolve().parents[1] / "static"
        manifest = json.loads((static / "dist/.vite/manifest.json").read_text(encoding="utf-8"))
        entry_rel = next(v["file"] for v in manifest.values() if isinstance(v, dict) and v.get("isEntry"))
        path = f"/manual/static/dist/{entry_rel}"
        status, headers, compressed = self.request(path)
        original = (static / "dist" / entry_rel).read_bytes()
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"content-encoding"], b"gzip")
        self.assertIn(b"Accept-Encoding", headers[b"vary"])
        self.assertIn(b"immutable", headers[b"cache-control"])
        self.assertIn(b"javascript", headers[b"content-type"])
        self.assertEqual(gzip.decompress(compressed), original)
        self.assertLess(len(compressed), len(original) * .4)
        status, identity_headers, body = self.request(path, "identity")
        self.assertEqual(status, 200)
        self.assertNotIn(b"content-encoding", identity_headers)
        self.assertEqual(body, original)
        status, _, body = self.request(path, extra_headers=[(b"if-none-match", headers[b"etag"])])
        self.assertEqual(status, 304)
        self.assertEqual(body, b"")

    def test_static_compression_does_not_wrap_api_or_missing_assets(self):
        status, headers, body = self.request("/manual/api/example")
        self.assertEqual(status, 200)
        self.assertNotIn(b"content-encoding", headers)
        self.assertEqual(body, b"private-json" * 1000)
        status, _, _ = self.request("/manual/static/not-found.js")
        self.assertEqual(status, 404)
        # Wave 3.6 retired legacy JS bundle & vendor cron-graph bundle
        for retired in ("/manual/static/app-bundle.js", "/manual/static/vendor/cron-graph/graph.js", "/manual/static/app.js"):
            status, _, _ = self.request(retired)
            self.assertEqual(status, 404, f"Expected retired asset 404 for {retired}")

    def test_unversioned_static_file_revalidates_instead_of_immutable(self):
        static = Path(__file__).resolve().parents[1] / "static"
        app = Starlette(routes=[Mount("/manual/static", app=dashboard_static_app(static))])

        async def fetch_unversioned():
            messages = []
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(msg):
                messages.append(msg)
            await app({
                "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                "method": "GET", "path": "/manual/static/css/base.css", "raw_path": b"/manual/static/css/base.css",
                "root_path": "", "query_string": b"", "scheme": "http", "http_version": "1.1",
                "headers": [(b"accept-encoding", b"gzip")],
            }, receive, send)
            return messages[0]["status"], dict(messages[0]["headers"])

        status, headers = asyncio.run(fetch_unversioned())
        self.assertEqual(status, 200)
        cache_control = headers.get(b"cache-control", b"")
        self.assertNotIn(b"immutable", cache_control)
        self.assertIn(b"must-revalidate", cache_control)

    def test_style_bundle_preserves_cascade_mobile_layer_and_conditional_cache(self):
        static = Path(__file__).resolve().parents[1] / "static"
        order = re.search(r"const stylesheetPaths = \[([\s\S]*?)\];", (static / "index.html").read_text())[1]
        names = json.loads("[" + re.sub(r",\s*$", "", order) + "]")
        self.assertEqual(names[-1], "css/mobile.css")
        expected = b"\n\n".join((static / name).read_bytes() for name in names)
        # Component files currently use only data URLs; relative asset URLs
        # would need rebasing when introducing them into the shared bundle.
        urls = [url.strip().strip("'\"") for url in re.findall(r"url\(([^)]+)\)", expected.decode())]
        self.assertFalse([url for url in urls if not url.startswith(("data:", "/", "https:", "http:"))])
        self.assertIsNone(re.search(r"@import\b", expected.decode()))
        route = "/manual/static/app-bundle.css"
        status, headers, body = self.request(route)
        self.assertEqual(status, 200)
        self.assertIn(b"text/css", headers[b"content-type"])
        self.assertEqual(gzip.decompress(body), expected)
        self.assertLess(len(body), len(expected) * .2)
        status, cached_headers, body = self.request(route, extra_headers=[(b"if-none-match", headers[b"etag"])])
        self.assertEqual((status, body), (304, b""))
        for key in (b"etag", b"cache-control", b"vary"):
            self.assertEqual(cached_headers[key], headers[key])
        status, head_headers, body = self.request(route, method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(head_headers[b"content-length"], headers[b"content-length"])
        status, identity_headers, body = self.request(route, encoding="identity")
        self.assertEqual((status, body), (200, expected))
        self.assertNotEqual(identity_headers[b"etag"], headers[b"etag"])
        status, cached_headers, body = self.request(route, encoding="identity",
                                                   extra_headers=[(b"if-none-match", identity_headers[b"etag"])])
        self.assertEqual((status, body), (304, b""))
        self.assertEqual(cached_headers[b"etag"], identity_headers[b"etag"])
        self.assertIn(b"immutable", cached_headers[b"cache-control"])
        self.assertIn(b"Accept-Encoding", cached_headers[b"vary"])


if __name__ == "__main__":
    unittest.main()
