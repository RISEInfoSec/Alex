"""Audit reusable Crossref outcomes independently of legacy harvest completion."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from alex.pipelines.harvest import _is_crossref_indexed_doi
from alex.utils.harvest_checkpoint import digest, file_sha256
from alex.utils.io import load_df, validate_columns
from alex.utils.text import clean


def _events(checkpoint: Path, input_sha256: str):
    outcomes = {}
    with checkpoint.open(encoding='utf-8') as stream:
        first = next(stream, '')
        header = json.loads(first)
        if not first.endswith('\n') or header.get('schema_version') != 1 or header.get('input_sha256') != input_sha256:
            raise ValueError('Saved outcomes do not bind to this exact harvest input')
        for raw in stream:
            row = json.loads(raw)
            if not raw.endswith('\n') or not isinstance(row, dict):
                raise ValueError('Saved outcome is incomplete')
            event = row.get('event')
            if event in ('begin', 'complete'):
                # These markers do not establish completion in a record-level replay.
                continue
            if event == 'response' and isinstance(row.get('response'), dict):
                fields = ('request_sha256', 'response')
            elif event == 'not_found' and row.get('http_status') == 404 and isinstance(row.get('evidence'), dict):
                fields = ('request_sha256', 'http_status', 'evidence')
            else:
                raise ValueError('Saved outcome type is unverified')
            key = row.get('request_sha256')
            if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key) or digest({k: row[k] for k in fields}) != row.get('sha256'):
                raise ValueError('Saved outcome hash does not match')
            if key in outcomes and outcomes[key]['sha256'] != row['sha256']:
                raise ValueError('Saved request has conflicting outcomes')
            outcomes[key] = row
    return outcomes


def reconcile(input_csv: Path, checkpoint: Path):
    """Classify exact retained outcomes through the old Crossref request key."""
    input_sha256 = file_sha256(input_csv)
    outcomes = _events(checkpoint, input_sha256)
    inputs = load_df(input_csv)
    validate_columns(inputs, ['doi'], input_csv.name)
    counts = Counter()
    for value in inputs['doi']:
        doi = clean(value)
        if not _is_crossref_indexed_doi(doi):
            continue
        request = json.dumps({'url': 'https://api.crossref.org/works/' + doi, 'params': {}, 'headers': {}}, sort_keys=True)
        outcome = outcomes.get(digest(request))
        if outcome is None:
            counts['missing'] += 1
            continue
        if outcome['event'] == 'not_found':
            counts['retained_not_found'] += 1
            continue
        response = outcome['response'].get('message')
        returned = clean(response.get('DOI')) if isinstance(response, dict) else ''
        if returned.lower() != doi.lower():
            counts['identity_unverified'] += 1
            continue
        counts['verified_response'] += 1
    return {'input_rows': len(inputs), 'distinct_saved_requests': len(outcomes),
            'crossref_input_rows': sum(counts.values()), 'outcomes': dict(counts), 'provider_requests': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_csv', type=Path)
    parser.add_argument('checkpoint', type=Path)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.input_csv, args.checkpoint), sort_keys=True))
