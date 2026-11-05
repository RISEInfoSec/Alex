"""Reversible, evidence-backed technical publication holds, not editorial votes."""
import json
import re
from pathlib import Path


def load_holds(path):
    path = Path(path)
    if not path.exists():
        return []
    policy = json.loads(path.read_text())
    if policy.get('schema_version') != 1 or not policy.get('authorization'):
        raise ValueError('Invalid metadata hold policy')
    holds = policy['records']
    seen = set()
    for hold in holds:
        doi = hold.get('doi', '')
        proof = hold.get('evidence', {})
        if (not re.fullmatch(r'10\.5281/zenodo\.\d+', doi) or doi in seen
                or hold.get('status') != 'held_pending_supported_type_review'
                or hold.get('verified_resource_type') != 'Book'
                or proof.get('metadata_doi') != doi
                or proof.get('resource_type_general') != 'Book'
                or proof.get('source_url') != 'https://api.datacite.org/dois/' + doi
                or not re.fullmatch(r'[0-9a-f]{64}', proof.get('body_sha256', ''))
                or not re.fullmatch(r'[0-9a-f]{64}', hold.get('original_csv_row_sha256', ''))
                or not proof.get('verified_source_receipt') or not hold.get('reason')):
            raise ValueError('Unproven or ambiguous metadata publication hold')
        seen.add(doi)
    return holds


def canonical_doi(value):
    value = str(value).strip().lower()
    return re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value)


def filter_records(records, path):
    held_dois = {h['doi'] for h in load_holds(path)}
    return [r for r in records if canonical_doi(r.get('doi','')) not in held_dois]


def filter_frame(frame, path):
    holds = load_holds(path)
    if not holds:
        return frame
    held_dois = {h['doi'] for h in holds}
    mask = frame.get('doi')
    if mask is None:
        raise ValueError('Corpus DOI column missing while publication holds exist')
    # Preserve original indexes: publish binds typed resources to exact CSV rows.
    return frame.loc[~mask.map(canonical_doi).isin(held_dois)].copy()
