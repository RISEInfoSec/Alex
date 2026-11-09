"""Apply one confirmed private deletion; private reasons/actors never leave the Site.

The workflow's authenticated dispatch supplies only a public identity, the exact
reviewed-content hash and an opaque request ID. Git history remains the recovery
path; exclusions prevent a later intake from restoring the removed record.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def key(p):
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*', '', str(p.get('doi') or '').strip(), flags=re.I).lower()
    if doi:
        return 'doi:' + doi
    for value in (p.get('source_url'), p.get('link')):
        u = urlsplit(str(value or '').strip())
        if u.scheme in ('http', 'https') and u.netloc and not (u.username or u.password):
            return 'url:' + urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path or '/', u.query, ''))
    clean = lambda v: ' '.join(str(v or '').strip().split()).lower()
    return 'bib:' + json.dumps([clean(p.get('title')), re.sub(r'\.0$', '', str(p.get('year') or '').strip()), clean(p.get('author'))], ensure_ascii=False, separators=(',', ':'))


def fingerprint(p):
    values = [str(p.get('title') or ''), str(p.get('author') or ''), str(p.get('year') or ''), str(p.get('doi') or ''),
              str(p.get('source_url') or p.get('link') or ''), str(p.get('summary') or '')]
    values[2] = re.sub(r'\.0$', '', values[2])
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def apply(root: Path, request_id: str, identity: str, reviewed_hash: str):
    if not re.fullmatch(r'[a-f0-9-]{36}', request_id) or not re.fullmatch(r'[a-f0-9]{64}', reviewed_hash):
        raise ValueError('Invalid request identity or content hash')
    import pandas as pd
    from alex.editorial_exclusions import exclusion_keys, record_keys, filter_frame as filter_exclusions
    from alex.metadata_holds import filter_frame as filter_metadata_holds
    receipt_path = root / 'data/deletion_receipts.json'
    receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {'schema_version': 1, 'records': {}}
    if receipts.get('schema_version') != 1 or not isinstance(receipts.get('records'), dict):
        raise ValueError('Invalid publication receipts')
    prior = receipts['records'].get(request_id)
    if prior:
        if prior.get('identity') != identity or prior.get('content_sha256') != reviewed_hash:
            raise ValueError('Request ID was used for a different decision')
        papers = json.loads((root / 'data/papers.json').read_text())
        if any(key(p) == identity for p in papers):
            raise ValueError('Previously deleted identity has reappeared')
        return {'already_applied': True, 'request_id': request_id}
    papers = json.loads((root / 'data/papers.json').read_text())
    matches = [(i, p) for i, p in enumerate(papers) if key(p) == identity]
    if len(matches) != 1:
        raise ValueError('Deletion must identify exactly one published record')
    index, paper = matches[0]
    if fingerprint(paper) != reviewed_hash:
        raise ValueError('Published content changed after the deletion decision; review it again')
    corpus = root / 'data/accepted_classified.csv'
    with corpus.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream); fields = reader.fieldnames; rows = list(reader)
    # Public output is a projection of the canonical corpus: editorial
    # exclusions and technical metadata holds intentionally retain their
    # canonical rows while excluding them from publication. Use the same
    # filters as the publisher, retaining original CSV indexes so the
    # approved public record maps back to exactly one canonical row.
    canonical = pd.read_csv(corpus)
    if len(canonical) != len(rows):
        raise ValueError('Canonical corpus could not be read consistently')
    projected = filter_exclusions(canonical, root / 'config/corpus_exclusions.json')
    projected = filter_metadata_holds(projected, root / 'config/corpus_metadata_holds.json')
    indexes = list(projected.index)
    if (len(indexes) != len(papers) or any(not isinstance(i, int) or i < 0 or i >= len(rows) for i in indexes)
            or indexes != sorted(set(indexes))):
        raise ValueError('Canonical and public corpora differ; reconcile before deletion')
    if len(papers) < 2:
        raise ValueError('The final corpus record requires manual publication reconciliation')
    for canonical_index, public in zip(indexes, papers):
        # Canonical/source order is part of the existing publication projection.
        source = rows[canonical_index]
        if source.get('title') != public.get('title') or source.get('authors', '') != public.get('author', '') or source.get('abstract', '') != public.get('summary', ''):
            raise ValueError('Canonical and public content are not aligned')
    canonical_index = indexes[index]
    exclusion = {'candidate_id': 'private-deletion:' + request_id, 'title': paper['title'], 'year': paper.get('year', ''),
                 'doi': paper.get('doi', ''), 'source_url': paper.get('source_url') or paper.get('link') or '',
                 'decision': 'rejected', 'submission_id': request_id, 'reviewed_content_sha256': reviewed_hash,
                 'reason': 'Administrator confirmed deletion in the private ALEX workspace.'}
    keys = exclusion_keys(exclusion)
    if (any(record_keys(p) & keys for i, p in enumerate(papers) if i != index)
            or any(record_keys(row) & keys for i, row in enumerate(rows) if i != canonical_index)):
        raise ValueError('This exclusion would affect another record; manual reconciliation required')
    registry_path = root / 'config/corpus_exclusions.json'
    registry = json.loads(registry_path.read_text())
    if registry.get('schema_version') != 1 or not isinstance(registry.get('records'), list):
        raise ValueError('Invalid exclusion registry')
    registry['records'].append(exclusion)
    receipt = {'identity': identity, 'content_sha256': reviewed_hash, 'status': 'published', 'records_before': len(rows), 'records_after': len(rows) - 1}
    receipts['records'][request_id] = receipt
    # All validation precedes mutations. Git commits all generated outputs together.
    with corpus.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows[:canonical_index] + rows[canonical_index + 1:])
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n')
    receipt_path.write_text(json.dumps(receipts, ensure_ascii=False, indent=2) + '\n')
    return {'request_id': request_id, 'removed': 1}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request-id'); parser.add_argument('--identity')
    parser.add_argument('--reviewed-hash'); parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--workflow-event', action='store_true')
    args = parser.parse_args()
    if args.workflow_event:
        if any(value is not None for value in (args.request_id, args.identity, args.reviewed_hash)):
            parser.error('Workflow event inputs cannot be combined with explicit inputs')
        event_path = os.environ.get('GITHUB_EVENT_PATH')
        if not event_path:
            parser.error('Workflow event is unavailable')
        try:
            event = json.loads(Path(event_path).read_text(encoding='utf-8'))
            inputs = event['inputs']
            values = [inputs[name] for name in ('request_id', 'identity', 'reviewed_hash')]
        except (OSError, ValueError, KeyError, TypeError):
            parser.error('Workflow event inputs are unavailable')
        if not all(isinstance(value, str) and value for value in values):
            parser.error('Workflow event inputs are invalid')
        result = apply(args.root, *values)
        print(json.dumps({'removed': result.get('removed', 0), 'already_applied': result.get('already_applied', False)}))
    else:
        if not all((args.request_id, args.identity, args.reviewed_hash)):
            parser.error('Explicit request, identity, and reviewed hash are required')
        print(json.dumps(apply(args.root, args.request_id, args.identity, args.reviewed_hash)))
