"""Audit reusable Crossref outcomes independently of legacy harvest completion."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re

import pandas as pd

from alex.pipelines.harvest import _is_crossref_indexed_doi
from alex.utils.harvest_checkpoint import digest, file_sha256
from alex.utils.io import validate_columns
from alex.utils.text import clean


def _events(checkpoint: Path, input_sha256: str):
    outcomes = {}
    checksum = hashlib.sha256()
    with checkpoint.open('rb') as stream:
        first = next(stream, b'')
        checksum.update(first)
        header = json.loads(first)
        if (not isinstance(header, dict) or not first.endswith(b'\n')
                or header.get('schema_version') != 1 or header.get('input_sha256') != input_sha256):
            raise ValueError('Saved outcomes do not bind to this exact harvest input')
        for raw in stream:
            checksum.update(raw)
            row = json.loads(raw)
            if not raw.endswith(b'\n') or not isinstance(row, dict):
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
    return outcomes, checksum.hexdigest()


def reconcile(input_csv: Path, checkpoint: Path, *, include_records=False):
    """Classify exact retained outcomes through the old Crossref request key."""
    uncertain = checkpoint.with_name(checkpoint.name + '.uncertain')
    if uncertain.exists():
        raise ValueError('Harvest state uncertain; reconciliation cannot authorize reuse')
    # Hash and parse the same captured bytes, rather than reopening mutable input.
    raw_input = input_csv.read_bytes()
    input_sha256 = hashlib.sha256(raw_input).hexdigest()
    outcomes, checkpoint_sha256 = _events(checkpoint, input_sha256)
    inputs = pd.read_csv(io.BytesIO(raw_input))
    validate_columns(inputs, ['doi'], input_csv.name)
    counts = Counter()
    records = []
    for position, value in enumerate(inputs['doi']):
        doi = clean(value)
        if not _is_crossref_indexed_doi(doi):
            continue
        request = json.dumps({'url': 'https://api.crossref.org/works/' + doi, 'params': {}, 'headers': {}}, sort_keys=True)
        request_sha256 = digest(request)
        outcome = outcomes.get(request_sha256)
        status = 'missing'
        returned = ''
        if outcome is None:
            pass
        elif outcome['event'] == 'not_found':
            status = 'retained_not_found'
        else:
            response = outcome['response'].get('message')
            returned = clean(response.get('DOI')) if isinstance(response, dict) else ''
            status = 'verified_response' if returned.lower() == doi.lower() else 'identity_unverified'
        counts[status] += 1
        if include_records:
            records.append({'input_record_index': position, 'doi': doi, 'outcome': status,
                            'request_sha256': request_sha256,
                            'outcome_sha256': outcome.get('sha256') if outcome else None,
                            'returned_doi': returned or None})
    # Fail on changed source files or a newly raised uncertainty hold. This is
    # an evidence audit, never a completion marker or a request authorization.
    if (uncertain.exists() or file_sha256(input_csv) != input_sha256
            or file_sha256(checkpoint) != checkpoint_sha256):
        raise ValueError('Retained reconciliation input changed; no audit accepted')
    report = {'input_rows': len(inputs), 'distinct_saved_requests': len(outcomes),
              'crossref_input_rows': sum(counts.values()), 'outcomes': dict(counts),
              'provider_requests': 0, 'input_sha256': input_sha256,
              'checkpoint_sha256': checkpoint_sha256, 'collection_complete': False,
              'publication_authorized': False, 'replay_authorized': False,
              'verification_scope': 'retained outcome hashes and DOI identity only; no document, quality or editorial approval'}
    if include_records:
        report['records'] = records
    return report


def write_manifest(path: Path, report):
    """Create-only local evidence; never overwrite retained input or a prior audit."""
    payload = {'schema_version': 1, 'report': report, 'sha256': digest(report)}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, sort_keys=True, ensure_ascii=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_csv', type=Path)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--manifest', type=Path, help='Create a new local per-input evidence ledger; never grants completion or publication')
    args = parser.parse_args()
    report = reconcile(args.input_csv, args.checkpoint, include_records=args.manifest is not None)
    if args.manifest:
        write_manifest(args.manifest, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, sort_keys=True))
