"""Controlled acceptance dataset; source responses and review actors are synthetic.

The processing/check implementations are real. This makes no live-provider,
production-editorial or hosted-scheduler verification claim.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3

from stage1.engine import digest
from stage2.adapters import RecordedClient, collect
from stage2.effects import EffectLedger
from stage2.run import ingest_pack
from stage2.store import ProcessingStore
from stage2.preview import publish, read


ACTOR = 'synthetic-stage2-reviewer'


def fixture_pack():
    abstract = ('Cybersecurity cybercrime OSINT methodology and investigation use open source intelligence, '
                'threat intelligence collection and dark web research to study phishing, malware and advanced persistent threats. '
                'This controlled fixture describes security research with explicit methods, bounded observations and reproducible evidence.')
    items = []
    for name in ('approved', 'rejected', 'book-held', 'irrelevant', 'restricted', 'missing-year'):
        item = {'title': ['Controlled cybersecurity investigation ' + name],
                'author': [{'given': 'Synthetic', 'family': 'University Researcher'}],
                'DOI': '10.0000/alex-stage2-' + name, 'abstract': abstract,
                'container-title': ['IEEE Security & Privacy'], 'published': {'date-parts': [[2024]]},
                'is-referenced-by-count': 500, 'URL': 'https://example.invalid/stage2/' + name,
                'type': 'journal-article'}
        if name == 'book-held':
            item['type'] = 'book'
        elif name == 'irrelevant':
            item['title'] = ['Controlled marine fish population study']
            item['abstract'] = 'Marine fish population measurements describe ocean ecology, spawning and stock sustainability.'
        elif name == 'missing-year':
            del item['published']
            item['created'] = {'date-parts': [[2024, 1, 1]]}
        items.append(item)
    request = RecordedClient.descriptor('https://api.crossref.org/works',
                                         {'query.title': 'cybersecurity', 'rows': 25, 'offset': 0})
    response = {'status': 200, 'body': {'message': {'items': items}}}
    captures = [{'request': request, 'response': response, 'response_sha256': digest(response)}]
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.row_factory = sqlite3.Row
    client = RecordedClient(EffectLedger(db), captures)
    rows = collect('Crossref', client, collection='synthetic-stage2')
    db.close()
    documents = {}
    for record in rows:
        text = ('<html><article><h1>' + record['title'] + '</h1><p>' + record['abstract'] + '</p><p>' +
                'This is a synthetic saved article, not a provider observation or an editorial approval. '
                'Its body permits reproducible checks of parsing, identity binding, format validation, metadata integrity, '
                'quality scoring, explicit review and isolated preview output without contacting a source.' + '</p></article></html>')
        raw = text.encode()
        document = {'candidate_content_hash': digest(record), 'url': record['source_url'],
                    'status': 403 if record['title'].endswith('restricted') else 200,
                    'access': 'restricted' if record['title'].endswith('restricted') else 'public',
                    'content_type': 'text/html; charset=utf-8', 'body_hex': raw.hex(),
                    'body_sha256': hashlib.sha256(raw).hexdigest(), 'provenance': 'synthetic_saved_fixture'}
        documents[digest(record)] = document
    return {'schema_version': 1, 'mode': 'recorded', 'source': 'Crossref',
            'collection': 'synthetic-stage2', 'query': 'cybersecurity',
            'captures': captures, 'documents': documents, 'fixture_editorial_authority': 'synthetic_only'}


def run(workspace):
    root = Path(__file__).resolve().parents[1]
    workspace = Path(workspace).resolve()
    if root == workspace or root in workspace.parents or 'sources' in workspace.parts:
        raise ValueError('private_acceptance_workspace_required')
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    pack = fixture_pack()
    (workspace / 'saved-source-pack.json').write_text(json.dumps(pack, indent=2) + '\n')
    store = ProcessingStore(workspace / 'private/state.sqlite', root=root, reviewers=[ACTOR])
    try:
        intake = ingest_pack(store, pack)
        first_jobs = store.work()
        packet = store.review_packet()
        (workspace / 'review-packet.json').write_text(json.dumps(packet, indent=2) + '\n')
        receipts = []
        for candidate in packet['candidates']:
            title = candidate['record']['title']
            if title.endswith('approved'):
                verdict = 'approve'
            elif title.endswith('rejected'):
                verdict = 'reject'
            else:
                verdict = 'hold'
            receipt = {'id': 'synthetic-stage2-decision-' + candidate['candidate_id'],
                       'actor': ACTOR, 'candidate_id': candidate['candidate_id'],
                       'content_hash': candidate['content_hash'], 'policy_hash': packet['policy_hash'],
                       'verdict': verdict, 'reason': 'Explicit synthetic acceptance decision; no real editorial authority'}
            store.review(receipt)
            receipts.append(receipt)
        final_jobs = store.work()
        projection = publish(store, workspace / 'preview')
        papers = read(workspace / 'preview')
        assert len(papers) == 1 and papers[0]['title'].endswith('approved')
        baseline = store.status()
        for _ in range(3):
            replay = ingest_pack(store, pack)
            assert replay['recorded_transport_calls'] == 0
            assert store.work() == 0
            for receipt in receipts:
                store.review(receipt)
            assert store.status() == baseline
            assert publish(store, workspace / 'preview') == projection
        assert store.db.execute('PRAGMA foreign_key_check').fetchall() == []
        evidence = {'scope': 'Stage 2 controlled recorded-input acceptance', 'synthetic_source_data': True,
                    'synthetic_editorial_decisions': True, 'actual_check_implementations': True,
                    'first_processing_jobs': first_jobs, 'preview_jobs': final_jobs,
                    'three_replays_without_duplicates': True, 'rejected_and_held_unpublished': True,
                    'unknown_publication_year_quarantined': True, 'preview': projection,
                    'status': store.status(), 'live_provider_requests': 0,
                    'hosted_runtime_verified': False, 'production_migration_authorized': False}
        (workspace / 'acceptance-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        (workspace / 'synthetic-review-receipts.json').write_text(json.dumps(receipts, indent=2) + '\n')
        return evidence
    finally:
        store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace), sort_keys=True))
