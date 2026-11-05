"""Check wire bytes and policies; HTTP clients usually auto-decompress gzip."""
import asyncio
import gzip
import unittest

from ra_triage_dashboard.app.response_compression import TextResponseCompressionMiddleware


class TextResponseCompressionTest(unittest.TestCase):
    def request(self, *, content_type="application/json", encoding="gzip", status=200,
                method="GET", body=b'{"items": "' + b"example " * 2000 + b'"}',
                headers=(), request_headers=(), streaming=False):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": status, "headers": [
                (b"content-type", content_type.encode()), (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"private, no-store, max-age=0"),
                (b"vary", b"Cookie"), (b"x-content-type-options", b"nosniff"), *headers,
            ]})
            if streaming:
                await send({"type": "http.response.body", "body": body[:10], "more_body": True})
                await send({"type": "http.response.body", "body": body[10:]})
            else:
                await send({"type": "http.response.body", "body": body if method != "HEAD" else b""})
        async def run():
            messages = []
            async def receive():
                return {"type": "http.request", "body": b""}
            async def send(message):
                messages.append(message)
            await TextResponseCompressionMiddleware(app)(
                {"type": "http", "method": method, "headers": [
                    (b"accept-encoding", encoding.encode()), *request_headers,
                ]}, receive, send,
            )
            return dict(messages[0]["headers"]), b"".join(m.get("body", b"") for m in messages)
        return body, *asyncio.run(run())

    def test_html_and_json_reduce_wire_bytes_and_preserve_private_policy(self):
        for mime in ("application/json", "text/html; charset=utf-8"):
            original, headers, body = self.request(content_type=mime, headers=[(b"etag", b'"version"')])
            self.assertEqual(gzip.decompress(body), original)
            self.assertLess(len(body), len(original) / 10)
            self.assertEqual(headers[b"content-encoding"], b"gzip")
            self.assertEqual(int(headers[b"content-length"]), len(body))
            self.assertEqual(headers[b"cache-control"], b"private, no-store, max-age=0")
            self.assertEqual(headers[b"vary"], b"Cookie, Accept-Encoding")
            self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
            self.assertEqual(headers[b"etag"], b'W/"version"')

    def test_identity_quality_zero_and_wildcard_negotiation(self):
        for encoding in ("identity", "br", "gzip;q=0, *;q=1", "gzip;q=invalid"):
            original, headers, body = self.request(encoding=encoding)
            self.assertEqual(body, original)
            self.assertNotIn(b"content-encoding", headers)
            self.assertIn(b"Accept-Encoding", headers[b"vary"])
        for encoding in ("br, gzip;q=0.5", "*;q=1"):
            original, _, body = self.request(encoding=encoding)
            self.assertEqual(gzip.decompress(body), original)

    def test_media_downloads_ranges_streams_and_small_payloads_pass_through(self):
        variants = [
            {"content_type": "video/mp4"}, {"content_type": "image/png"},
            {"content_type": "text/event-stream"}, {"streaming": True},
            {"headers": [(b"content-disposition", b'attachment; filename="export.json"')]},
            {"headers": [(b"content-range", b"bytes 0-1023/2048")], "status": 206},
            {"headers": [(b"content-encoding", b"br")]},
            {"request_headers": [(b"range", b"bytes=0-1023")]},
            {"body": b'{"revision": 1}'}, {"status": 304, "body": b""},
            {"method": "POST"},
        ]
        for options in variants:
            with self.subTest(options=options):
                original, headers, body = self.request(**options)
                self.assertEqual(body, original)
                self.assertNotEqual(headers.get(b"content-encoding"), b"gzip")
        original, headers, body = self.request(method="HEAD")
        self.assertEqual(body, b"")
        self.assertEqual(int(headers[b"content-length"]), len(original))


if __name__ == "__main__":
    unittest.main()
