from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from ra_triage_dashboard.app.settings import Settings, _dashboard_return_url


class DashboardReturnURLTest(unittest.TestCase):
    def test_app_id_follows_configured_gateway_and_explicit_override(self) -> None:
        for host, expected in (("auto-triage.intra.xiaojukeji.com", "2103794"),
                               ("ra-model.intra.xiaojukeji.com", "2103860")):
            for override in ("", "12345"):
                with self.subTest(host=host, override=override), tempfile.TemporaryDirectory() as root, patch.dict(
                    os.environ, {"DASHBOARD_DATA_DIR": root, "DASHBOARD_BASE_PATH": "/manual",
                                 "DASHBOARD_KYLIN_SSO_RETURN_URL": f"https://{host}/manual/review",
                                 "DASHBOARD_KYLIN_SSO_APP_ID": override}, clear=True,
                ):
                    settings = Settings.from_env()
                    self.assertEqual(settings.kylin_sso_app_id, override or expected)
                    self.assertEqual(parse_qs(urlparse(settings.kylin_sso_logout_url).query)["app_id"], [override or expected])

    def test_known_gateways_and_base_paths(self) -> None:
        for host in ("auto-triage.intra.xiaojukeji.com", "ra-model.intra.xiaojukeji.com"):
            for base in ("/manual", "/manual-migration"):
                with self.subTest(host=host, base=base):
                    url = f"https://{host}{base}/review"
                    self.assertEqual(_dashboard_return_url("return", url, base), url)

    def test_return_cannot_escape_trusted_gateway_or_base(self) -> None:
        for url in (
            "https://ra-model.intra.xiaojukeji.com.evil.test/manual/review",
            "https://evil.test/manual/review",
            "http://ra-model.intra.xiaojukeji.com/manual/review",
            "https://user@ra-model.intra.xiaojukeji.com/manual/review",
            "https://ra-model.intra.xiaojukeji.com:8443/manual/review",
            "https://ra-model.intra.xiaojukeji.com/manual-migration/review",
            "https://ra-model.intra.xiaojukeji.com/manual/review#other",
        ):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                _dashboard_return_url("return", url, "/manual")


class SeedExampleSettingTest(unittest.TestCase):
    def test_seed_examples_can_be_disabled_for_isolated_smoke_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                "DASHBOARD_DATA_DIR": str(Path(temp_dir) / "data"),
                "DASHBOARD_SEED_EXAMPLES_ENABLED": "false",
            },
            clear=False,
        ):
            self.assertFalse(Settings.from_env().seed_examples_enabled)


if __name__ == "__main__":
    unittest.main()
