import unittest
from ra_triage_dashboard.app.labeling_summary import summarize_labeling_cases


class LabelingSummaryTest(unittest.TestCase):
    def test_counts_cases_and_deduplicates_authors_and_tags_across_sources(self):
        head = {"author": "Alice", "tags": ["road", "turn"]}
        cases = [{"resolution": {"heads": [head]}}, {"resolution": {"heads": [head]}}]
        result = summarize_labeling_cases([
            {"issue_id": "a", "label_state": "resolved", "gt_label": "误触发", "expected_output": "正确触发", "label_cases": cases},
            {"issue_id": "b", "label_state": "conflict", "gt_label": "误触发", "expected_output": "", "label_cases": cases},
            {"issue_id": "c", "label_state": "pending", "label_cases": []},
            {"issue_id": "d", "label_state": "resolved", "gt_label": "", "expected_output": "无需协助", "label_cases": []},
        ])
        self.assertEqual(result['total'], 4)
        self.assertEqual(result['annotated'], 2)
        self.assertEqual(result['states'], {'resolved': 2, 'conflict': 1, 'pending': 1})
        self.assertEqual(result['pairs'], [{'gt': '误触发', 'label': '正确触发', 'count': 1}])
        self.assertEqual(result['outputs'], {'正确触发': 1, '无需协助': 1})
        self.assertEqual(result['tags'], {'road': 2, 'turn': 2})
        self.assertEqual(result['people'], [{'name': 'alice', 'count': 2}])

    def test_empty_scope_does_not_fabricate_distribution(self):
        data = summarize_labeling_cases([])
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['pairs'], [])
        self.assertEqual(data['people'], [])
        self.assertEqual(data['outputs'], {})
