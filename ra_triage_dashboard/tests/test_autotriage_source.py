from __future__ import annotations

import unittest

from ra_triage_dashboard.app.autotriage_source import (
    AutoTriageSource,
    AutoTriageSourceError,
    normalise_batch_id,
)


class AutoTriageSourceTest(unittest.TestCase):
    def test_batch_id_accepts_id_or_record_link_without_using_link_host(self) -> None:
        self.assertEqual(normalise_batch_id("761"), "761")
        self.assertEqual(
            normalise_batch_id(
                "http://auto-triage.intra.xiaojukeji.com/"
                "ra/model_triage/records/761?tab=results"
            ),
            "761",
        )
        with self.assertRaises(AutoTriageSourceError):
            normalise_batch_id("0")

    def test_source_host_is_fixed_and_response_shape_is_checked(self) -> None:
        with self.assertRaises(RuntimeError):
            AutoTriageSource("https://example.com")
        with self.assertRaises(RuntimeError):
            AutoTriageSource("http://10.190.57.183:9000")
        source = AutoTriageSource("http://10.190.57.183:8000")
        source._get_json = lambda path: {  # type: ignore[method-assign]
            "success": True,
            "data": {"id": 761, "batch_name": "demo"},
        }
        self.assertEqual(source.fetch_batch("761")["batch_name"], "demo")
        source._get_json = lambda path: {  # type: ignore[method-assign]
            "success": True,
            "data": [{"issue_id": "cn123"}],
        }
        self.assertEqual(source.fetch_results("761")[0]["issue_id"], "cn123")

    def test_redirecting_or_invalid_payload_is_not_accepted(self) -> None:
        source = AutoTriageSource("http://10.190.57.183:8000")
        source._get_json = lambda path: {  # type: ignore[method-assign]
            "success": False,
            "data": [],
        }
        with self.assertRaises(AutoTriageSourceError):
            source.fetch_results("761")
