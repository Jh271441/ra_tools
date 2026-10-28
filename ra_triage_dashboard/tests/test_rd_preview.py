"""Preview-only synthetic data is independent from model/combined review results."""
import unittest
from ra_triage_dashboard.tests.preview_version_filters import preview_rd_summary


class RDPreviewTest(unittest.TestCase):
    def test_partition_and_independent_labels(self):
        rows = [dict(issue_id=f'cn9000{i:03}', review_submitted=True,
                     prediction={'model_label': '误触发'}) for i in range(1, 25)]
        result = preview_rd_summary(rows)
        self.assertEqual(result['completed'], 13)
        self.assertEqual(result['pending'], 8)
        self.assertEqual(result['conflict'], 3)
        self.assertEqual(sum(result['distribution'].values()), result['completed'])
        self.assertEqual(result['completed'] + result['pending'] + result['conflict'], result['total'])
        self.assertTrue(result['synthetic'])

    def test_empty(self):
        result = preview_rd_summary([])
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['completed'], 0)

    def test_sample_subset(self):
        result = preview_rd_summary([{'issue_id': f'cn9000{i:03}'} for i in range(3,25,3)])
        self.assertEqual((result['completed'], result['total']), (5,8))
