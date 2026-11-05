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

    def test_graph_compression_identity_and_conditional_cache(self):
        path = "/manual/static/vendor/cron-graph/graph.js"
        status, headers, compressed = self.request(path)
        original = (Path(__file__).resolve().parents[1] / "static/vendor/cron-graph/graph.js").read_bytes()
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"content-encoding"], b"gzip")
        self.assertIn(b"Accept-Encoding", headers[b"vary"])
        self.assertIn(b"immutable", headers[b"cache-control"])
        self.assertIn(b"javascript", headers[b"content-type"])
        self.assertEqual(gzip.decompress(compressed), original)
        self.assertLess(len(compressed), len(original) * .35)
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

    def test_bundle_preserves_manifest_order_compression_and_cache(self):
        static = Path(__file__).resolve().parents[1] / "static"
        names = [line.strip() for line in (static / "js/MANIFEST").read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        expected = b"\n;\n".join((static / "js" / name).read_bytes() for name in names)
        route = "/manual/static/app-bundle.js"
        status, headers, body = self.request(route)
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"content-encoding"], b"gzip")
        self.assertEqual(headers[b"vary"], b"Accept-Encoding")
        self.assertIn(b"immutable", headers[b"cache-control"])
        self.assertEqual(gzip.decompress(body), expected)
        self.assertLess(len(body), len(expected) * .3)
        status, cached_headers, body = self.request(route, extra_headers=[(b"if-none-match", headers[b"etag"])])
        self.assertEqual((status, body), (304, b""))
        for key in (b"etag", b"cache-control", b"vary"):
            self.assertEqual(cached_headers[key], headers[key])
        status, head_headers, body = self.request(route, method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(head_headers[b"content-length"], headers[b"content-length"])
        status, identity_headers, body = self.request(route, encoding="identity")
        self.assertEqual(status, 200)
        self.assertNotIn(b"content-encoding", identity_headers)
        self.assertNotEqual(identity_headers[b"etag"], headers[b"etag"])
        self.assertEqual(body, expected)
        if shutil.which("node"):
            result = subprocess.run(["node", "-e", "new (require('node:vm').Script)(JSON.parse(require('node:fs').readFileSync(0,'utf8')));"],
                                    input=json.dumps(body.decode()), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_bundle_rejects_duplicate_or_unsafe_manifest_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            modules = Path(directory) / "js"
            modules.mkdir()
            for manifest in ("../secret.js\n", "core.js\ncore.js\n", ""):
                (modules / "MANIFEST").write_text(manifest)
                with self.assertRaises(RuntimeError):
                    dashboard_static_app(directory)

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
