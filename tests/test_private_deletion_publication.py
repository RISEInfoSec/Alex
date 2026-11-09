import csv
import json
import os
import subprocess
import sys
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

    def write_canonical(self, rows):
        with (self.root / 'data/accepted_classified.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.rows[0].keys())
            writer.writeheader(); writer.writerows(rows)

    def hold(self, number, title='Held book', year=2024):
        doi = f'10.5281/zenodo.{number}'
        row = dict(title=title, authors='Author', abstract='Held text', year=year,
                   doi=doi, source_url=f'https://example.org/{number}', extra='preserved')
        policy = {'doi': doi, 'status': 'held_pending_supported_type_review',
                  'verified_resource_type': 'Book', 'original_csv_row_sha256': 'a' * 64,
                  'evidence': {'metadata_doi': doi, 'resource_type_general': 'Book',
                               'source_url': 'https://api.datacite.org/dois/' + doi,
                               'body_sha256': 'b' * 64, 'verified_source_receipt': 'verified'},
                  'reason': 'Requires supported-type review'}
        return row, policy

    def write_holds(self, policies):
        path = self.root / 'config/corpus_metadata_holds.json'
        path.write_text(json.dumps({'schema_version': 1, 'authorization': 'test', 'records': policies}))
        return path

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

    def test_public_projection_excludes_held_rows_without_deleting_them(self):
        held = [self.hold(n, title=f'Held book {n}') for n in range(1, 6)]
        original = [held[0][0], self.rows[0], held[1][0], self.rows[1],
                    held[2][0], held[3][0], held[4][0]]
        self.write_canonical(original)
        hold_path = self.write_holds([policy for _, policy in held])
        before_holds = hold_path.read_bytes()
        self.assertEqual(self.run_deletion()['removed'], 1)
        with (self.root / 'data/accepted_classified.csv').open(newline='') as f:
            actual = list(csv.DictReader(f))
        expected = [row for row in original if row is not self.rows[0]]
        self.assertEqual(actual, [{k: str(v) for k, v in row.items()} for row in expected])
        self.assertEqual(hold_path.read_bytes(), before_holds)
        receipt = json.loads((self.root / 'data/deletion_receipts.json').read_text())['records'][self.request]
        self.assertEqual((receipt['records_before'], receipt['records_after']), (7, 6))

    def test_excluded_canonical_row_remains_untouched(self):
        hidden = dict(title='Previously excluded', authors='Carol', abstract='Hidden', year=2023,
                      doi='10.1000/excluded', source_url='https://example.org/excluded', extra='preserved')
        self.write_canonical([hidden, *self.rows])
        exclusion = {'title': hidden['title'], 'year': hidden['year'], 'doi': hidden['doi'],
                     'decision': 'rejected', 'submission_id': 'prior', 'reviewed_content_sha256': 'c' * 64}
        (self.root / 'config/corpus_exclusions.json').write_text(json.dumps({'schema_version': 1, 'records': [exclusion]}))
        self.assertEqual(self.run_deletion()['removed'], 1)
        with (self.root / 'data/accepted_classified.csv').open(newline='') as f:
            actual = list(csv.DictReader(f))
        self.assertEqual(actual, [{k: str(v) for k, v in row.items()} for row in [hidden, self.rows[1]]])

    def test_unaccounted_projection_mismatch_fails_before_any_write(self):
        self.write_canonical([self.rows[0], self.rows[1], dict(self.rows[1], title='Unexpected extra', doi='10.1000/extra')])
        paths = [self.root / 'data/accepted_classified.csv', self.root / 'config/corpus_exclusions.json']
        before = [path.read_bytes() for path in paths]
        with self.assertRaisesRegex(ValueError, 'corpora differ'): self.run_deletion()
        self.assertEqual([path.read_bytes() for path in paths], before)
        self.assertFalse((self.root / 'data/deletion_receipts.json').exists())

    def test_exclusion_collision_with_held_record_is_rejected(self):
        hidden, policy = self.hold(12345, title=self.papers[0]['title'], year=self.papers[0]['year'])
        self.write_canonical([hidden, *self.rows])
        self.write_holds([policy])
        before = (self.root / 'data/accepted_classified.csv').read_bytes()
        with self.assertRaisesRegex(ValueError, 'another record'): self.run_deletion()
        self.assertEqual((self.root / 'data/accepted_classified.csv').read_bytes(), before)

    def test_two_sequential_deletions_preserve_held_record(self):
        hidden, policy = self.hold(12345)
        third = dict(id=3, title='Third record', author='Dana', year=2024.0, doi='10.1000/third',
                     summary='Third content', source_url='https://example.org/third')
        third_row = dict(title=third['title'], authors=third['author'], abstract=third['summary'],
                         year=third['year'], doi=third['doi'], source_url=third['source_url'], extra='preserved')
        self.papers.append(third); self.save_public()
        self.write_canonical([hidden, self.rows[0], self.rows[1], third_row])
        hold_path = self.write_holds([policy]); before_holds = hold_path.read_bytes()
        self.assertEqual(self.run_deletion()['removed'], 1)
        # The real workflow rebuilds the public projection after each deletion.
        self.papers = self.papers[1:]; self.save_public()
        second_request = '22222222-2222-4222-8222-222222222222'
        self.assertEqual(apply(self.root, second_request, key(self.papers[0]), fingerprint(self.papers[0]))['removed'], 1)
        with (self.root / 'data/accepted_classified.csv').open(newline='') as f:
            actual = list(csv.DictReader(f))
        self.assertEqual(actual, [{k: str(v) for k, v in row.items()} for row in [hidden, third_row]])
        self.assertEqual(hold_path.read_bytes(), before_holds)
        self.assertEqual(len(json.loads((self.root / 'config/corpus_exclusions.json').read_text())['records']), 2)

    def test_workflow_event_input_is_not_echoed_in_process_output(self):
        identity, digest = key(self.papers[0]), fingerprint(self.papers[0])
        event = self.root / 'event.json'
        event.write_text(json.dumps({'inputs': {'request_id': self.request, 'identity': identity,
                                               'reviewed_hash': digest}}))
        env = dict(os.environ, GITHUB_EVENT_PATH=str(event))
        script = Path(__file__).resolve().parents[1] / 'scripts/publish_private_deletion.py'
        result = subprocess.run([sys.executable, str(script), '--workflow-event', '--root', str(self.root)],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'removed': 1, 'already_applied': False})
        self.assertNotIn(identity, result.stdout + result.stderr)
        self.assertNotIn(digest, result.stdout + result.stderr)

    def test_bad_workflow_event_fails_before_any_write(self):
        event = self.root / 'event.json'
        event.write_text(json.dumps({'inputs': {'request_id': self.request}}))
        env = dict(os.environ, GITHUB_EVENT_PATH=str(event))
        script = Path(__file__).resolve().parents[1] / 'scripts/publish_private_deletion.py'
        path = self.root / 'data/accepted_classified.csv'
        before = path.read_bytes()
        result = subprocess.run([sys.executable, str(script), '--workflow-event', '--root', str(self.root)],
                                env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / 'data/deletion_receipts.json').exists())


if __name__ == '__main__': unittest.main()
