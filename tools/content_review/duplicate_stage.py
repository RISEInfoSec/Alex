"""Prepare one bounded local duplicate check from verified inputs.

No network, manifest mutation, checkpoint, decision or publication is performed.
The caller must independently recheck D1, Git heads and the live lease before
applying any returned evidence through the established checkpoint contract.
"""
from datetime import datetime, timezone
from copy import deepcopy
import json

from tools.content_review.coordinator import plan
from tools.content_review.duplicate_evidence import audit
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.manifest_integrity import validate_update


def evaluate(snapshot, confirmed_snapshot, inputs, ledger, state, owner, run_id,
             collection, candidate_id, *, observed_heads, source_attempts, source_progress, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(inputs, dict) or not isinstance(observed_heads, dict):
        raise ValueError('Verified input bundle and current heads are required')
    if (observed_heads.get('review') != inputs.get('review_commit')
        or observed_heads.get('main') != inputs.get('main_commit')):
        raise ValueError('Source heads changed or are unavailable')
    for key, kind in (('registry', list), ('manifests', dict), ('public', list),
                      ('original_queue', list), ('current_queue', list), ('exclusion_keys', set),
                      ('metadata', list)):
        if not isinstance(inputs.get(key), kind):
            raise ValueError('Verified input bundle is incomplete')
    if not inputs['metadata'] or not inputs['public']:
        raise ValueError('Verified input provenance and nonempty public corpus are required')
    if ledger != inputs.get('lifecycle') or state != inputs.get('worker_state'):
        raise ValueError('Worker state or lifecycle differs from the verified source commit')
    # These distinct routes require their own hash/decision adapters.
    if collection in ('apwg', 'corpus-audit', 'virusbulletin'):
        raise ValueError('Collection requires its separate source adapter')
    # The Site's filtered APWG view is used only for decision reconciliation;
    # the original source remains present in duplicate comparisons.
    normalized = inputs.get('reconciliation_manifests')
    if normalized is None:normalized = {k: v for k, v in inputs['manifests'].items() if k != 'apwg'}
    if not isinstance(normalized,dict):raise ValueError('Invalid reconciliation manifests')
    selection = plan(snapshot, confirmed_snapshot, normalized, ledger, inputs['registry'],
                     state, owner, run_id, source_attempts=source_attempts,
                     source_progress=source_progress, at=now)
    match = [x for x in selection['selected'] if x['collection'] == collection and x['candidate_id'] == candidate_id]
    if len(match) != 1 or match[0]['next_stage'] != 'duplicates':
        raise ValueError('Candidate is not selected for its duplicate gate')
    rows = inputs['manifests'][collection].get('records', []) + inputs['manifests'][collection].get('preflight_records', [])
    found = [x for x in rows if x.get('candidate_id') == candidate_id]
    if len(found) != 1 or found[0].get('content_sha256') != match[0]['content_sha256']:
        raise ValueError('Candidate identity or reviewed hash changed')
    row = found[0]
    if reviewed_digest(row) != row['content_sha256']:
        raise ValueError('Candidate content does not match its reviewed hash')
    collections = {'public': inputs['public']}
    for name, manifest in inputs['manifests'].items():
        collections[name] = manifest.get('records', []) + manifest.get('preflight_records', [])
    upstream = inputs['original_queue'] + inputs['current_queue']
    result = audit(row, collections, upstream, inputs['exclusion_keys'], source_collection=collection)
    return {'collection': collection, 'candidate_id': candidate_id,
            'content_sha256': row['content_sha256'], 'gate': 'duplicates',
            'status': result['status'], 'evidence': result, 'checked_at': now.isoformat(),
            'review_commit': inputs['review_commit'], 'main_commit': inputs['main_commit'],
            'provider_requests': 0, 'paid_requests': 0, 'writes': 0,
            'recheck_d1_heads_and_lease_before_checkpoint': True}


def propose_checkpoint(snapshot, confirmed_snapshot, inputs, ledger, state, owner, run_id,
                       collection, candidate_id, *, observed_heads, source_attempts, source_progress, at=None):
    """Prepare an evidence-bound manifest change; never write or publish it."""
    result = evaluate(snapshot, confirmed_snapshot, inputs, ledger, state, owner, run_id,
                      collection, candidate_id, observed_heads=observed_heads,
                      source_attempts=source_attempts, source_progress=source_progress, at=at)
    if result['status'] != 'passed':
        return {'status': 'held', 'result': result, 'manifest': None, 'writes': 0}
    before = inputs['manifests'][collection]
    after = deepcopy(before)
    rows = after.get('records', []) + after.get('preflight_records', [])
    matches = [row for row in rows if row.get('candidate_id') == candidate_id]
    if len(matches) != 1:
        raise ValueError('Candidate identity changed before checkpoint preparation')
    row = matches[0]
    if row.get('decision', 'pending') not in ('pending', 'unreviewed'):
        raise ValueError('A completed decision cannot be changed by duplicate processing')
    preflight = row.setdefault('preflight', {})
    if not isinstance(preflight, dict):
        raise ValueError('Invalid candidate preflight')
    checks = preflight.setdefault('checks', {})
    if not isinstance(checks, dict):
        raise ValueError('Invalid candidate preflight checks')
    previous = deepcopy(checks.get('duplicates'))
    checks['duplicates'] = {'status': 'passed', 'content_sha256': result['content_sha256'],
                            'checked_at': result['checked_at'],
                            'evidence': {'method': 'complete immutable corpus, exclusions, registered collections and upstream inventories',
                                         'review_commit': result['review_commit'], 'main_commit': result['main_commit'],
                                         'input_blobs': deepcopy(inputs['metadata']),
                                         'matches': result['evidence']['matches'],
                                         'exclusions': result['evidence']['exclusions'],
                                         'upstream_aliases': result['evidence']['upstream_aliases']}}
    if previous is not None:
        checks['duplicates']['prior_evidence'] = previous
    validate_update(json.dumps(before), json.dumps(after))
    return {'status': 'prepared', 'result': result, 'manifest': after, 'writes': 0,
            'requires_remote_lease_and_snapshot_recheck': True}
