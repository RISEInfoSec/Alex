"""Build a source gate checkpoint for independent validation; never write it."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.lifecycle import GATES, current_pass, evaluate, instant, record_attempt
from tools.content_review.source_gate_stage import prepare as stage_source
from tools.content_review.stage_summary import derive, validate_summary
from tools.content_review.verified_inputs import _git


def prepare(repo, snapshot, confirmed, inputs, ledger, state, owner, run_id, collection, candidate_id, gate,
            *, observed_heads, source_attempts, source_progress, at=None, heartbeat=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware checkpoint time required')
    expiry, started = instant((state.get('lease') or {}).get('expires_at')), instant((state.get('current_run') or {}).get('started_at'))
    if not expiry or not started or (expiry-now).total_seconds() <= 120 or not 0 <= (now-started).total_seconds() <= 600:
        raise ValueError('Source checkpoint reserve or work window unavailable')
    proposal = stage_source(repo, snapshot, confirmed, inputs, ledger, state, owner, run_id, collection, candidate_id, gate,
                            observed_heads=observed_heads, source_attempts=source_attempts, source_progress=source_progress,
                            at=now, heartbeat=heartbeat)
    if proposal.get('status') != 'prepared':
        return {'status': 'held', 'reason': proposal.get('reason', 'source_gate_unavailable'), 'writes': 0}
    if not isinstance(inputs.get('lifecycle_policy'), dict) or not isinstance(inputs.get('preflight_status'), dict):
        raise ValueError('Lifecycle policy and stage status required')
    entries = [x for x in inputs['registry'] if x.get('id') == collection]
    if len(entries) != 1:
        raise ValueError('Registered source collection unavailable')
    name = (entries[0].get('manifest_url') or '').rsplit('/', 1)[-1]
    if not re.fullmatch(r'[a-zA-Z0-9_-]+\.json', name):
        raise ValueError('Registered manifest path invalid')
    manifest_path = 'config/' + name
    ledger_path, stage_path, state_path = ('config/content_review_candidate_lifecycle.json',
                                          'config/content_review_preflight_status.json', 'config/content_review_worker_status.json')
    base_paths = (manifest_path, ledger_path, stage_path, state_path)
    metadata = {x.get('path'): x for x in inputs['metadata']
                if isinstance(x, dict) and x.get('commit') == inputs['review_commit'] and x.get('path')}
    if any(path not in metadata for path in base_paths):
        raise ValueError('Verified source base metadata unavailable')
    key = collection + ':' + candidate_id
    old_entry = ledger.get('records', {}).get(key)
    if not isinstance(old_entry, dict):
        raise ValueError('Candidate lifecycle unavailable')
    receipt_id = hashlib.sha256((run_id+'\0'+key+'\0'+proposal['content_sha256']+'\0'+gate).encode()).hexdigest()
    receipt_path = 'config/content_review_source_gate_checkpoints/' + receipt_id + '.json'
    if _git(repo, 'ls-tree', '-z', inputs['review_commit'], '--', receipt_path):
        raise ValueError('Source gate receipt exists; reconcile before retrying')
    rows = proposal['manifest'].get('records', []) + proposal['manifest'].get('preflight_records', [])
    selected = [x for x in rows if x.get('candidate_id') == candidate_id]
    if len(selected) != 1:
        raise ValueError('Proposed candidate identity invalid')
    row = selected[0]
    updated_ledger = deepcopy(ledger)
    attempt = record_attempt(old_entry, attempt_id=receipt_id, at=now, stage=gate, outcome='success',
                             reason='Independently verifiable retained source evidence supports this narrow gate.', evidence_ref=receipt_path)
    updated_ledger['records'][key] = evaluate(row, attempt, now, inputs['lifecycle_policy'])
    updated_ledger['updated_at'] = now.isoformat()
    updated_ledger['counts'] = dict(Counter(x['state'] for x in updated_ledger['records'].values()))
    updated_ledger['source_counts'] = {c: dict(Counter(x['state'] for x in updated_ledger['records'].values() if x.get('collection') == c))
                                       for c in sorted({x.get('collection') for x in updated_ledger['records'].values() if x.get('collection')})}
    status = deepcopy(inputs['preflight_status'])
    records = status.get('records')
    if not isinstance(records, list):
        raise ValueError('Stage records unavailable')
    matches = [x for x in records if x.get('collection') == collection and x.get('candidate_id') == candidate_id]
    original = [x for x in inputs['manifests'][collection].get('records', []) + inputs['manifests'][collection].get('preflight_records', [])
                if x.get('candidate_id') == candidate_id]
    if (len(matches) != 1 or len(original) != 1 or matches[0].get('content_sha256') != row['content_sha256'] or
            matches[0].get('checks') != original[0].get('preflight', {}).get('checks', {})):
        raise ValueError('Manifest and stage evidence differ')
    matches[0]['checks'][gate] = deepcopy(row['preflight']['checks'][gate])
    matches[0]['blockers'] = [g for g in GATES if not current_pass(row, g)]
    matches[0]['status'] = 'held' if matches[0]['blockers'] else 'passed_awaiting_batch_admission'
    matches[0]['review_ready'] = False
    status['summary'] = derive(records)
    status['updated_at'] = status['summary_observed_at'] = now.isoformat()
    validate_summary(status)
    updated_state = deepcopy(state)
    attempts = updated_state.setdefault('source_attempts', {})
    if not isinstance(attempts, dict):
        raise ValueError('Collection attempt history invalid')
    attempts[collection] = {'at': now.isoformat(), 'run_id': run_id, 'gate': gate}
    receipt = {'schema_version': 1, 'kind': 'source_gate_checkpoint', 'run_id': run_id,
               'collection': collection, 'candidate_id': candidate_id, 'gate': gate,
               'content_sha256': proposal['content_sha256'], 'checked_at': now.isoformat(), 'status': 'passed',
               'source_review_commit': inputs['review_commit'], 'source_main_commit': inputs['main_commit'],
               'source_receipt': row['preflight']['checks'][gate]['evidence']['source_receipt'],
               'provider_requests': 0, 'paid_requests': 0, 'openalex_requests': 0, 'publication_approved': False}
    d1 = reconcile(snapshot, confirmed, {k: v.get('records', []) for k, v in inputs['reconciliation_manifests'].items()})
    objects = {manifest_path: proposal['manifest'], ledger_path: updated_ledger, stage_path: status,
               state_path: updated_state, receipt_path: receipt}
    return {'status': 'prepared', 'files': {path: json.dumps(value, ensure_ascii=False, indent=2)+'\n' for path, value in objects.items()},
            'base_blobs': {path: metadata[path] for path in base_paths}, 'new_paths_must_be_absent': [receipt_path],
            'd1_fingerprint_private': d1['snapshot_sha256'], 'requires_independent_site_validation': True,
            'requires_remote_lease_and_snapshot_recheck': True, 'writes': 0}
