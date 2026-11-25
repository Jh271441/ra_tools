"""Phase 3 Strangler-Fig: Vite build manifest loading, HTML injection, cache headers, and React island guards."""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount

from ra_triage_dashboard.app.static_assets import dashboard_static_app
from ra_triage_dashboard.app.vite_assets import load_vite_assets, render_vite_assets_json
from ra_triage_dashboard.app.web_paths import render_index_html


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
FRONTEND_SRC_DIR = Path(__file__).resolve().parents[1] / "frontend" / "src"


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
        self.assertIn('window.__RA_REACT_OWNED_PAGES__ = ["status", "users", "daily-cron", "runs-manager"]', default_html)

        custom_html = render_index_html(
            template,
            "/manual",
            vite_assets_json='{"js":["assets/main-abc.js"],"css":["assets/main-def.css"]}',
        )
        self.assertIn("assets/main-abc.js", custom_html)
        self.assertIn("assets/main-def.css", custom_html)

    def test_built_vite_dist_manifest_cache_headers_and_lazy_chunks(self) -> None:
        assets = load_vite_assets(STATIC_DIR)
        self.assertTrue(assets["js"], "Vite build must produce at least one entry JS bundle")
        self.assertTrue(assets["css"], "Vite build must produce at least one entry CSS bundle")

        app = Starlette(routes=[Mount("/manual/static", app=dashboard_static_app(STATIC_DIR))])

        async def fetch(path: str, query: bytes = b"") -> tuple[int, dict[bytes, bytes]]:
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
                    "query_string": query,
                    "scheme": "http",
                    "http_version": "1.1",
                    "headers": [(b"accept-encoding", b"gzip")],
                },
                receive,
                send,
            )
            return messages[0]["status"], dict(messages[0]["headers"])

        # Classic app-bundle.js and app-bundle.css remain intact for Strangler-Fig parity.
        for classic_path in ("/manual/static/app-bundle.js", "/manual/static/app-bundle.css"):
            status, headers = asyncio.run(fetch(classic_path, b"v=manual-triage-886"))
            self.assertEqual(status, 200, f"Expected HTTP 200 for {classic_path}")
            self.assertIn(b"immutable", headers.get(b"cache-control", b""))

        # Unversioned plain static files must revalidate instead of immutable.
        status, headers = asyncio.run(fetch("/manual/static/styles.css"))
        self.assertEqual(status, 200)
        self.assertIn(b"must-revalidate", headers.get(b"cache-control", b""))

        for rel in [*assets["js"], *assets["css"]]:
            disk_path = STATIC_DIR / "dist" / rel
            self.assertTrue(disk_path.is_file(), f"Missing built Vite asset: {disk_path}")
            status, headers = asyncio.run(fetch(f"/manual/static/dist/{rel}"))
            self.assertEqual(status, 200, f"Expected HTTP 200 for /manual/static/dist/{rel}")
            self.assertIn(b"immutable", headers.get(b"cache-control", b""))

        manifest_data = json.loads(
            (STATIC_DIR / "dist" / ".vite" / "manifest.json").read_text(encoding="utf-8")
        )
        chunk_by_name = {
            entry.get("name"): entry
            for entry in manifest_data.values()
            if isinstance(entry, dict) and entry.get("name")
        }
        for expected_chunk in ("DailyCronPage", "CronGraphCanvas", "RunsManagerIsland"):
            self.assertIn(expected_chunk, chunk_by_name)
            chunk_rel = chunk_by_name[expected_chunk]["file"]
            self.assertTrue((STATIC_DIR / "dist" / chunk_rel).is_file())

    def test_zero_raw_native_select_in_react_islands(self) -> None:
        raw_select_re = re.compile(r"<select\b")
        block_comment_re = re.compile(r"/\*[\s\S]*?\*/")
        line_comment_re = re.compile(r"//.*$", re.MULTILINE)
        offenders: list[str] = []
        for tsx in FRONTEND_SRC_DIR.rglob("*.tsx"):
            if tsx.name.endswith(".test.tsx"):
                continue
            source = tsx.read_text(encoding="utf-8")
            stripped = line_comment_re.sub("", block_comment_re.sub("", source))
            if raw_select_re.search(stripped):
                offenders.append(str(tsx.relative_to(FRONTEND_SRC_DIR)))
        self.assertEqual(offenders, [], f"Raw <select> forbidden in React islands: {offenders}")


if __name__ == "__main__":
    unittest.main()
