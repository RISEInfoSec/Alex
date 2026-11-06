"""Prepare a bounded review pass from verified inputs; does not perform it.

The caller owns native access, atomic lease updates, checkpoints and execution.
No network, provider calls, GitHub writes, or publication occur in this module.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import sys

from tools.content_review.d1_reconcile import select_reconciled
from tools.content_review.lifecycle import instant

INITIAL_LIMIT = 5
MAX_CANDIDATES = 10000


def plan(snapshot, confirmed_snapshot, manifests, ledger, registry, state,
         owner, run_id, *, source_attempts, source_progress, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware observation required')
    if not isinstance(state, dict):
        raise ValueError('Current worker state is required')
    lease = state.get('lease') or {}
    expiry = instant(lease.get('expires_at'))
    if (not owner or not run_id or lease.get('owner') != owner or lease.get('run_id') != run_id
        or not expiry or expiry <= now):
        raise ValueError('A matching unexpired single-writer lease is required')
    current = state.get('current_run') or {}
    if current.get('run_id') != run_id or current.get('application_status') != 'running':
        raise ValueError('A matching running worker observation is required')
    started, heartbeat = instant(current.get('started_at')), instant(current.get('observed_at'))
    if not started or not heartbeat or not started <= heartbeat <= now or (now-heartbeat).total_seconds() > 40:
        raise ValueError('A fresh matching start and heartbeat are required')
    if not isinstance(source_attempts, dict) or not isinstance(source_progress, dict):
        raise ValueError('Separate collection attempt and progress histories are required')
    if not isinstance(registry, list) or not all(isinstance(c, dict) and isinstance(c.get('id'), str) and c['id'] for c in registry):
        raise ValueError('A complete collection registry is required')
    names = [c['id'] for c in registry]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate collection in registry')
    if not isinstance(manifests, dict) or any(k not in names for k in manifests):
        raise ValueError('Manifest collection is not in the registry')
    index = {}
    for collection, manifest in manifests.items():
        if not isinstance(manifest, dict):
            raise ValueError('Invalid collection manifest')
        for field in ('records', 'preflight_records'):
            rows = manifest.get(field, [])
            if not isinstance(rows, list):
                raise ValueError('Incomplete manifest section')
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('candidate_id'), str) or not row['candidate_id']:
                    raise ValueError('Missing manifest candidate identity')
                key = (collection, row['candidate_id'])
                if key in index:
                    raise ValueError('Duplicate candidate within collection')
                index[key] = row
                if len(index) > MAX_CANDIDATES:
                    raise ValueError('Candidate inventory exceeds the bounded plan')

    result = select_reconciled(snapshot, confirmed_snapshot, manifests, ledger,
                               limit=MAX_CANDIDATES, source_progress=source_progress,
                               source_attempts=source_attempts)
    # APWG and the existing-corpus audit require their separate adapters. They
    # are never silently reclassified as normalized intake.
    special = {c['id'] for c in registry if c.get('adapter') in ('apwg_pending', 'corpus_audit')}
    eligible = [item for item in result['selected'] if item['collection'] not in special]
    selected = [{**item, 'content_sha256': index[(item['collection'], item['candidate_id'])]['content_sha256']}
                for item in eligible[:INITIAL_LIMIT]]
    available, selected_counts = Counter(x['collection'] for x in eligible), Counter(x['collection'] for x in selected)
    held = Counter(x['collection'] for x in result['reconciliation']['held'])
    coverage = []
    for entry in registry:
        collection = entry['id']
        if collection in special:
            reason = 'separate_collection_adapter_required'
        elif collection not in manifests:
            reason = 'manifest_unavailable'
        elif selected_counts[collection]:
            reason = 'selected_for_next_gate'
        elif available[collection]:
            reason = 'deferred_by_candidate_ceiling'
        elif held[collection]:
            reason = 'decision_reconciliation_hold'
        else:
            reason = 'no_due_candidate_in_supplied_snapshot'
        coverage.append({'collection': collection, 'eligible': available[collection],
                         'selected': selected_counts[collection], 'decision_holds': held[collection],
                         'disposition': reason})
    return {'status': 'plan_only', 'selected': selected, 'coverage': coverage,
            'candidate_limit': INITIAL_LIMIT, 'openalex_requests_permitted': 0,
            'provider_requests': 0, 'paid_requests': 0, 'writes': 0,
            'snapshot_recheck_required': True, 'lease_readback_required': True,
            'decision_counts': result['reconciliation']['counts']}


def main():
    # The JSON input is private; stdout contains only the public candidate plan
    # and aggregate decision counts, never the D1 rows or user identifiers.
    try:
        request = json.loads(sys.stdin.readline())
        result = plan(request['snapshot'], request['confirmed_snapshot'], request['manifests'],
                      request['ledger'], request['registry'], request['state'],
                      request['owner'], request['run_id'], source_attempts=request['source_attempts'],
                      source_progress=request['source_progress'])
        print(json.dumps(result, sort_keys=True))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc) if isinstance(exc, ValueError) else 'Invalid plan input'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
