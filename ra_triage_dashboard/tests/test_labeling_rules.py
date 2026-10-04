import unittest
from ra_triage_dashboard.app.labeling_rules import current_adjudication
from ra_triage_dashboard.app.db_parts.assignment_rules import legacy_batch_source


class LabelingRulesTest(unittest.TestCase):
    def test_current_issue_decision_precedes_tasks_without_copying_task_tags(self):
        item = self.item()
        item['decision'] = {'id': 8, 'created_by': 'judge', 'rationale': 'issue final'}
        result = current_adjudication(item)
        self.assertEqual((result['kind'], result['author'], result['tags']), ('issue', 'judge', []))

    def test_latest_matching_task_wins_and_unresolved_projection_never_adjudicated(self):
        item = self.item()
        item['decision'] = {'id': 8, 'stale': True}
        self.assertEqual(current_adjudication(item)['id'], 3)
        for state in ['conflict', 'pending', 'stale']:
            with self.subTest(state=state):
                item['label_state'] = state
                self.assertIsNone(current_adjudication(item))

    @staticmethod
    def item():
        return {'label_state': 'resolved', 'expected_output': '误触发', 'label_cases': [
            {'task_id': str(i), 'resolution': {'state': 'resolved', 'method': 'adjudication',
             'result_revision': {'id': i, 'author': 'alice', 'expected_output': output, 'tags': ['x']}}}
            for i, output in [(1, '误触发'), (3, '误触发'), (7, '正确触发')]
        ]}

    def test_legacy_source_requires_exact_run_and_known_provenance(self):
        batch = {'model_run_id': 'run-a', 'filter_json': '{"source_legacy_split_id":"old"}'}
        source = {'id': 'old', 'model_run_id': 'run-a', 'created_by': 'alice'}
        self.assertEqual(legacy_batch_source(batch, {'old': source}), source)
        self.assertEqual(legacy_batch_source(batch, {}), {})
        self.assertEqual(legacy_batch_source(batch, {'old': {**source, 'model_run_id': 'run-b'}}), {})
