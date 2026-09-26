import io
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from check_http import verify_http


class Response(io.BytesIO):
    def __init__(self, body, status=200, content_type="text/html", **headers):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Type": content_type, **headers}


class HttpContractTests(unittest.TestCase):
    def run_check(self, broken=None):
        def open_request(request, timeout):
            path = urlsplit(request.full_url).path
            if broken and path == broken[0]:
                return broken[1]()
            canonical = path[4:] if path.startswith("/sim/") else path
            if path in ("/sim", "/sim/weekly"):
                target = "/sim/overview" if path == "/sim" else "/sim/weekly/"
                return Response(b"", status=302, Location=target)
            if canonical.startswith("/api/"):
                return Response(
                    json.dumps({"ok": True}).encode(), content_type="application/json"
                )
            if canonical.startswith("/assets/"):
                return Response(
                    b"console.log(1)", content_type="application/javascript"
                )
            return Response(b'<script src="/sim/assets/app.js"></script>')

        with patch("check_http.urllib.request.build_opener") as build:
            build.return_value.open.side_effect = open_request
            verify_http("http://127.0.0.1:8787")

    def test_both_path_styles_and_relative_redirects(self):
        self.run_check()

    def test_rejects_backend_port_redirect(self):
        with self.assertRaisesRegex(RuntimeError, "redirect"):
            self.run_check(
                (
                    "/sim",
                    lambda: Response(
                        b"", status=302, Location="http://example:8787/sim/overview"
                    ),
                )
            )

    def test_rejects_stripped_asset_404(self):
        with self.assertRaisesRegex(RuntimeError, "gateway mismatch"):
            self.run_check(
                ("/assets/app.js", lambda: Response(b"not found", status=404))
            )

    def test_rejects_html_returned_as_api(self):
        with self.assertRaisesRegex(RuntimeError, "API is not healthy"):
            self.run_check(("/api/health", lambda: Response(b"<html>fallback</html>")))


if __name__ == "__main__":
    unittest.main()
