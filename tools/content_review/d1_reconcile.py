"""Validate private review decisions and plan a hash-bound, read-only overlay.

The caller must obtain fresh D1 data and current manifests over authorized
channels, and recheck them immediately before any leased checkpoint. This
module neither reads D1 nor writes decisions, manifests, or public artifacts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import re
import sys

HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_ROWS = 10000


class SnapshotError(ValueError):
    """Incomplete or internally inconsistent snapshot; do not process it."""


def _require(condition, reason):
    if not condition:
        raise SnapshotError(reason)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _rows(snapshot, key):
    rows = snapshot.get(key)
    _require(isinstance(rows, list) and len(rows) <= MAX_ROWS, f"Invalid {key} snapshot")
    evidence = snapshot.get('read_evidence')
    _require(isinstance(evidence, dict) and isinstance(evidence.get(key), dict), f"Missing {key} read evidence")
    proof = evidence[key]
    _require(proof.get('complete') is True and type(proof.get('truncated_values')) is int and proof['truncated_values'] == 0
             and type(proof.get('omitted_columns')) is int and proof['omitted_columns'] == 0
             and type(proof.get('rows_received')) is int and proof['rows_received'] == len(rows),
             f"Incomplete {key} read evidence")
    _require(all(isinstance(row, dict) for row in rows), f"Invalid {key} row")
    ids = [row.get('id') for row in rows]
    _require(all(isinstance(i, str) and i for i in ids), f"Missing {key} identity")
    _require(len(set(ids)) == len(ids), f"Duplicate {key} identity")
    return rows


def _fingerprint(snapshot):
    # Sort by immutable row ID; order from a paginated reader is not a snapshot.
    canonical = {k: sorted(snapshot[k], key=lambda row: row['id'])
                 for k in ('submissions', 'decisions', 'jobs')}
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _review_batch(collection, row):
    """Match the Site's existing collection-specific batch contract."""
    def safe_positive(value):
        return _integer(value, 1) and value <= 9007199254740991
    if collection == 'soups' and row.get('review_number') is None:
        number, batch = row.get('reserved_review_number'), row.get('reserved_review_batch')
        if (not safe_positive(number) or not safe_positive(batch) or
                any(row.get(field) is not None and row[field] != batch for field in ('review_batch', 'batch'))):
            return None
        return batch
    number = row.get('review_number')
    if not safe_positive(number):
        return None
    # APWG's filtered Site view computes `batch` after applying its fallback;
    # an original falsey review_batch must not override that computed value.
    fields = ('batch', 'review_batch') if collection == 'apwg' else ('review_batch', 'batch')
    for field in fields:
        explicit = row.get(field)
        if explicit is not None:
            return explicit if safe_positive(explicit) else None
    if collection == 'apwg':
        # APWG derives batches from filtered manifest positions; callers must
        # supply its normalized explicit batch, never guess that membership.
        return None
    if collection == 'soups':
        if number <= 100:
            return (number + 19) // 20
        if number <= 118:
            return 6
        return 7 + (number - 119) // 20
    return (number + 19) // 20


