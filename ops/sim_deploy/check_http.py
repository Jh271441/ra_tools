"""HTTP contract checks for direct and prefix-stripping gateway deployments."""

import json
import re
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_http(base_url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(path):
        request = urllib.request.Request(
            base_url + path,
            headers={
                "Host": "dashboard.example.internal",
                "X-Forwarded-Proto": "https",
            },
        )
        try:
            response = opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    for path, expected in (("/sim", "/sim/overview"), ("/sim/weekly", "/sim/weekly/")):
        status, headers, _ = get(path)
        if status not in (301, 302, 307, 308) or headers.get("Location") != expected:
            raise RuntimeError(
                f"Bad relative redirect for {path}: {status}, {headers.get('Location')}"
            )

    status, headers, body = get("/sim/overview")
    if status != 200 or "text/html" not in headers.get("Content-Type", ""):
        raise RuntimeError("Overview is not an HTML page")
    assets = re.findall(r'(?:src|href)="(/sim/assets/[^\"]+)"', body.decode())
    if not assets:
        raise RuntimeError("No built frontend assets in overview")
    for path in ("/sim/overview", "/sim/issues", "/sim/status", *assets):
        canonical = get(path)
        stripped = get(path[4:])
        if canonical[0] != 200 or stripped[0] != 200 or canonical[2] != stripped[2]:
            raise RuntimeError(f"Prefix-stripping gateway mismatch: {path}")
        if path in assets:
            content_type = canonical[1].get("Content-Type", "")
            expected_type = "css" if path.endswith(".css") else "javascript"
            if expected_type not in content_type:
                raise RuntimeError(f"Asset returned wrong content type: {path}")
    for prefix in ("/sim", ""):
        for suffix in (
            "/api/health",
            "/api/dashboard/versions",
            "/api/dashboard/summary",
        ):
            status, headers, body = get(prefix + suffix)
            if status != 200 or "application/json" not in headers.get(
                "Content-Type", ""
            ):
                raise RuntimeError(f"API is not healthy: {prefix}{suffix}")
            json.loads(body)
    print("Direct and prefix-stripped pages, assets, APIs and relative redirects: OK")
