"""Contracts for standalone architecture artifact routes and static exports."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

from ra_triage_dashboard.app.web_paths import BASE_PATH_TOKEN, render_index_html


DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = DASHBOARD_ROOT / "static"
ARTIFACT_DIR = STATIC_DIR / "artifacts" / "architecture-original-330"


class ArchitectureArtifactContractTest(unittest.TestCase):
    def test_artifact_files_exist_and_avoid_external_cdns(self) -> None:
        html_path = ARTIFACT_DIR / "index.html"
        png_path = ARTIFACT_DIR / "original330_vlm_flowchart.png"
        svg_path = ARTIFACT_DIR / "original330_vlm_flowchart.svg"

        self.assertTrue(html_path.is_file())
        self.assertTrue(png_path.is_file())
        self.assertTrue(svg_path.is_file())

        html = html_path.read_text(encoding="utf-8")
        self.assertIn(BASE_PATH_TOKEN, html)
        for forbidden_cdn in (
            "gstatic.com",
            "googleapis.com",
            "unpkg.com",
            "jsdelivr.net",
            "cdnjs.cloudflare.com",
        ):
            self.assertNotIn(forbidden_cdn, html)

        self.assertTrue(png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        svg_text = svg_path.read_text(encoding="utf-8")
        self.assertIn("<svg", svg_text)
        self.assertIn("Original330", svg_text)

    def test_base_path_rendering_and_workbench_isolation(self) -> None:
        template = (ARTIFACT_DIR / "index.html").read_text(encoding="utf-8")
        root_html = render_index_html(template, "")
        manual_html = render_index_html(template, "/manual/")

        self.assertIn('<meta name="ra-triage-base" content="" />', root_html)
        self.assertIn('<meta name="ra-triage-base" content="/manual" />', manual_html)
        self.assertNotIn(BASE_PATH_TOKEN, root_html)
        self.assertNotIn(BASE_PATH_TOKEN, manual_html)

        # Artifact route must stay out of the Manual Workbench shell navigation.
        workbench_index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("architecture-original-330", workbench_index)

    @unittest.skipUnless(
        sys.version_info >= (3, 10)
        and importlib.util.find_spec("starlette") is not None
        and importlib.util.find_spec("fastapi") is not None,
        "Python 3.10+ with starlette/fastapi runtime required",
    )
    def test_static_assets_and_router_serve_over_asgi(self) -> None:
        from fastapi import FastAPI
        from starlette.applications import Starlette
        from starlette.routing import Mount

        from ra_triage_dashboard.app.routers import artifacts
        from ra_triage_dashboard.app.static_assets import dashboard_static_app

        async def asgi_get(app_obj, path: str) -> tuple[int, dict[bytes, bytes], bytes]:
            messages: list[dict] = []

            async def receive() -> dict:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: dict) -> None:
                messages.append(message)

            await app_obj(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "method": "GET",
                    "path": path,
                    "raw_path": path.encode("utf-8"),
                    "root_path": "",
                    "query_string": b"",
                    "scheme": "http",
                    "http_version": "1.1",
                    "headers": [(b"accept-encoding", b"identity")],
                },
                receive,
                send,
            )
            status = messages[0]["status"]
            headers = dict(messages[0]["headers"])
            body = b"".join(m.get("body", b"") for m in messages)
            return status, headers, body

        route_app = FastAPI()
        route_app.include_router(artifacts.router)
        for route_path in ("/architecture-original-330", "/architecture-original-330/"):
            status, headers, body = asyncio.run(asgi_get(route_app, route_path))
            self.assertEqual(status, 200)
            self.assertIn(b"text/html", headers.get(b"content-type", b""))
            self.assertEqual(headers.get(b"cache-control"), b"no-store, max-age=0")
            self.assertIn(b"Original330 VLM", body)

        static_app = Starlette(
            routes=[Mount("/manual/static", app=dashboard_static_app(STATIC_DIR))]
        )
        for filename, expected_mime in (
            ("original330_vlm_flowchart.png", b"image/png"),
            ("original330_vlm_flowchart.svg", b"image/svg+xml"),
        ):
            status, headers, body = asyncio.run(
                asgi_get(
                    static_app,
                    f"/manual/static/artifacts/architecture-original-330/{filename}",
                )
            )
            self.assertEqual(status, 200)
            self.assertIn(expected_mime, headers.get(b"content-type", b""))
            self.assertIn(b"immutable", headers.get(b"cache-control", b""))
            self.assertEqual(body, (ARTIFACT_DIR / filename).read_bytes())


if __name__ == "__main__":
    unittest.main()
