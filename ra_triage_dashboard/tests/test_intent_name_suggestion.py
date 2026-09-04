from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ra_triage_dashboard.app.intent_name_suggestion import (
    rule_based_intent_name,
    suggest_intent_name_with_llm,
)


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size):
        return json.dumps({"choices": [{"message": {"content": "推荐名称：0206 Routing 路口复核"}}]}).encode()


class _Opener:
    def open(self, request, timeout):
        assert timeout == 12
        assert request.get_header("Apikey") == "secret"
        return _Response()


class _Catalog:
    def resolve(self, requested, provider_id):
        self.requested = requested
        self.provider_id = provider_id
        return {"resolved_model_id": "Qwen3/test"}


class IntentNameSuggestionTest(unittest.TestCase):
    def test_rule_name_is_immediate_and_descriptive(self):
        self.assertEqual(
            rule_based_intent_name(
                ["0206 · 1335", "0522 · 100"],
                annotation_mode="blind",
                case_count=300,
                overlap_ratio=0.2,
            ),
            "0206+0522 Routing 交叉20%复核 300 Case",
        )

    def test_llm_name_uses_server_owned_gateway_and_normalizes_prefix(self):
        settings = SimpleNamespace(ra_model_default_id="auto")
        catalog = _Catalog()
        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_Opener()),
        ):
            suggestion = suggest_intent_name_with_llm(
                settings,
                catalog,
                fallback="0206 Routing 交叉20%复核 300 Case",
                dataset_labels=["0206 · 1335"],
                annotation_mode="blind",
                case_count=300,
                overlap_ratio=0.2,
                overlap_reviewers=2,
                member_count=4,
                draft_name="0206 复核第二轮",
            )
        self.assertEqual(suggestion, "0206 Routing 路口复核")
        self.assertEqual(catalog.provider_id, "kylin")


if __name__ == "__main__":
    unittest.main()
