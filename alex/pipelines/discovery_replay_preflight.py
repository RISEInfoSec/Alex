"""Fail-closed, offline verification of exact saved singleton replay keys."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import warnings

import pandas as pd

from alex.connectors.openalex import OPENALEX, _normalise_doi
from alex.utils.text import normalize_title


def verify(root: Path, *, expected_state: str, minimum_hits: str, mailto: str,
           expected_checkout: str) -> tuple[int, int]:
    if (not re.fullmatch(r'[0-9a-f]{40}', expected_state or '')
            or not re.fullmatch(r'[0-9a-f]{40}', expected_checkout or '')
            or not re.fullmatch(r'[0-9]{1,3}', minimum_hits or '')
            or not 1 <= int(minimum_hits) <= 250 or not mailto):
        raise ValueError('invalid_preflight_inputs')
    git_dir = subprocess.check_output(['git', 'rev-parse', '--git-dir'], cwd=root,
                                      text=True, stderr=subprocess.DEVNULL).strip()
    directory = Path(git_dir)
    if not directory.is_absolute():
        directory = root / directory
    pulled_state = (directory / 'alex-state-base').read_text().strip()
    checkout = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    if pulled_state != expected_state or checkout != expected_checkout:
        raise ValueError('preflight_ref_mismatch')
    checkpoint = json.loads((root / 'data/discovery_checkpoint.json').read_text())
    if checkpoint.get('status') != 'partial' or not isinstance(checkpoint.get('responses'), dict):
        raise ValueError('checkpoint_not_partial')
    targets = checkpoint['candidate_titles']
    if not isinstance(targets, list) or not all(isinstance(v, str) for v in targets):
        raise ValueError('invalid_checkpoint_targets')
    targets = set(targets)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', pd.errors.DtypeWarning)
        frame = pd.read_csv(root / 'data/discovery_candidates.csv')
    frame = frame.astype(object).where(pd.notna(frame), '')
    dois = set()
    for row in frame.to_dict('records'):
        if (normalize_title(str(row.get('title', ''))) in targets
                and not row.get('abstract') and row.get('doi')):
            # Discovery normalizes once while gathering DOIs and again in
            # get_many_by_doi before constructing the singleton URL.
            dois.add(_normalise_doi(_normalise_doi(str(row['doi']))))
    dois.discard('')
    matches = 0
    responses = checkpoint['responses']
    expected_keys = set()
    for doi in dois:
        url = f'{OPENALEX}/https://doi.org/{doi}'
        key = hashlib.sha256(json.dumps(['get_json', url, {'mailto': mailto}],
                                        sort_keys=True).encode()).hexdigest()
        expected_keys.add(key)
        if key not in responses:
            continue
        value = responses[key]
        if value is None:
            matches += 1  # A retained 404 is a completed lookup.
        elif isinstance(value, dict):
            identifier = (value.get('ids') or {}).get('doi', '')
            if isinstance(identifier, str) and _normalise_doi(identifier) == doi:
                matches += 1
    # A high aggregate hit count alone could hide a few lost old keys if
    # unrelated hits offset them. Preserve each known work and negative key.
    for key, value in responses.items():
        if value is None and key not in expected_keys:
            raise ValueError('checkpoint_cache_context_mismatch')
        if isinstance(value, dict) and isinstance(value.get('ids'), dict):
            identifier = value['ids'].get('doi', '')
            if (isinstance(identifier, str) and _normalise_doi(identifier) in dois
                    and key not in expected_keys):
                raise ValueError('checkpoint_cache_context_mismatch')
    if matches < int(minimum_hits):
        raise ValueError('checkpoint_cache_context_mismatch')
    return matches, len(dois)


def main() -> int:
    try:
        matches, total = verify(Path.cwd(),
            expected_state=os.getenv('EXPECTED_PIPELINE_STATE', ''),
            minimum_hits=os.getenv('MINIMUM_CHECKPOINT_CACHE_HITS', ''),
            mailto=os.getenv('HARVEST_MAILTO', ''),
            expected_checkout=os.getenv('GITHUB_SHA', ''))
    except Exception as exc:
        # Do not expose values, paths, provider data or exception text.
        known = {'invalid_preflight_inputs', 'preflight_ref_mismatch',
                 'checkpoint_not_partial', 'invalid_checkpoint_targets',
                 'checkpoint_cache_context_mismatch'}
        reason = str(exc) if type(exc) is ValueError and str(exc) in known else 'preflight_failed'
        print('Checkpoint replay preflight blocked: ' + reason, file=sys.stderr)
        return 1
    print(f'Checkpoint replay preflight verified {matches} cached lookups among {total} pending DOIs')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
