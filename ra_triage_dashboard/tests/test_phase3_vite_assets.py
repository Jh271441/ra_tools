"""Phase 3 Wave 3.1: Vite build manifest loading, HTML injection, and dist serving."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount

from ra_triage_dashboard.app.static_assets import dashboard_static_app
from ra_triage_dashboard.app.vite_assets import load_vite_assets, render_vite_assets_json
from ra_triage_dashboard.app.web_paths import render_index_html


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


class Phase3ViteAssetsTest(unittest.TestCase):
    def test_load_vite_assets_handles_missing_manifest_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_vite_assets(tmp), {"js": [], "css": []})
            self.assertEqual(render_vite_assets_json(tmp), '{"js":[],"css":[]}')

    def test_load_vite_assets_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "dist" / ".vite" / "manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"src/main.tsx": {"file": "../escape.js", "isEntry": True}}),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_vite_assets(tmp)

    def test_render_index_html_injects_vite_assets_and_preserves_two_arg_contract(self) -> None:
        template = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        default_html = render_index_html(template, "/manual")
        self.assertIn('id="raViteAssets"', default_html)
        self.assertIn('{"js":[],"css":[]}', default_html)
        self.assertNotIn("{{RA_TRIAGE_VITE_ASSETS}}", default_html)

        custom_html = render_index_html(
            template,
            "/manual",
            vite_assets_json='{"js":["assets/main-abc.js"],"css":["assets/main-def.css"]}',
        )
        self.assertIn("assets/main-abc.js", custom_html)
        self.assertIn("assets/main-def.css", custom_html)

    def test_built_vite_dist_manifest_and_gzip_serving(self) -> None:
        assets = load_vite_assets(STATIC_DIR)
        self.assertTrue(assets["js"], "Vite build must produce at least one entry JS bundle")
        self.assertTrue(assets["css"], "Vite build must produce at least one entry CSS bundle")

        app = Starlette(routes=[Mount("/manual/static", app=dashboard_static_app(STATIC_DIR))])

        async def fetch(path: str) -> tuple[int, dict[bytes, bytes]]:
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(msg):
                messages.append(msg)

            await app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "method": "GET",
                    "path": path,
                    "raw_path": path.encode(),
                    "root_path": "",
                    "query_string": b"",
                    "scheme": "http",
                    "http_version": "1.1",
                    "headers": [(b"accept-encoding", b"gzip")],
                },
                receive,
                send,
            )
            return messages[0]["status"], dict(messages[0]["headers"])

        for rel in [*assets["js"], *assets["css"]]:
            disk_path = STATIC_DIR / "dist" / rel
            self.assertTrue(disk_path.is_file(), f"Missing built Vite asset: {disk_path}")
            status, headers = asyncio.run(fetch(f"/manual/static/dist/{rel}"))
            self.assertEqual(status, 200, f"Expected HTTP 200 for /manual/static/dist/{rel}")
            self.assertIn(b"immutable", headers.get(b"cache-control", b""))


if __name__ == "__main__":
    unittest.main()
