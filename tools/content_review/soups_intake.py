"""Prepare bounded SOUPS reservations and lifecycle entries without writing.

The proposal is not authority to checkpoint. It requires an independent
semantic guard, current lease and heads, and a D1 fence/recheck at commit.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from tools.content_review.coordinator import plan
from tools.content_review.d1_reconcile import reconcile
from tools.content_review.lifecycle import evaluate, instant
from tools.content_review.manifest_integrity import reviewed_digest, validate_update

MAX_INTAKE = 5
PATH = 'config/soups_review_manifest.json'
URL = 'https://raw.githubusercontent.com/RISEInfoSec/Alex/codex/soups-corpus-review/' + PATH


def prepare(snapshot, confirmed_snapshot, inputs, ledger, state, owner, run_id, *, observed_heads,
            source_attempts, source_progress, at=None, heartbeat=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware intake observation required')
    if not isinstance(inputs, dict) or observed_heads != {'review': inputs.get('review_commit'), 'main': inputs.get('main_commit')}:
        raise ValueError('Verified source heads required')
    if ledger != inputs.get('lifecycle') or state != inputs.get('worker_state'):
        raise ValueError('Intake state differs from verified source')
    expires = instant((state.get('lease') or {}).get('expires_at'))
    if not expires or expires - now <= timedelta(minutes=2):
        raise ValueError('Intake checkpoint reserve unavailable')
    manifests, registry = inputs.get('reconciliation_manifests'), inputs.get('registry')
    if not isinstance(manifests, dict) or not isinstance(registry, list) or not isinstance(inputs.get('lifecycle_policy'), dict):
        raise ValueError('Complete verified intake inputs required')
    entries = [item for item in registry if item.get('id') == 'soups']
    metadata = {(x.get('commit'), x.get('path')) for x in inputs.get('metadata', []) if isinstance(x, dict)}
    manifest = manifests.get('soups')
    if (len(entries) != 1 or entries[0].get('adapter') != 'soups' or entries[0].get('manifest_url') != URL
        or not isinstance(manifest, dict) or manifest != inputs.get('manifests', {}).get('soups')
        or (inputs['review_commit'], PATH) not in metadata):
        raise ValueError('Verified SOUPS manifest unavailable')
    plan(snapshot, confirmed_snapshot, manifests, ledger, registry, state, owner, run_id,
         source_attempts=source_attempts, source_progress=source_progress, at=now,
         heartbeat=heartbeat, review_head=inputs['review_commit'])
    checked = reconcile(snapshot, confirmed_snapshot, {k: v.get('records', []) for k, v in manifests.items()})
    excluded = {(x['collection'], x['candidate_id']) for x in checked['matched_decisions'] + checked['held']}
    # Historical decisions remain excluded even if their submission was later superseded.
    excluded.update((x['collection'], x['candidate_id']) for x in snapshot['decisions'])
    rows = manifest.get('records', []) + manifest.get('preflight_records', [])
    used_numbers, used_batches = {}, set()
    for row in rows:
        candidate = row['candidate_id']
        numbers = [row.get(k) for k in ('review_number', 'reserved_review_number') if row.get(k) is not None]
        if any(type(n) is not int or n < 1 for n in numbers) or len(set(numbers)) > 1:
            raise ValueError('Invalid SOUPS review number reservation')
        for number in set(numbers):
            if number in used_numbers and used_numbers[number] != candidate:
                raise ValueError('Conflicting SOUPS review number reservation')
            used_numbers[number] = candidate
        for key in ('review_batch', 'batch', 'reserved_review_batch'):
            if row.get(key) is not None:
                if type(row[key]) is not int or row[key] < 1: raise ValueError('Invalid SOUPS batch reservation')
                used_batches.add(row[key])
    for sub in snapshot['submissions']:
        if sub['collection'] == 'soups': used_batches.add(sub['batch'])
    for decision in snapshot['decisions']:
        if decision['collection'] == 'soups':
            n = decision['review_number']
            if n in used_numbers and used_numbers[n] != decision['candidate_id']:
                raise ValueError('SOUPS number conflicts with a historical decision')
            used_numbers[n] = decision['candidate_id']
    for sealed in manifest.get('sealed_review_batches', []):
        batch = sealed.get('batch') if isinstance(sealed, dict) else None
        if type(batch) is not int or batch < 1: raise ValueError('Invalid sealed SOUPS batch')
        used_batches.add(batch)
    eligible, held = [], Counter()
    for row in rows:
        cid = row['candidate_id']
        if (row.get('review_number') is not None or ('soups', cid) in excluded
            or 'soups:' + cid in ledger['records'] or row.get('decision', 'pending') not in ('pending', 'unreviewed')
            or row.get('publication_status') == 'published_live_verified'):
            continue
        if row.get('review_ready') is True or row.get('editorial_queue_eligible') is True or row.get('publication_approved') is True:
            held['inconsistent_readiness'] += 1; continue
        batches = {row[k] for k in ('review_batch', 'batch', 'reserved_review_batch') if row.get(k) is not None}
        if len(batches) > 1 or (batches and row.get('reserved_review_batch') is None):
            held['inconsistent_batch_reservation'] += 1; continue
        if reviewed_digest(row) != row.get('content_sha256'):
            held['reviewed_content_hash_mismatch'] += 1; continue
        eligible.append(cid)
    eligible.sort()
    selected = eligible[:MAX_INTAKE]
    if not selected:
        return {'status': 'no_soups_intake_due', 'held': dict(held), 'writes': 0, 'candidate_processing': False}
    proposed, lifecycle = deepcopy(manifest), deepcopy(ledger)
    by_id = {r['candidate_id']: r for r in proposed.get('records', []) + proposed.get('preflight_records', [])}
    next_number = max(used_numbers, default=0) + 1
    next_batch = max(used_batches, default=0) + 1
    for cid in selected:
        row = by_id[cid]
        if row.get('reserved_review_number') is None:
            row['reserved_review_number'] = next_number; next_number += 1
        if row.get('reserved_review_batch') is None:
            row['reserved_review_batch'] = next_batch
        entry = evaluate(row, at=now, policy=inputs['lifecycle_policy'])
        entry['evidence_location'] = PATH + '#' + cid
        entry['collection'] = 'soups'
        lifecycle['records']['soups:' + cid] = entry
    lifecycle['updated_at'] = now.isoformat()
    lifecycle['policy_version'] = inputs['lifecycle_policy'].get('version')
    lifecycle['counts'] = dict(Counter(x['state'] for x in lifecycle['records'].values()))
    lifecycle['source_counts'] = {c: dict(Counter(x['state'] for x in lifecycle['records'].values() if x.get('collection') == c))
                                  for c in sorted({x['collection'] for x in lifecycle['records'].values()})}
    validate_update(json.dumps(manifest), json.dumps(proposed))
    return {'status': 'prepared', 'proposed_manifest': proposed, 'proposed_ledger': lifecycle,
            'selected': selected, 'held': dict(held), 'writes': 0, 'candidate_processing': False,
            'requires_semantic_guard_and_live_recheck': True}
