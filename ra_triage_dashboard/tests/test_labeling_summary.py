import unittest
from ra_triage_dashboard.app.labeling_summary import summarize_labeling_cases


class LabelingSummaryTest(unittest.TestCase):
    def test_counts_cases_and_deduplicates_authors_and_tags_across_sources(self):
        head = {
            "author": "Alice",
            "tags": ["road", "turn"],
            "evidence_gaps": ["camera"],
            "rationale": "visible reason",
            "created_at": "2026-09-28T10:00:00+08:00",
        }
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
        self.assertEqual(result['submitted_states'], {'resolved': 1, 'conflict': 1})
        self.assertEqual(result['reason_count'], 2)
        self.assertEqual(result['empty_reason_count'], 0)
        self.assertEqual(result['structured_evidence_count'], 2)
        self.assertEqual(result['pairs'], [{'gt': '误触发', 'label': '正确触发', 'count': 1}])
        self.assertEqual(result['outputs'], {'正确触发': 1, '无需协助': 1})
        self.assertEqual(result['tags'], {'road': 2, 'turn': 2})
        self.assertEqual(result['evidence'], {'camera': 2})
        self.assertEqual(result['people'], [{'name': 'alice', 'count': 2}])
        self.assertEqual([item['issue_id'] for item in result['items']], ['b', 'a'])
        self.assertEqual(result['page_count'], 1)

    def test_reason_detail_is_paginated_over_submitted_cases_only(self):
        items = [
            {
                "issue_id": f"case-{index}",
                "label_state": "resolved",
                "gt_label": "误触发",
                "expected_output": "误触发",
                "label_cases": [{"resolution": {"heads": [{"id": index, "author": "alice"}]}}],
            }
            for index in range(5)
        ]
        items.append({"issue_id": "unsubmitted", "label_state": "pending", "label_cases": []})
        result = summarize_labeling_cases(items, page=2, page_size=2)
        self.assertEqual(result['total'], 6)
        self.assertEqual(result['annotated'], 5)
        self.assertEqual(result['page'], 2)
        self.assertEqual(result['page_count'], 3)
        self.assertEqual(len(result['items']), 2)

    def test_empty_scope_does_not_fabricate_distribution(self):
        data = summarize_labeling_cases([])
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['pairs'], [])
        self.assertEqual(data['people'], [])
        self.assertEqual(data['outputs'], {})
        self.assertEqual(data['items'], [])
        self.assertEqual(data['page_count'], 0)

    def test_task_adjudication_is_primary_and_original_conflict_is_retained(self):
        heads=[{"id":1,"author":"alice","expected_output":"正确触发","rationale":"original a","tags":["old"]},{"id":2,"author":"bob","expected_output":"误触发","rationale":"original b"}]
        resolution={"state":"resolved","method":"adjudication","heads":heads,"result_revision":{"id":3,"author":"carol","expected_output":"误触发","rationale":"final decision","tags":["final"],"evidence_gaps":["camera"],"created_at":"2026-09-30T10:00:00+08:00"}}
        result=summarize_labeling_cases([{"issue_id":"cn1","label_state":"resolved","expected_output":"误触发","gt_label":"正确触发","label_cases":[{"task_id":"task1","resolution":resolution}]}])
        row=result["items"][0]
        self.assertEqual(row["authors"],["carol"])
        self.assertEqual(row["rationales"],["final decision"])
        self.assertEqual(row["tags"],["final"])
        self.assertTrue(row["original_conflict"])
        self.assertEqual(len(row["original_votes"]),2)
        self.assertEqual(row["adjudication"]["kind"],"task")
        self.assertEqual(result["states"],{"resolved":1})
        self.assertEqual(result["adjudicated_count"], 1)
        self.assertEqual(result["tags"], {"final": 1})

    def test_issue_decision_owns_rationale_and_author_without_inventing_tags(self):
        row={"issue_id":"cn1","label_state":"resolved","expected_output":"无需协助","gt_label":"正确触发","decision":{"id":5,"created_by":"judge","created_at":"2026-09-30T10:00:00+08:00","rationale":"final issue decision","stale":False},"label_cases":[{"resolution":{"heads":[{"id":1,"author":"alice","expected_output":"正确触发","tags":["old"],"rationale":"old reason"},{"id":2,"author":"bob","expected_output":"误触发"}]}}]}
        data=summarize_labeling_cases([row]);item=data["items"][0]
        self.assertEqual(item["authors"],["judge"])
        self.assertEqual(data["adjudicated_count"], 1)
        self.assertEqual(item["rationales"],["final issue decision"])
        self.assertEqual(item["tags"],[])
        self.assertTrue(item["original_conflict"])
        row["decision"]["stale"]=True;row["label_state"]="conflict"
        stale=summarize_labeling_cases([row])["items"][0]
        self.assertIsNone(stale["adjudication"])
        self.assertEqual(summarize_labeling_cases([row])["adjudicated_count"], 0)
        self.assertNotIn("final issue decision",stale["rationales"])