def reconcile(snapshot, confirmed_snapshot, manifests):
    """Return a plan, never publication authority or a mutation.

    Identical consecutive complete reads detect many pagination races, but are
    not a database transaction. The consumer must refresh and compare the D1
    state and source heads while holding the shared writer lease before writes.
    Only the latest complete revision per user/collection/batch is considered.
    Changed/missing candidates and cross-submission conflicts are held.
    """
    _require(isinstance(snapshot, dict) and isinstance(confirmed_snapshot, dict), 'Missing D1 snapshots')
    _require(isinstance(manifests, dict), 'Missing manifests')
    subs = _rows(snapshot, 'submissions')
    decisions = _rows(snapshot, 'decisions')
    jobs = _rows(snapshot, 'jobs')
    for key in ('submissions', 'decisions', 'jobs'):
        _rows(confirmed_snapshot, key)
    fingerprint = _fingerprint(snapshot)
    _require(fingerprint == _fingerprint(confirmed_snapshot), 'D1 snapshots changed between reads')

    by_id = {row['id']: row for row in subs}
    revisions, latest = set(), {}
    for row in subs:
        _require(all(isinstance(row.get(k), str) and row[k] for k in ('user_id', 'collection')), 'Invalid submission owner or collection')
        _require(_integer(row.get('batch'), 1) and _integer(row.get('revision'), 1), 'Invalid submission batch or revision')
        _require(_integer(row.get('accepted')) and _integer(row.get('rejected')), 'Invalid submission counts')
        _require(1 <= row['accepted'] + row['rejected'] <= 20, 'Invalid completed batch size')
        _require(bool(HASH.fullmatch(row.get('payload_hash') or '')), 'Invalid submission payload hash')
        key = (row['user_id'], row['collection'], row['batch'])
        unique = (*key, row['revision'])
        _require(unique not in revisions, 'Duplicate submission revision')
        revisions.add(unique)
        if key not in latest or row['revision'] > latest[key]['revision']:
            latest[key] = row

    counts, decision_by_key = defaultdict(Counter), {}
    for row in decisions:
        sub = by_id.get(row.get('submission_id'))
        _require(sub is not None, 'Decision references missing submission')
        _require(all(row.get(k) == sub[k] for k in ('user_id', 'collection', 'batch', 'revision')), 'Decision submission identity mismatch')
        _require(isinstance(row.get('candidate_id'), str) and bool(row['candidate_id']), 'Invalid candidate identity')
        _require(_integer(row.get('review_number'), 1) and bool(HASH.fullmatch(row.get('content_sha256') or '')), 'Invalid reviewed content identity')
        _require(row.get('decision') in ('approved', 'rejected'), 'Invalid review decision')
        key = (row['submission_id'], row['candidate_id'])
        _require(key not in decision_by_key, 'Duplicate decision in submission')
        decision_by_key[key] = row
        counts[sub['id']][row['decision']] += 1
    for sub in subs:
        _require(counts[sub['id']]['approved'] == sub['accepted'] and counts[sub['id']]['rejected'] == sub['rejected'], 'Incomplete submission decisions')

    for job in jobs:
        sub = by_id.get(job.get('submission_id'))
        _require(sub is not None, 'Job references missing submission')
        _require(all(job.get(k) == sub[k] for k in ('user_id', 'collection', 'revision')), 'Job submission identity mismatch')
        kind = job.get('kind')
        _require(kind in ('buffer_reconcile', 'mechanical_assessment', 'corpus_removal_review'), 'Unknown review job kind')
        if kind == 'buffer_reconcile':
            _require(job.get('candidate_id') is None and job.get('content_sha256') is None, 'Invalid buffer job')
            continue
        row = decision_by_key.get((job['submission_id'], job.get('candidate_id')))
        _require(row is not None and row['content_sha256'] == job.get('content_sha256'), 'Job reviewed content mismatch')
        _require(row['decision'] == ('approved' if kind == 'mechanical_assessment' else 'rejected'), 'Job decision mismatch')

    index = {}
    for collection, rows in manifests.items():
        _require(isinstance(collection, str) and isinstance(rows, list), 'Invalid collection manifest')
        for row in rows:
            _require(isinstance(row, dict) and isinstance(row.get('candidate_id'), str) and row['candidate_id'], 'Invalid manifest candidate')
            key = (collection, row['candidate_id'])
            _require(key not in index, 'Duplicate manifest candidate')
            index[key] = row

    active_ids = {s['id'] for s in latest.values()}
    active = [row for row in decisions if row['submission_id'] in active_ids]
    candidates = defaultdict(list)
    for row in active:
        candidates[(row['collection'], row['candidate_id'])].append(row)
    matched, held = [], []
    for key, rows in candidates.items():
        target = index.get(key)
        if len(rows) != 1:
            held.append({'collection': key[0], 'candidate_id': key[1], 'reason': 'conflicting_active_decisions'})
        elif target is None:
            held.append({'collection': key[0], 'candidate_id': key[1], 'reason': 'missing_manifest_candidate'})
        elif target.get('content_sha256') != rows[0]['content_sha256'] or target.get('review_number') != rows[0]['review_number']:
            held.append({'collection': key[0], 'candidate_id': key[1], 'reason': 'reviewed_content_changed'})
        elif _review_batch(key[0], target) != rows[0]['batch']:
            held.append({'collection': key[0], 'candidate_id': key[1], 'reason': 'review_batch_changed_or_unknown'})
        else:
            matched.append(deepcopy(rows[0]))
    return {'snapshot_sha256': fingerprint, 'transactional_snapshot': False,
            'requires_recheck_under_lease': True, 'matched_decisions': matched, 'held': held,
            'counts': {'submissions': len(subs), 'decisions': len(decisions), 'jobs': len(jobs),
                       'active_submissions': len(active_ids), 'active_decisions': len(active),
                       'matched': len(matched), 'held': len(held)}}


