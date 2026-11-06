"""Prepare, but never publish, an atomic duplicate-gate checkpoint bundle."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.duplicate_stage import propose_checkpoint
from tools.content_review.lifecycle import GATES, current_pass, evaluate, instant, record_attempt
from tools.content_review.stage_summary import derive, validate_summary


def prepare(snapshot, confirmed_snapshot, inputs, ledger, state, owner, run_id,
            collection, candidate_id, *, observed_heads, source_attempts, source_progress, at=None):
    """Return an all-or-nothing bundle; the caller must still perform remote CAS.

    D1 and both Git heads must be rechecked after preparation, immediately
    before expected-head publication. No D1 rows or identities are persisted.
    """
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware checkpoint time required')
    expiry = instant((state.get('lease') or {}).get('expires_at'))
    started = instant((state.get('current_run') or {}).get('started_at'))
    if not expiry or not started or (expiry-now).total_seconds() <= 120 or not 0 <= (now-started).total_seconds() <= 600:
        raise ValueError('Checkpoint reserve or original work window is unavailable')
    stage = propose_checkpoint(snapshot, confirmed_snapshot, inputs, ledger, state, owner, run_id,
                               collection, candidate_id, observed_heads=observed_heads,
                               source_attempts=source_attempts, source_progress=source_progress, at=now)
    if stage['status'] != 'prepared':
        return {'status': 'held', 'result': stage['result'], 'writes': 0}
    if not isinstance(inputs.get('lifecycle_policy'), dict) or not isinstance(inputs.get('preflight_status'), dict):
        raise ValueError('Verified lifecycle policy and stage status are required')
    collection_entry = next((x for x in inputs['registry'] if x.get('id') == collection), None)
    if not collection_entry:
        raise ValueError('Collection is not in the verified registry')
    name = (collection_entry.get('manifest_url') or '').rsplit('/', 1)[-1]
    if not re.fullmatch(r'[a-zA-Z0-9_-]+\.json', name):
        raise ValueError('Invalid verified manifest name')
    manifest_path = 'config/' + name
    ledger_path = 'config/content_review_candidate_lifecycle.json'
    stage_path = 'config/content_review_preflight_status.json'
    state_path = 'config/content_review_worker_status.json'
    base_paths = (manifest_path, ledger_path, stage_path, state_path)
    metadata = {x.get('path'): x for x in inputs['metadata']
                if isinstance(x, dict) and x.get('commit') == inputs['review_commit'] and x.get('path')}
    if any(path not in metadata for path in base_paths):
        raise ValueError('Missing verified base blob metadata')
    result = stage['result']
    candidate_key = collection + ':' + candidate_id
    old_entry = ledger.get('records', {}).get(candidate_key)
    if not isinstance(old_entry, dict):
        raise ValueError('Current candidate lifecycle is missing')
    receipt_id = hashlib.sha256((run_id + '\0' + candidate_key + '\0' + result['content_sha256']).encode()).hexdigest()
    receipt_path = 'config/content_review_mechanical_checkpoints/' + receipt_id + '.json'
    updated_ledger = deepcopy(ledger)
    attempt = record_attempt(old_entry, attempt_id=receipt_id, at=now, stage='duplicates',
                             outcome='success', reason='Complete local duplicate and exclusion check passed.',
                             evidence_ref=receipt_path)
    after_rows = stage['manifest'].get('records', []) + stage['manifest'].get('preflight_records', [])
    row = next((x for x in after_rows if x.get('candidate_id') == candidate_id), None)
    if not row:
        raise ValueError('Prepared candidate is missing')
    updated_ledger['records'][candidate_key] = evaluate(row, attempt, now, inputs['lifecycle_policy'])
    updated_ledger['updated_at'] = now.isoformat()
    updated_ledger['counts'] = dict(Counter(x['state'] for x in updated_ledger['records'].values()))
    updated_ledger['source_counts'] = {c: dict(Counter(x['state'] for x in updated_ledger['records'].values() if x.get('collection') == c))
        for c in sorted({x.get('collection') for x in updated_ledger['records'].values() if x.get('collection')})}

    status = deepcopy(inputs['preflight_status'])
    records = status.get('records')
    if not isinstance(records, list):
        raise ValueError('Stage status records are unavailable')
    matches = [x for x in records if x.get('collection') == collection and x.get('candidate_id') == candidate_id]
    if len(matches) != 1 or matches[0].get('content_sha256') != result['content_sha256']:
        raise ValueError('Stage status identity is missing, ambiguous or stale')
    checks = matches[0].get('checks')
    if not isinstance(checks, dict):
        raise ValueError('Stage status checks are unavailable')
    before_row = next(x for x in (inputs['manifests'][collection].get('records', []) +
                                   inputs['manifests'][collection].get('preflight_records', []))
                      if x.get('candidate_id') == candidate_id)
    if checks != before_row.get('preflight', {}).get('checks', {}):
        raise ValueError('Stage and manifest checks disagree; reconcile before checkpoint')
    checks['duplicates'] = deepcopy(row['preflight']['checks']['duplicates'])
    matches[0]['blockers'] = [gate for gate in GATES if not current_pass(row, gate)]
    matches[0]['status'] = 'held' if matches[0]['blockers'] else 'passed_awaiting_batch_admission'
    matches[0]['review_ready'] = False
    status['summary'] = derive(records)
    status['updated_at'] = now.isoformat()
    status['summary_observed_at'] = now.isoformat()
    validate_summary(status)

    updated_state = deepcopy(state)
    attempts = updated_state.setdefault('source_attempts', {})
    progress = updated_state.setdefault('source_last_progress', {})
    if not isinstance(attempts, dict) or not isinstance(progress, dict):
        raise ValueError('Invalid collection progress history')
    attempts[collection] = {'at': now.isoformat(), 'run_id': run_id, 'gate': 'duplicates'}
    # A local duplicate check is not a successful source retrieval. Record it
    # for fair scheduling without manufacturing source progress.
    receipt = {'schema_version': 1, 'kind': 'duplicate_checkpoint', 'run_id': run_id,
               'collection': collection, 'candidate_id': candidate_id,
               'content_sha256': result['content_sha256'], 'checked_at': now.isoformat(),
               'status': 'passed', 'source_review_commit': inputs['review_commit'],
               'source_main_commit': inputs['main_commit'], 'provider_requests': 0,
               'paid_requests': 0, 'openalex_requests': 0, 'publication_approved': False}
    # This fingerprint stays in coordinator memory, not in the public receipt.
    sources = inputs.get('reconciliation_manifests')
    if sources is None:sources = {k: v for k, v in inputs['manifests'].items() if k != 'apwg'}
    normalized = {k: v.get('records', []) for k, v in sources.items()}
    d1 = reconcile(snapshot, confirmed_snapshot, normalized)
    objects = {manifest_path: stage['manifest'], ledger_path: updated_ledger, stage_path: status,
               state_path: updated_state, receipt_path: receipt}
    return {'status': 'prepared', 'files': {path: json.dumps(value, ensure_ascii=False, indent=2) + '\n'
                                             for path, value in objects.items()},
            'base_blobs': {path: metadata[path] for path in base_paths},
            'new_paths_must_be_absent': [receipt_path], 'd1_fingerprint_private': d1['snapshot_sha256'],
            'requires_remote_lease_and_snapshot_recheck': True, 'writes': 0}
