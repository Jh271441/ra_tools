from __future__ import annotations

import unittest
from pathlib import Path

from ra_triage_dashboard.app.web_paths import (
    normalize_base_path,
    render_index_html,
    with_base_path,
)


INDEX_HTML = (
    Path(__file__).resolve().parents[1] / "static" / "index.html"
).read_text(encoding="utf-8")


class BasePathTest(unittest.TestCase):
    def test_normalizes_root_and_trailing_slash(self) -> None:
        self.assertEqual(normalize_base_path(""), "")
        self.assertEqual(normalize_base_path("/"), "")
        self.assertEqual(normalize_base_path("/dashboard/"), "/dashboard")
        self.assertEqual(normalize_base_path("/manual/"), "/manual")
        self.assertEqual(normalize_base_path("/tools/ra_triage"), "/tools/ra_triage")

    def test_rejects_unsafe_or_ambiguous_values(self) -> None:
        for value in (
            "dashboard",
            "http://example.test/dashboard",
            "/dashboard path",
            "/dashboard/../admin",
            "/dashboard..",
            "/dashboard//admin",
        ):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    normalize_base_path(value)

    def test_with_base_path_is_root_compatible_and_idempotent(self) -> None:
        self.assertEqual(with_base_path("", "/api/status"), "/api/status")
        self.assertEqual(
            with_base_path("/dashboard", "/api/status"),
            "/dashboard/api/status",
        )
        self.assertEqual(
            with_base_path("/manual", "/api/status"),
            "/manual/api/status",
        )
        self.assertEqual(
            with_base_path("/dashboard", "/dashboard/api/status"),
            "/dashboard/api/status",
        )
        self.assertEqual(
            with_base_path("/dashboard", "https://example.test/resource"),
            "https://example.test/resource",
        )

    def test_shell_injection_covers_assets_and_navigation(self) -> None:
        root_shell = render_index_html(INDEX_HTML, "")
        self.assertIn('content=""', root_shell)
        self.assertIn('styles.href = `${activeBase}/static/styles.css', root_shell)
        self.assertIn('html.ra-styles-loading body { visibility: hidden; }', root_shell)
        self.assertIn('styles.addEventListener("load", revealShell', root_shell)
        self.assertIn('styles.addEventListener("error", revealShell', root_shell)
        self.assertIn('window.setTimeout(revealShell, 5000)', root_shell)
        self.assertIn('data-app-path="/review"', root_shell)
        self.assertNotIn("{{RA_TRIAGE_BASE_PATH}}", root_shell)

        subpath_shell = render_index_html(INDEX_HTML, "/manual/")
        self.assertIn('content="/manual"', subpath_shell)
        self.assertIn('window.__RA_TRIAGE_BASE__ = activeBase', subpath_shell)
        self.assertIn('`${window.__RA_TRIAGE_BASE__ || ""}${link.dataset.appPath}`', subpath_shell)
        self.assertIn('/static/styles.css?v=manual-triage-149', subpath_shell)
        self.assertIn('/static/app.js?v=manual-triage-149', subpath_shell)


if __name__ == "__main__":
    unittest.main()
