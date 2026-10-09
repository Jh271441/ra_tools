from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ra_triage_dashboard.app.settings import Settings


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
