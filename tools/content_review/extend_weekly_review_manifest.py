"""Reproduce the 150-record extension while preserving the initial 138 records.

Pass the complete newly prepared SOUPS manifest as an optional first argument.
No corpus or remote writes occur.
"""
import json
import sys
from pathlib import Path
from build_weekly_review_manifest import build

original = json.loads(Path('/tmp/weekly-ready-manifest.json').read_text())['records']
extra = sys.argv[1:]
build(150, '/tmp/weekly-ready-150.json', 'weekly_preparation_receipt_150.json', extra)
extended = json.loads(Path('/tmp/weekly-ready-150.json').read_text())['records']
assert len(extended) == 150
assert extended[:138] == original, 'Initial assessed records changed or dedupe uncovered a conflict'
assert len({r['candidate_id'] for r in extended}) == 150
assert [r['review_number'] for r in extended] == list(range(1, 151))
assert all(r['decision'] == 'pending' and not r['publication_approved'] for r in extended)
print('Validated 150 records; first 138 objects are unchanged.')
