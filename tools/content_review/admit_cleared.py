"""Seal cleared candidates into immutable review batches, independently of held peers."""
from __future__ import annotations

import copy
from collections import Counter

from tools.content_review.bind_recommendations import ALL_GATES, _current_pass
from tools.content_review.paid_worker import reviewed_digest


def admit(manifest, stage, collection, submitted_batches=(), decided_ids=(), stamp=None):
    """Keep identities/content fixed; allocate new batches beyond every reservation.

    A sealed batch may have 1–20 papers. Later passes always allocate new batches,
    never append to an admitted/submitted batch. The SOUPS full-batch floor is
    counted separately. This function spends nothing and never changes decisions.
    """
    from tools.content_review.paid_worker import now
    stamp = stamp or now()
    result, checkpoint = copy.deepcopy(manifest), copy.deepcopy(stage)
    all_rows = result.get('records', []) + result.get('preflight_records', [])
    ids = [r['candidate_id'] for r in all_rows]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate current candidate identity')
    stages = {(r['collection'], r['candidate_id']): r for r in checkpoint['records']}
    submitted_batches, decided_ids = set(submitted_batches), set(decided_ids)
    existing_batches = list(submitted_batches)
    for row in all_rows:
        existing_batches.extend(row[k] for k in ('review_batch', 'batch', 'reserved_review_batch')
                                if isinstance(row.get(k), int))
        if collection == 'soups' and row.get('review_number'):
            from alex.pipelines.soups_gui_decisions import batch_number
            existing_batches.append(batch_number(row['review_number']))
    existing_batches.extend(b['batch'] for b in result.get('sealed_review_batches', []))
    next_batch = max(existing_batches, default=0) + 1
    eligible = []
    for row in all_rows:
        if (not row.get('batch_admission_eligible') or row.get('review_ready')
                or row.get('decision', 'pending') not in ('pending', 'unreviewed')
                or row['candidate_id'] in decided_ids):
            continue
        h = row['content_sha256']
        z = stages.get((collection, row['candidate_id']))
        if (not z or reviewed_digest(row) != h or z['content_sha256'] != h
                or row.get('recommendation_content_sha256') != h
                or row.get('recommendation_evidence', {}).get('content_sha256') != h):
            raise ValueError('Stale content or recommendation: ' + row['candidate_id'])
        for gate in ALL_GATES:
            if not all(_current_pass(checks.get(gate, {}), h) for checks in
                       (row['preflight']['checks'], z['checks'])):
                raise ValueError('Uncleared gate: ' + gate)
        eligible.append(row)
    eligible.sort(key=lambda r: r.get('review_number') or r.get('reserved_review_number'))
    sealed = []
    for offset in range(0, len(eligible), 20):
        batch = next_batch + offset // 20
        group = eligible[offset:offset + 20]
        members = []
        for row in group:
            old_batch = row.get('review_batch') or row.get('batch') or row.get('reserved_review_batch')
            row.setdefault('preflight_reservation', {
                'review_number': row.get('review_number') or row.get('reserved_review_number'),
                'review_batch': old_batch,
            })
            row['review_number'] = row.get('review_number') or row['reserved_review_number']
            row['review_batch'] = row['batch'] = batch
            row['review_ready'] = row['editorial_queue_eligible'] = True
            row['preflight_status'] = row['readiness_status'] = 'passed'
            row['admission_hold'] = None
            row['admitted_at'] = stamp
            z = stages[(collection, row['candidate_id'])]
            z.update(status='passed', review_ready=True, admitted_at=stamp, review_batch=batch)
            members.append({'candidate_id': row['candidate_id'], 'review_number': row['review_number'],
                            'content_sha256': row['content_sha256']})
        sealed.append({'batch': batch, 'sealed_at': stamp, 'count': len(group), 'members': members,
                       'policy': 'Cleared candidates sealed independently of held inventory; never append.'})
    admitted_ids = {r['candidate_id'] for r in eligible}
    result['preflight_records'] = [r for r in result.get('preflight_records', [])
                                   if r['candidate_id'] not in admitted_ids]
    existing_ids = {r['candidate_id'] for r in result['records']}
    result['records'].extend(r for r in eligible if r['candidate_id'] not in existing_ids)
    result.setdefault('sealed_review_batches', []).extend(sealed)
    ready = [r for r in result['records'] if r.get('review_ready')
             and r.get('decision', 'pending') in ('pending', 'unreviewed')
             and r['candidate_id'] not in decided_ids]
    result['ready_count'] = len(ready)
    result['prepared_count'] = len(ready)
    result['mechanical_passed_awaiting_batch_admission'] = 0
    result['preflight_held_count'] = sum(r.get('preflight', {}).get('status') != 'passed'
                                       for r in all_rows if (collection, r['candidate_id']) in stages)
    result['preflight_policy'] = (
        'Admit only six current hash-bound gate passes and current substantive recommendations. '
        'Seal batches of 1–20 cleared candidates independently of held peers; never append to sealed batches.'
    )
    checkpoint['updated_at'] = stamp
    counts = Counter(r['review_batch'] for r in ready)
    return result, checkpoint, {'admitted': len(eligible), 'ready': len(ready),
                               'batches': sealed, 'full_pending_batches': sum(n == 20 for n in counts.values())}
