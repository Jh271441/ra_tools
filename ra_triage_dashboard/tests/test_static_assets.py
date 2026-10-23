"""Exercise raw ASGI bytes (HTTP clients often transparently decompress them)."""
import asyncio
import gzip
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


if __name__ == "__main__":
    unittest.main()
