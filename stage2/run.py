"""Private local staging commands; recorded sources and explicit review only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from stage1.engine import canonical, digest
from stage2.adapters import RecordedClient, collect
from stage2.store import ProcessingStore
from stage2 import preview


def ingest_pack(store, pack):
    if pack.get('schema_version') != 1 or pack.get('mode') != 'recorded':
        raise ValueError('recorded_evidence_pack_required')
    client = RecordedClient(store.effects, pack['captures'])
    receipt_hash = digest(pack)
    try:
        rows = collect(pack['source'], client, query=pack.get('query', 'cybersecurity'),
                       collection=pack['collection'], archive_url=pack.get('archive_url'),
                       archive_year=pack.get('archive_year'))
    except Exception:
        with store.transaction():
            store.db.execute('INSERT OR IGNORE INTO source_outcomes VALUES(?,?,?,?,?)',
                             (receipt_hash, pack['source'], 'held_source_error', 0, 1))
        raise
    if len(rows) > 1000:
        raise ValueError('intake_bound_exceeded')
    ids, held = [], 0
    for index, record in enumerate(rows):
        try:
            document = pack.get('documents', {}).get(digest(record))
            ids.append(store.discover_saved(pack['source'], receipt_hash + ':' + str(index), record, document))
        except ValueError as error:
            # Missing metadata/identity conflicts remain retained holds, not
            # dropped rows or fabricated publication years.
            if str(error) not in ('title_and_year_required_for_fixture', 'receipt_content_conflict',
                                  'identity_conflict_requires_review', 'content_conflict_requires_review',
                                  'conflicting_doi_requires_review', 'retained_document_conflict',
                                  'document_not_bound_to_candidate'):
                raise
            hold_hash = digest({'source': pack['source'], 'record': record})
            with store.transaction():
                store.db.execute('INSERT OR IGNORE INTO intake_holds VALUES(?,?,?,?)',
                                 (hold_hash, pack['source'], canonical(record), str(error)))
            held += 1
    with store.transaction():
        expected = (pack['source'], 'held' if held else 'complete_bounded_capture', len(ids), held)
        old = store.db.execute('SELECT source,status,discovered,held FROM source_outcomes WHERE receipt_hash=?', (receipt_hash,)).fetchone()
        if old and tuple(old) != expected:
            raise ValueError('source_outcome_conflict')
        store.db.execute('INSERT OR IGNORE INTO source_outcomes VALUES(?,?,?,?,?)', (receipt_hash, *expected))
    return {'candidate_ids': ids, 'intake_holds': held, 'recorded_transport_calls': client.transport_calls,
            'live_requests': 0, 'source_status': expected[1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--reviewer', action='append', required=True,
                        help='Explicit local staging operator allowlist; not a browser identity')
    sub = parser.add_subparsers(dest='command', required=True)
    ingest = sub.add_parser('ingest')
    ingest.add_argument('pack')
    sub.add_parser('process')
    sub.add_parser('review-packet')
    review = sub.add_parser('review')
    review.add_argument('receipt')
    sub.add_parser('preview')
    sub.add_parser('status')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    workspace = Path(args.workspace).resolve()
    if workspace == root or root in workspace.parents or 'sources' in workspace.parts:
        raise ValueError('use_private_workspace_outside_repository_and_sources')
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    workspace.chmod(0o700)
    store = ProcessingStore(workspace / 'private/state.sqlite', root=root, reviewers=args.reviewer)
    try:
        if args.command == 'ingest':
            result = ingest_pack(store, json.loads(Path(args.pack).read_text()))
        elif args.command == 'process':
            result = {'completed_jobs': store.work(), **store.status()}
        elif args.command == 'review-packet':
            result = store.review_packet()
            (workspace / 'review-packet.json').write_text(json.dumps(result, indent=2) + '\n')
        elif args.command == 'review':
            store.review(json.loads(Path(args.receipt).read_text()))
            result = store.status()
        elif args.command == 'preview':
            result = preview.publish(store, workspace / 'preview')
        else:
            result = store.status()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        store.close()


if __name__ == '__main__':
    main()
