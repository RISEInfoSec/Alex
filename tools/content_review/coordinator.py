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
from tools.content_review.source_unresolved import validate as validate_unresolved

INITIAL_LIMIT = 5
MAX_CANDIDATES = 10000


def plan(snapshot, confirmed_snapshot, manifests, ledger, registry, state,
         owner, run_id, *, source_attempts, source_progress, at=None, heartbeat=None, review_head=None, stages=None):
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
    started = instant(current.get('started_at'))
    if heartbeat is None:
        heartbeat_time = instant(current.get('observed_at'))
    else:
        from tools.content_review.heartbeat_evidence import verify
        heartbeat_time = verify(heartbeat, state, review_head, owner, run_id, at=now)
    if not started or not heartbeat_time or not started <= heartbeat_time <= now or (now-heartbeat_time).total_seconds() > 40:
        raise ValueError('A fresh matching start and heartbeat are required')
    if not isinstance(source_attempts, dict) or not isinstance(source_progress, dict):
        raise ValueError('Separate collection attempt and progress histories are required')
    valid_stages={'duplicates','source','metadata','quality','classification_and_serialization','recommendation_and_admission'}
    if stages is not None and (not isinstance(stages,(tuple,list)) or not stages or
                               any(not isinstance(x,str) or x not in valid_stages for x in stages) or len(stages)!=len(set(stages))):
        raise ValueError('Invalid bounded stage selection')
    if (source_attempts != state.get('source_attempts', {}) or
            source_progress != state.get('source_last_progress', {})):
        raise ValueError('Collection scheduling history differs from current worker state')
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
    unresolved_keys,unresolved_hosts=validate_unresolved(state.get('source_unresolved_requests',[]))
    def source_hold(item):
        key=(item['collection'],item['candidate_id'])
        if key in unresolved_keys:return True
        # A failed workflow may have followed an unknown redirect. Until its
        # request history is reconciled, no source destination is provably safe.
        return item['next_stage']=='source' and bool(unresolved_hosts)
    # APWG and corpus audit still require their own execution adapters. Virus
    # Bulletin has independently checked duplicate and source-reservation paths;
    # do not select its later gates until those paths have been implemented.
    special = {c['id'] for c in registry if c.get('adapter') in ('apwg_pending', 'corpus_audit')}
    supported_stages={'duplicates','source','metadata'}
    eligible = [item for item in result['selected'] if item['collection'] not in special
                and not source_hold(item)
                and item['next_stage'] in supported_stages
                and (item['collection'] != 'virusbulletin' or item['next_stage'] in ('duplicates', 'source'))]
    stage_eligible=[item for item in eligible if stages is None or item['next_stage'] in stages]
    history=state.get('run_history',[])
    if not isinstance(history,list) or any(not isinstance(x,dict) or not x.get('run_id') for x in history):
        raise ValueError('Run history is unavailable for candidate rotation')
    offset=(len(history)*INITIAL_LIMIT)%len(stage_eligible) if stage_eligible else 0
    rotated=stage_eligible[offset:]+stage_eligible[:offset]
    selected = [{**item, 'content_sha256': index[(item['collection'], item['candidate_id'])]['content_sha256']}
                for item in rotated[:INITIAL_LIMIT]]
    # Report due work even when an executor is not yet available. Hiding it as
    # zero would make the coverage report look complete while skipping a source.
    available = Counter(x['collection'] for x in result['selected'])
    selected_counts = Counter(x['collection'] for x in selected)
    executable = Counter(x['collection'] for x in eligible)
    unsupported_gates=Counter(x['collection'] for x in result['selected']
                              if x['collection'] not in special and x['next_stage'] not in supported_stages)
    unresolved=Counter(x['collection'] for x in result['selected'] if source_hold(x))
    decisions = Counter(x['collection'] for x in result['reconciliation']['matched_decisions'])
    decided_keys = {(x['collection'], x['candidate_id']) for x in result['reconciliation']['matched_decisions']}
    held_keys = {(x['collection'], x['candidate_id']) for x in result['reconciliation']['held']}
    held_keys.update((x['collection'],x['candidate_id']) for x in snapshot['decisions']
                     if (x['collection'],x['candidate_id']) in index and (x['collection'],x['candidate_id']) not in decided_keys)
    held = Counter(collection for collection,_ in held_keys)
    entries = ledger.get('records') if isinstance(ledger, dict) else None
    if not isinstance(entries, dict):
        raise ValueError('Complete candidate lifecycle is required')
    missing_lifecycle, unnumbered_intake = Counter(), Counter()
    for (collection, candidate_id), row in index.items():
        key = (collection, candidate_id)
        if (row.get('decision', 'pending') in ('pending', 'unreviewed')
            and row.get('publication_status') != 'published_live_verified' and key not in decided_keys
            and key not in held_keys and collection + ':' + candidate_id not in entries):
            if type(row.get('review_number')) is int and row['review_number'] > 0:
                missing_lifecycle[collection] += 1
            else:
                unnumbered_intake[collection] += 1
    coverage = []
    for entry in registry:
        collection = entry['id']
        if collection not in manifests:
            reason = 'manifest_unavailable'
        elif available[collection] and (collection in special or (collection == 'virusbulletin' and not executable[collection])):
            reason = 'separate_collection_adapter_required'
        elif selected_counts[collection]:
            reason = 'selected_for_next_gate'
        elif unresolved[collection] and not executable[collection]:
            reason = 'unresolved_source_failure'
        elif unsupported_gates[collection] and not executable[collection]:
            reason = 'separate_gate_executor_required'
        elif stages is not None and executable[collection] and not any(x['collection']==collection for x in stage_eligible):
            reason = 'deferred_by_stage_filter'
        elif available[collection]:
            reason = 'deferred_by_candidate_ceiling'
        elif held[collection]:
            reason = 'decision_reconciliation_hold'
        elif missing_lifecycle[collection]:
            reason = 'lifecycle_entry_missing'
        elif unnumbered_intake[collection]:
            reason = 'unnumbered_intake_required'
        else:
            reason = 'no_due_candidate_in_supplied_snapshot'
        coverage.append({'collection': collection, 'eligible': available[collection],
                         'selected': selected_counts[collection], 'decision_holds': held[collection],
                         'unsupported_gate_count': unsupported_gates[collection],
                         'unresolved_source_count': unresolved[collection],
                         'missing_lifecycle': missing_lifecycle[collection],
                         'unnumbered_intake': unnumbered_intake[collection],
                         'matched_review_decisions': decisions[collection],
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
                      source_progress=request['source_progress'], heartbeat=request.get('heartbeat'),
                      review_head=request.get('review_head'))
        print(json.dumps(result, sort_keys=True))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc) if isinstance(exc, ValueError) else 'Invalid plan input'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
