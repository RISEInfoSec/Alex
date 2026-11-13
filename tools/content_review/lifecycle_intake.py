"""Prepare bounded additive lifecycle entries; never write or infer decisions.

This preparer is not a worker or an atomic checkpoint. A caller must validate
its proposal against immutable inputs and recheck D1, both source heads and the
live lease before a separately guarded expected-head write.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re

from tools.content_review.coordinator import plan
from tools.content_review.d1_reconcile import reconcile
from tools.content_review.lifecycle import evaluate, instant
from tools.content_review.manifest_integrity import reviewed_digest

MAX_ADDITIONS = 5
BASE = 'https://raw.githubusercontent.com/RISEInfoSec/Alex/codex/soups-corpus-review/config/'


def prepare(snapshot, confirmed_snapshot, inputs, ledger, state, owner, run_id, *, observed_heads,
            source_attempts, source_progress, at=None, heartbeat=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware lifecycle observation is required')
    if not isinstance(inputs, dict) or not isinstance(observed_heads, dict):
        raise ValueError('Verified lifecycle inputs and source heads are required')
    if (observed_heads.get('review') != inputs.get('review_commit') or
        observed_heads.get('main') != inputs.get('main_commit')):
        raise ValueError('Lifecycle source heads changed')
    if ledger != inputs.get('lifecycle') or state != inputs.get('worker_state'):
        raise ValueError('Lifecycle or worker state differs from verified source')
    expiry = instant((state.get('lease') or {}).get('expires_at'))
    if not expiry or expiry - now <= timedelta(minutes=2):
        raise ValueError('Lifecycle checkpoint reserve is unavailable')
    if not isinstance(inputs.get('lifecycle_policy'), dict):
        raise ValueError('Committed lifecycle policy is required')
    manifests = inputs.get('reconciliation_manifests')
    registry = inputs.get('registry')
    if not isinstance(manifests, dict) or not isinstance(registry, list):
        raise ValueError('Complete collection inputs are required')
    # This enforces the same current lease, heartbeat, D1 and registry checks
    # as candidate planning. It does not by itself perform an attempt.
    plan(snapshot, confirmed_snapshot, manifests, ledger, registry, state, owner, run_id,
         source_attempts=source_attempts, source_progress=source_progress, at=now,
         heartbeat=heartbeat, review_head=inputs['review_commit'])
    checked = reconcile(snapshot, confirmed_snapshot, {k: v.get('records', []) for k, v in manifests.items()})
    excluded = {(x['collection'], x['candidate_id']) for x in checked['matched_decisions'] + checked['held']}
    # A later submission can supersede a decision without erasing its review
    # history. Do not initialize a previously decided candidate as untouched.
    excluded.update((x['collection'], x['candidate_id']) for x in snapshot['decisions'])
    metadata = {(x.get('commit'), x.get('path')) for x in inputs.get('metadata', []) if isinstance(x, dict)}
    groups, held = {}, Counter()
    for collection in registry:
        cid = collection['id']
        if collection.get('adapter') not in ('soups', 'normalized') or cid == 'virusbulletin':
            continue
        manifest = manifests.get(cid)
        url = collection.get('manifest_url') or ''
        name = url[len(BASE):] if url.startswith(BASE) else ''
        path = 'config/' + name
        if (not isinstance(manifest, dict) or not re.fullmatch(r'[a-zA-Z0-9_-]+\.json', name)
            or (inputs['review_commit'], path) not in metadata):
            raise ValueError('Verified lifecycle manifest is unavailable')
        for row in manifest.get('records', []) + manifest.get('preflight_records', []):
            candidate = row['candidate_id']
            key = cid + ':' + candidate
            if (key in ledger['records'] or (cid, candidate) in excluded or
                row.get('decision', 'pending') not in ('pending', 'unreviewed') or
                row.get('publication_status') == 'published_live_verified'):
                continue
            if type(row.get('review_number')) is not int or row['review_number'] < 1:
                held['unnumbered_intake_required'] += 1
                continue
            try:
                if reviewed_digest(row) != row.get('content_sha256'):
                    held['reviewed_content_hash_mismatch'] += 1
                    continue
                entry = evaluate(row, at=now, policy=inputs['lifecycle_policy'])
            except (KeyError, TypeError, ValueError):
                held['invalid_lifecycle_inputs'] += 1
                continue
            entry['evidence_location'] = path + '#' + candidate
            entry['collection'] = cid
            groups.setdefault(cid, []).append((key, entry))
    for group in groups.values():
        group.sort(key=lambda pair: pair[0])

    def last_served(cid):
        values = [source_attempts.get(cid, {}).get('at'), source_progress.get(cid, {}).get('at')]
        dates = [instant(value).timestamp() for value in values if value and instant(value)]
        return max(dates, default=float('-inf'))

    order = sorted(groups, key=lambda cid: (last_served(cid), cid != 'weekly', cid))
    chosen = []
    while len(chosen) < MAX_ADDITIONS and any(groups.values()):
        for cid in order:
            if groups[cid] and len(chosen) < MAX_ADDITIONS:
                chosen.append(groups[cid].pop(0))
    if not chosen:
        return {'status': 'no_numbered_lifecycle_entries_due', 'held': dict(held),
                'writes': 0, 'candidate_processing': False}
    proposed = deepcopy(ledger)
    for key, entry in chosen:
        proposed['records'][key] = entry
    proposed['updated_at'] = now.isoformat()
    proposed['policy_version'] = inputs['lifecycle_policy'].get('version')
    proposed['counts'] = dict(Counter(x['state'] for x in proposed['records'].values()))
    proposed['source_counts'] = {cid: dict(Counter(x['state'] for x in proposed['records'].values()
        if x.get('collection') == cid)) for cid in sorted({x['collection'] for x in proposed['records'].values()})}
    return {'status': 'prepared', 'proposed_ledger': proposed, 'added_keys': [key for key, _ in chosen],
            'held': dict(held), 'writes': 0, 'candidate_processing': False,
            'requires_semantic_guard_and_live_recheck': True}
