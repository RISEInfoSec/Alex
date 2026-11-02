import csv
import json
import tempfile
import unittest
from pathlib import Path
from scripts.publish_private_deletion import apply, fingerprint, key


class PrivateDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir(); (self.root / 'config').mkdir()
        self.papers = [dict(id=1, title='Reviewed record', author='Alice', year=2026.0, doi='10.1000/test', summary='Exact reviewed content', source_url='https://example.org/a'),
                       dict(id=2, title='Retained record', author='Bob', year=2025.0, doi='10.1000/keep', summary='Retain every field', source_url='https://example.org/b')]
        self.request = '11111111-1111-4111-8111-111111111111'
        self.save_public()
        self.rows = [dict(title=p['title'], authors=p['author'], abstract=p['summary'], year=p['year'], doi=p['doi'], source_url=p['source_url'], extra='preserved') for p in self.papers]
        with (self.root / 'data/accepted_classified.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.rows[0].keys()); writer.writeheader(); writer.writerows(self.rows)
        (self.root / 'config/corpus_exclusions.json').write_text(json.dumps({'schema_version': 1, 'records': []}))

    def save_public(self):
        (self.root / 'data/papers.json').write_text(json.dumps(self.papers))

    def run_deletion(self):
        return apply(self.root, self.request, key(self.papers[0]), fingerprint(self.papers[0]))

    def test_exact_removal_preserves_other_rows_and_creates_durable_exclusion(self):
        from alex.editorial_exclusions import load_keys, record_keys
        self.assertEqual(self.run_deletion()['removed'], 1)
        with (self.root / 'data/accepted_classified.csv').open(newline='') as f: rows = list(csv.DictReader(f))
        self.assertEqual(rows, [{k: str(v) for k, v in self.rows[1].items()}])
        excluded = load_keys(self.root / 'config/corpus_exclusions.json')
        self.assertTrue(record_keys(self.papers[0]) & excluded)
        self.assertFalse(record_keys(self.papers[1]) & excluded)
        receipt = json.loads((self.root / 'data/deletion_receipts.json').read_text())['records'][self.request]
        self.assertEqual(receipt['records_after'], 1)
        self.assertNotIn('reason', receipt); self.assertNotIn('actor', receipt)

    def test_retry_is_idempotent_after_assets_are_rebuilt(self):
        identity, digest = key(self.papers[0]), fingerprint(self.papers[0])
        self.run_deletion(); self.papers = self.papers[1:]; self.save_public()
        self.assertTrue(apply(self.root, self.request, identity, digest)['already_applied'])
        with self.assertRaisesRegex(ValueError, 'different decision'):
            apply(self.root, self.request, identity, 'f' * 64)

    def test_changed_content_and_unknown_or_ambiguous_identity_fail_before_writes(self):
        before = (self.root / 'data/accepted_classified.csv').read_bytes()
        for identity, digest in [(key(self.papers[0]), 'f' * 64), ('doi:missing', fingerprint(self.papers[0]))]:
            with self.assertRaises(ValueError): apply(self.root, self.request, identity, digest)
        self.papers.append(dict(self.papers[0])); self.save_public()
        with self.assertRaisesRegex(ValueError, 'exactly one'): self.run_deletion()
        self.assertEqual((self.root / 'data/accepted_classified.csv').read_bytes(), before)

    def test_canonical_content_drift_is_rejected(self):
        self.papers[0]['author'] = 'Changed author'; self.save_public()
        with self.assertRaisesRegex(ValueError, 'not aligned'): self.run_deletion()

    def test_exclusion_collision_never_removes_an_extra_record(self):
        self.papers[1]['title'] = self.papers[0]['title']; self.papers[1]['year'] = self.papers[0]['year']; self.save_public()
        # Bring only the canonical title/year in line so the collision guard is exercised.
        path = self.root / 'data/accepted_classified.csv'
        with path.open(newline='') as f: reader = csv.DictReader(f); fields = reader.fieldnames; rows = list(reader)
        rows[1]['title'] = self.papers[1]['title']; rows[1]['year'] = str(self.papers[1]['year'])
        with path.open('w', newline='') as f: writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        with self.assertRaisesRegex(ValueError, 'another record'): self.run_deletion()


if __name__ == '__main__': unittest.main()
