import copy
import unittest
from tools.content_review.stage_summary import derive, validate_summary

class StageSummaryTests(unittest.TestCase):
    def test_all_collections_and_unknowns_preserved(self):
        rows = [{'collection': c, 'checks': {'format': {'status': 'passed'}, 'quality': {'status': 'unknown'}}}
                for c in ('weekly', 'soups', 'first', 'm3aawg', 'bellingcat', 'sans', 'virusbulletin')]
        before = copy.deepcopy(rows)
        summary = derive(rows)
        self.assertEqual(set(summary), {r['collection'] for r in rows})
        self.assertTrue(all(s['quality'] == {'unknown': 1} and s['schema'] == {'not_checked': 1} for s in summary.values()))
        self.assertEqual(rows, before)
        validate_summary({'records': rows, 'summary': summary})
        with self.assertRaises(ValueError):
            validate_summary({'records': rows, 'summary': {'weekly': {}}})

    def test_mixed_gate_counts_and_empty(self):
        rows = [{'collection': 'weekly', 'checks': {'access': {'status': status}}} for status in ('passed', 'held', 'passed')]
        self.assertEqual(derive(rows)['weekly']['access'], {'held': 1, 'passed': 2})
        self.assertEqual(derive([]), {})

if __name__ == '__main__':
    unittest.main()
