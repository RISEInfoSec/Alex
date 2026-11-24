"""Inspect the explicitly linked outstanding original for two identified weekly cases.

Run from the review branch checkout, with its package on PYTHONPATH. Uses the native
publisher transport and its robots, pacing, byte, cooldown and destination guards.
Writes a local observation only. Never asserts a candidate gate or edits any source.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from tools.content_review.lifecycle import ensure_eligible
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.source_unresolved import validate as unresolved
from tools.content_review.source_worker import Transport, Hold, extract

CANDIDATES = (
    ('weekly-2fb8d1268a016d82ab42dd40', 'https://www.advancelrf.org/wp-content/uploads/2026/09/Vol-8-No.-3-5.pdf'),
    ('weekly-02db78e5dcf92cfe64dc4487', 'https://www.ijisrt.com/assets/upload/files/IJISRT26MAY1257.pdf'),
)


def load(root, name):
    return json.loads((root / name).read_bytes())


def run(root, out):
    state = load(root, 'config/content_review_worker_status.json')
    ledger = load(root, 'config/content_review_candidate_lifecycle.json')['records']
    manifest = load(root, 'config/weekly_review_manifest.json')
    _, hosts = unresolved(state.get('source_unresolved_requests', []))
    tx = Transport(deadline=time.monotonic() + 160, cap=8,
                   origin_backoff=state.get('source_origin_backoff', {}), unresolved_origins=hosts)
    results = []
    for candidate, url in CANDIDATES:
        row, = [r for r in manifest['preflight_records'] if r.get('candidate_id') == candidate]
        entry = ledger['weekly:' + candidate]
        ensure_eligible(root, 'weekly', candidate)
        assert row.get('decision', 'pending') in ('pending', 'unreviewed') and not row.get('publication_approved')
        assert row.get('publication_status') != 'published_live_verified' and reviewed_digest(row) == row['content_sha256']
        assert entry['state'] == 'awaiting_initial_checks' and entry['content_sha256'] == row['content_sha256']
        assert row.get('access_decision', {}).get('status') != 'restricted'
        assert row.get('source_observation', {}).get('tlp', '').upper() in ('', 'TLP:CLEAR', 'TLP:WHITE')
        prior = row['source_processing']
        assert prior['content_sha256'] == row['content_sha256'] and prior['retrieval_status'] == 'retrieved'
        receipt = load(root, prior['receipt'])
        assert receipt['independently_verified'] is True
        observations, = [r for r in receipt['result']['records'] if r['candidate_id'] == candidate and
                         r['collection'] == 'weekly' and r['content_sha256'] == row['content_sha256']]
        landing, = [e for e in observations['evidence'] if e['requested_url'] == row['source_url'] and
                    e.get('http_status') == 200 and not e.get('resource_unavailable') and
                    urlsplit(e['final_url']).netloc == urlsplit(url).netloc and
                    any(link.get('url') == url for link in e.get('links', []))]
        assert hashlib.sha256(landing['text'].encode()).hexdigest() == landing['text_sha256']
        assert not any(e.get('requested_url') == url or e.get('final_url') == url for e in observations['evidence'])
        detail = {'candidate_id': candidate, 'content_sha256': row['content_sha256'], 'url': url, 'source_receipt': prior['receipt'],
                  'prior_run_id': receipt['result']['provenance']['GITHUB_RUN_ID'], 'gate_writes': 0, 'trigger': 'operator_manual'}
        try:
            evidence = extract(tx.fetch(url))
            if evidence.get('container_type') != 'pdf':
                raise Hold('intended_original_not_pdf')
            normalized = lambda text: ' '.join(re.findall(r'[a-z0-9]+', text.lower()))
            pdf_text = evidence['text']
            detail.update(status='retrieved', pdf=dict(
                requested_url=evidence['requested_url'], final_url=evidence['final_url'],
                http_status=evidence['http_status'], body_sha256=evidence['body_sha256'],
                text_sha256=evidence['text_sha256'], byte_count=evidence['byte_count'],
                retrieved_at=evidence['retrieved_at'], page_count=evidence.get('page_count'),
                title_present=normalized(row['title']) in normalized(pdf_text),
                doi_present=row['doi'].lower() in pdf_text.lower(),
                authors_present=all(normalized(a) in normalized(pdf_text) for a in row['authors'].split(';')),
                complete_text=evidence.get('text_complete'),
            ))
        except Exception as exc:
            detail.update(status='held', reason=str(exc) if isinstance(exc, Hold) else type(exc).__name__)
        results.append(detail)
        out.write_text(json.dumps({'results': results, 'request_log': tx.sends,
            'native_run_id': os.getenv('GITHUB_RUN_ID'), 'trigger': os.getenv('GITHUB_EVENT_NAME','operator_manual'),
            'native_run_attempt': os.getenv('GITHUB_RUN_ATTEMPT')}, ensure_ascii=False, indent=2) + '\n')
        print(candidate, detail['status'], detail.get('reason', ''), len(tx.sends), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence_file', type=Path)
    args = parser.parse_args()
    run(Path.cwd(), args.evidence_file)