def select_reconciled(snapshot, confirmed_snapshot, manifests, ledger, *, limit=5,
                      source_progress=None, source_attempts=None):
    """Select only after overlaying matching completed decisions in memory.

    This is not a lease, a database transaction, or a checkpoint. The caller
    must still revalidate and use the existing leased, hash-verified writers.
    """
    from tools.content_review.work_plan import select

    _require(isinstance(manifests, dict) and all(isinstance(v, dict) for v in manifests.values()),
             'Invalid selection manifests')
    checked = reconcile(snapshot, confirmed_snapshot,
                        {k: v.get('records', []) for k, v in manifests.items()})
    decided = {(d['collection'], d['candidate_id']): d['decision'] for d in checked['matched_decisions']}
    held = {(d['collection'], d['candidate_id']) for d in checked['held']}
    # The Site writers protect every recorded decision, including a decision
    # superseded by a later batch revision. Do not repeatedly select one of
    # those candidates when the independent writer must reject it.
    historical = {(d['collection'], d['candidate_id']) for d in snapshot['decisions']}
    reviewed_numbers = {(d['collection'], d['review_number']) for d in snapshot['decisions']}
    # The Site's checkpoint and source writers also reject an entire submitted
    # review batch, including candidates without an individual decision. Keep
    # the planner in agreement so it doesn't repeatedly select unwritable work.
    submitted_batches = {(s['collection'], s['batch']) for s in snapshot['submissions']}
    safe = deepcopy(manifests)
    for collection, manifest in safe.items():
        for section in ('records', 'preflight_records'):
            _require(isinstance(manifest.get(section, []), list), 'Invalid manifest section')
            for row in manifest.get(section, []):
                _require(isinstance(row, dict) and isinstance(row.get('candidate_id'), str), 'Invalid selection candidate')
                key = (collection, row['candidate_id'])
                batch = _review_batch(collection, row)
                number = row.get('review_number')
                if collection == 'soups' and number is None:
                    number = row.get('reserved_review_number')
                if (key in held or batch is None or (collection, batch) in submitted_batches or
                        (collection, number) in reviewed_numbers or
                        not isinstance(row.get('content_sha256'), str) or not HASH.fullmatch(row['content_sha256'])):
                    # work_plan treats anything other than pending/unreviewed as
                    # ineligible; no editorial decision is written or invented.
                    row['decision'] = 'hold_review_reconciliation'
                elif key in decided:
                    row['decision'] = decided[key]
                elif key in historical:
                    row['decision'] = 'hold_review_reconciliation'
    selected = select(safe, ledger, limit=limit, source_progress=source_progress,
                      source_attempts=source_attempts)
    return {'selected': selected, 'reconciliation': checked}


def main():
    # One JSON line from stdin; raw private rows are never printed or persisted.
    try:
        request = json.loads(sys.stdin.readline())
        result = reconcile(request['snapshot'], request['confirmed_snapshot'], request['manifests'])
        print(json.dumps({'counts': result['counts'], 'transactional_snapshot': False,
                          'requires_recheck_under_lease': True}, sort_keys=True))
    except (KeyError, TypeError, json.JSONDecodeError, SnapshotError) as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, SnapshotError) else 'Invalid reconciliation input'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
