from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ra_triage_dashboard.app.intent_name_suggestion import (
    IntentNameSuggestionError,
    rule_based_assignment_name,
    rule_based_intent_name,
    suggest_assignment_name_with_llm,
    suggest_intent_name_with_llm,
)


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size):
        return json.dumps({"choices": [{"message": {"content": "推荐名称：0206 Routing 路口交叉20%复核 300 Case"}}]}).encode()


class _Opener:
    def open(self, request, timeout):
        body = json.loads(request.data)
        assignment = "Case 标注和模型复核" in body["messages"][0]["content"]
        assert timeout == (15 if assignment else 8)
        assert body["max_tokens"] == (128 if assignment else 64)
        assert request.get_header("Apikey") == "secret"
        assert json.loads(request.data)["model"] == "Qwen3.8-27B/Qwen3.8-27B"
        return _Response()


class _Catalog:
    def resolve(self, requested, provider_id):
        self.requested = requested
        self.provider_id = provider_id
        return {"resolved_model_id": "Qwen3/test"}


class IntentNameSuggestionTest(unittest.TestCase):
    def test_case_assignment_rule_name_is_immediate_and_descriptive(self):
        self.assertEqual(
            rule_based_assignment_name(
                ["0508 · 1071"],
                assignment_kind="case_labeling",
                case_count=1071,
                reviewers_per_issue=1,
                overlap_ratio=0,
                member_count=1,
            ),
            "0508 Case标注 单人均分 1071 Case",
        )

    def test_assignment_rule_name_tracks_member_configuration(self):
        self.assertEqual(
            rule_based_assignment_name(
                ["0508 · 1071"], assignment_kind="case_labeling",
                case_count=1071, reviewers_per_issue=1,
                overlap_ratio=0, member_count=0,
            ),
            "0508 Case标注 待选人员 1071 Case",
        )
        self.assertEqual(
            rule_based_assignment_name(
                ["0508 · 1071"], assignment_kind="case_labeling",
                case_count=1071, reviewers_per_issue=1,
                overlap_ratio=0, member_count=2,
            ),
            "0508 Case标注 2人均分 1071 Case",
        )

    def test_model_review_rule_name_keeps_run_scope_and_comparison(self):
        self.assertEqual(
            rule_based_assignment_name(
                ["0508 · 1071"],
                assignment_kind="model_review",
                case_count=211,
                reviewers_per_issue=2,
                overlap_ratio=0.5,
                member_count=4,
                workflow_mode="model_review_and_case_label",
                run_name="H2 + original330 · 0508",
                comparison="mismatch",
            ),
            "0508 H2 + original330 联合复核 MISMATCH 2人交叉50%复核 211 Case",
        )

    def test_assignment_llm_name_is_validated(self):
        class _AssignmentResponse(_Response):
            def read(self, _size):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "0508 H2 联合复核 MISMATCH 2人交叉50%复核 211 Case"
                                }
                            }
                        ]
                    }
                ).encode()

        class _AssignmentOpener(_Opener):
            def open(self, request, timeout):
                super().open(request, timeout)
                return _AssignmentResponse()

        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_AssignmentOpener()),
        ):
            suggestion = suggest_assignment_name_with_llm(
                SimpleNamespace(ra_model_default_id="auto"),
                _Catalog(),
                fallback="0508 H2 + original330 联合复核 MISMATCH 2人交叉50%复核 211 Case",
                dataset_labels=["0508 · 1071"],
                assignment_kind="model_review",
                case_count=211,
                reviewers_per_issue=2,
                overlap_ratio=0.5,
                member_count=4,
                workflow_mode="model_review_and_case_label",
                run_name="H2 + original330 · 0508",
                comparison="mismatch",
            )
        self.assertEqual(
            suggestion,
            "0508 H2 联合复核 MISMATCH 2人交叉50%复核 211 Case",
        )

    def test_assignment_accepts_valid_unchanged_output_but_rejects_wrong_allocation(self):
        kwargs = dict(
            fallback="0508 Case标注 2人均分 1071 Case", dataset_labels=["0508"],
            assignment_kind="case_labeling", case_count=1071, reviewers_per_issue=1,
            overlap_ratio=0, member_count=2,
        )
        with patch("ra_triage_dashboard.app.intent_name_suggestion._request_name_completion", return_value=kwargs["fallback"]) as call:
            self.assertEqual(suggest_assignment_name_with_llm(SimpleNamespace(), _Catalog(), **kwargs), kwargs["fallback"])
            self.assertIn('"2人均分"', call.call_args.kwargs["prompt"])
        with patch("ra_triage_dashboard.app.intent_name_suggestion._request_name_completion", return_value="0508 Case标注 1071Case 单人"):
            with self.assertRaises(IntentNameSuggestionError) as error:
                suggest_assignment_name_with_llm(SimpleNamespace(), _Catalog(), **kwargs)
            self.assertEqual(error.exception.reason, "invalid_output")

    def test_assignment_timeout_has_a_safe_reason(self):
        from ra_triage_dashboard.app.intent_name_suggestion import _request_name_completion
        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener") as opener,
        ):
            opener.return_value.open.side_effect = TimeoutError("private transport detail")
            with self.assertRaises(IntentNameSuggestionError) as error:
                _request_name_completion(SimpleNamespace(), prompt="test", system_prompt="test")
            self.assertEqual(error.exception.reason, "timeout")
            self.assertNotIn("private transport detail", str(error.exception))

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
        self.assertEqual(suggestion, "0206 Routing 路口交叉20%复核 300 Case")

    def test_rule_name_does_not_claim_cross_review_with_one_reviewer(self):
        self.assertEqual(
            rule_based_intent_name(
                ["0206 · 1335"],
                annotation_mode="blind",
                case_count=1335,
                overlap_ratio=0.2,
                overlap_reviewers=1,
                member_count=4,
            ),
            "0206 Routing 分工盲标 1335 Case",
        )

    def test_llm_name_rejects_missing_experiment_facts(self):
        class _AbnormalResponse(_Response):
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": "R0206-RI-300-BR20"}}]}).encode()

        class _AbnormalOpener(_Opener):
            def open(self, request, timeout):
                return _AbnormalResponse()

        settings = SimpleNamespace(ra_model_default_id="auto")
        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_AbnormalOpener()),
        ):
            with self.assertRaisesRegex(IntentNameSuggestionError, "缺少实验关键信息"):
                suggest_intent_name_with_llm(
                    settings,
                    _Catalog(),
                    fallback="0206 Routing 交叉20%复核 300 Case",
                    dataset_labels=["0206 · 1335"],
                    annotation_mode="blind",
                    case_count=300,
                    overlap_ratio=0.2,
                    overlap_reviewers=2,
                    member_count=4,
                )

    def test_llm_name_uses_the_low_latency_kylin_model(self):
        settings = SimpleNamespace(ra_model_default_id="auto")
        with (
            patch("ra_triage_dashboard.app.intent_name_suggestion.read_provider_api_key", return_value="secret"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.model_gateway_chat_url", return_value="http://ra-model.intra.xiaojukeji.com/v1/chat/completions"),
            patch("ra_triage_dashboard.app.intent_name_suggestion.build_opener", return_value=_Opener()),
        ):
            suggestion = suggest_intent_name_with_llm(
                settings,
                _Catalog(),
                fallback="0206 Routing 交叉20%复核 300 Case",
                dataset_labels=["0206 · 1335"],
                annotation_mode="blind",
                case_count=300,
                overlap_ratio=0.2,
                overlap_reviewers=2,
                member_count=4,
            )
        self.assertEqual(suggestion, "0206 Routing 路口交叉20%复核 300 Case")


if __name__ == "__main__":
    unittest.main()
