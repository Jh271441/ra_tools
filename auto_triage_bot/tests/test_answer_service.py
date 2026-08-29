from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from auto_triage_bot.service import AnswerService


def settings(directory: str):
    return SimpleNamespace(
        dashboard_base_url="http://127.0.0.1:8785",
        dashboard_timeout_seconds=1.0,
        model_id="",
        model_api_key_file=Path(directory) / "key",
        model_chat_url="http://127.0.0.1:9999/v1/chat/completions",
        model_timeout_seconds=1.0,
        model_temperature=0.2,
        max_answer_chars=2800,
        dashboard_review_url="https://auto-triage.intra.xiaojukeji.com/manual/review",
    )


class AnswerServiceTest(unittest.TestCase):
    def test_static_business_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = AnswerService(settings(directory))
            answer = service.answer("正确触发和无需协助怎么区分？")
        self.assertIn("触发后的演化", answer)
        self.assertIn("知识版本", answer)

    def test_issue_fallback_exposes_bound_facts_and_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = AnswerService(settings(directory))
            service.dashboard.get_case = lambda _: {
                "issue_id": "12345678",
                "gt_label": "正确触发",
                "gt_source": "baseline",
                "baseline_scope": "release0508",
                "baseline_id": "0508",
                "predictions": [
                    {
                        "model_run_id": "run-1",
                        "run_name": "model one",
                        "run_is_default": True,
                        "model_label": "无需协助",
                        "model_reason": "constraint cleared",
                    }
                ],
                "annotations": [],
            }
            answer = service.answer("解释 12345678")
        self.assertIn("正确触发", answer)
        self.assertIn("无需协助", answer)
        self.assertIn("run=run-1", answer)
        self.assertIn("没有绑定的人工 Review", answer)


if __name__ == "__main__":
    unittest.main()
