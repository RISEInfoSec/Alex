"""Verify a prepared duplicate checkpoint against immutable local Git objects.

No remote reads or writes are performed. The caller must independently verify
the remote heads, D1 state and live lease, then use a single expected-head update.
Private D1 snapshots and fingerprints must remain outside committed files.
"""
from copy import deepcopy
from collections import Counter
import hashlib
import json
import re

from tools.content_review.checkpoint_transport import validate
from tools.content_review.lifecycle import GATES, current_pass, evaluate, instant, record_attempt
from tools.content_review.manifest_integrity import validate_update
from tools.content_review.stage_summary import validate_summary
from tools.content_review.verified_inputs import MAX_BLOB_BYTES, SHA, _git, _path_blob


def _only_changed(before, after, allowed):
    return {k: v for k, v in before.items() if k not in allowed} == {
        k: v for k, v in after.items() if k not in allowed}


def _manifest(before, after, candidate, content_sha256):
    validate_update(json.dumps(before), json.dumps(after))
    left, right = deepcopy(before), deepcopy(after)
    old_rows, new_rows = [], []
    for key in ('records', 'preflight_records'):
        a, b = left.get(key, []), right.get(key, [])
        if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
            raise ValueError('Manifest inventory changed')
        old_rows.extend(a); new_rows.extend(b)
    old = [r for r in old_rows if r.get('candidate_id') == candidate]
    new = [r for r in new_rows if r.get('candidate_id') == candidate]
    if len(old) != 1 or len(new) != 1:
        raise ValueError('Checkpoint candidate identity is ambiguous')
    if old[0].get('content_sha256') != content_sha256 or new[0].get('content_sha256') != content_sha256:
        raise ValueError('Checkpoint candidate content hash differs from receipt')
    new_row = deepcopy(new[0])
    old_checks = old[0].get('preflight', {}).get('checks', {})
    new_checks = new[0].get('preflight', {}).get('checks', {})
    if not isinstance(old_checks, dict) or not isinstance(new_checks, dict):
        raise ValueError('Checkpoint checks are missing')
    previous = old_checks.pop('duplicates', None)
    updated = new_checks.pop('duplicates', None)
    if not isinstance(updated, dict) or updated.get('status') != 'passed':
        raise ValueError('Duplicate check did not pass')
    if previous is not None and updated.get('prior_evidence') != previous:
        raise ValueError('Prior duplicate evidence is not preserved')
    if left != right:
        raise ValueError('Checkpoint changes unrelated manifest content')
    return new_row


def _stage(before, after, collection, candidate, manifest_row):
    validate_summary(after)
    if not _only_changed(before, after, {'records', 'summary', 'updated_at', 'summary_observed_at'}):
        raise ValueError('Checkpoint changes unrelated stage metadata')
    a, b = before.get('records'), after.get('records')
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        raise ValueError('Stage inventory changed')
    found = 0
    for old, new in zip(a, b):
        if old.get('collection') != collection or old.get('candidate_id') != candidate:
            if old != new:
                raise ValueError('Checkpoint changes another candidate stage')
            continue
        found += 1
        if not _only_changed(old, new, {'checks', 'blockers', 'status', 'review_ready'}):
            raise ValueError('Checkpoint changes unrelated stage fields')
        x, y = old.get('checks', {}), new.get('checks', {})
        if not isinstance(x, dict) or not isinstance(y, dict) or not _only_changed(x, y, {'duplicates'}):
            raise ValueError('Checkpoint changes another gate')
        if y != manifest_row.get('preflight', {}).get('checks', {}):
            raise ValueError('Stage and manifest checks differ')
        blockers = [gate for gate in GATES if not current_pass(manifest_row, gate)]
        if new.get('blockers') != blockers or new.get('status') != ('held' if blockers else 'passed_awaiting_batch_admission'):
            raise ValueError('Stage blockers or status are inconsistent')
        if new.get('review_ready') is not False:
            raise ValueError('Duplicate check cannot admit a candidate')
    if found != 1:
        raise ValueError('Stage candidate identity is ambiguous')


def verify(repo, review_commit, main_commit, bundle):
    """Return exact blob and tree metadata, with no remote update or disclosure."""
    if not isinstance(review_commit, str) or not SHA.fullmatch(review_commit) or not isinstance(main_commit, str) or not SHA.fullmatch(main_commit):
        raise ValueError('Full immutable Git heads required')
    if not isinstance(bundle, dict) or bundle.get('status') != 'prepared' or bundle.get('writes') != 0:
        raise ValueError('Prepared checkpoint bundle required')
    files, bases, new = bundle.get('files'), bundle.get('base_blobs'), bundle.get('new_paths_must_be_absent')
    if not isinstance(files, dict) or not isinstance(bases, dict) or not isinstance(new, list) or len(new) != 1:
        raise ValueError('Checkpoint path inventory is incomplete')
    receipt_path = new[0]
    if not isinstance(receipt_path, str) or not re.fullmatch(r'config/content_review_mechanical_checkpoints/[0-9a-f]{64}\.json', receipt_path):
        raise ValueError('Invalid new checkpoint receipt path')
    fixed = {'config/content_review_candidate_lifecycle.json', 'config/content_review_preflight_status.json',
             'config/content_review_worker_status.json'}
    manifests = set(bases) - fixed
    if len(manifests) != 1 or not re.fullmatch(r'config/[a-zA-Z0-9_-]+_review_manifest\.json', next(iter(manifests))):
        raise ValueError('Invalid checkpoint manifest path')
    manifest_path = next(iter(manifests))
    if set(bases) != fixed | {manifest_path} or set(files) != set(bases) | {receipt_path}:
        raise ValueError('Unexpected or omitted checkpoint path')
    original, changed, blobs = {}, {}, {}
    for path in sorted(files):
        content = files[path]
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_BLOB_BYTES:
            raise ValueError('Invalid checkpoint content size')
        changed[path] = validate(content, path)
        if not isinstance(changed[path], dict):
            raise ValueError('Checkpoint JSON object required')
        raw = content.encode('utf-8')
        blobs[path] = {'blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                       'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        if path in bases:
            old, proof = _path_blob(repo, review_commit, path)
            if proof != bases[path]:
                raise ValueError('Checkpoint base blob differs from the verified commit')
            original[path] = json.loads(old)
        elif _git(repo, 'ls-tree', '-z', review_commit, '--', path):
            raise ValueError('New checkpoint receipt already exists')
    receipt = changed[receipt_path]
    required = {'schema_version', 'kind', 'run_id', 'collection', 'candidate_id', 'content_sha256', 'checked_at',
                'status', 'source_review_commit', 'source_main_commit', 'provider_requests', 'paid_requests',
                'openalex_requests', 'publication_approved'}
    if (set(receipt) != required or receipt['schema_version'] != 1 or receipt['kind'] != 'duplicate_checkpoint' or receipt['status'] != 'passed'
        or receipt['source_review_commit'] != review_commit or receipt['source_main_commit'] != main_commit
        or receipt['provider_requests'] != 0 or receipt['paid_requests'] != 0 or receipt['openalex_requests'] != 0
        or receipt['publication_approved'] is not False or not all(isinstance(receipt[k], str) and receipt[k] for k in ('run_id', 'collection', 'candidate_id', 'content_sha256', 'checked_at'))
        or not re.fullmatch(r'[0-9a-f]{64}', receipt['content_sha256'] or '')):
        raise ValueError('Checkpoint receipt is invalid or exceeds scope')
    collection, candidate = receipt['collection'], receipt['candidate_id']
    checked_at = instant(receipt['checked_at'])
    if not checked_at:
        raise ValueError('Checkpoint receipt timestamp is invalid')
    expected_id = hashlib.sha256((receipt['run_id'] + '\0' + collection + ':' + candidate + '\0' + receipt['content_sha256']).encode()).hexdigest()
    if receipt_path != 'config/content_review_mechanical_checkpoints/' + expected_id + '.json':
        raise ValueError('Checkpoint receipt identity is inconsistent')
    row = _manifest(original[manifest_path], changed[manifest_path], candidate, receipt['content_sha256'])
    stage_path = 'config/content_review_preflight_status.json'
    _stage(original[stage_path], changed[stage_path], collection, candidate, row)
    state_path = 'config/content_review_worker_status.json'
    if not _only_changed(original[state_path], changed[state_path], {'source_attempts', 'source_last_progress'}):
        raise ValueError('Checkpoint changes unrelated worker state')
    old_state, new_state = original[state_path], changed[state_path]
    lease, run = old_state.get('lease') or {}, old_state.get('current_run') or {}
    expiry, started, observed = instant(lease.get('expires_at')), instant(run.get('started_at')), instant(run.get('observed_at'))
    if (not lease.get('owner') or lease.get('run_id') != receipt['run_id'] or run.get('run_id') != receipt['run_id']
        or run.get('application_status') != 'running' or not expiry or (expiry-checked_at).total_seconds() <= 120
        or not started or not 0 <= (checked_at-started).total_seconds() <= 600
        or not observed or not 0 <= (checked_at-observed).total_seconds() <= 40):
        raise ValueError('Checkpoint receipt lacks a fresh matching lease and run')
    old_attempts, new_attempts = old_state.get('source_attempts', {}), new_state.get('source_attempts', {})
    if (not isinstance(old_attempts, dict) or not isinstance(new_attempts, dict)
        or not _only_changed(old_attempts, new_attempts, {collection})
        or new_attempts.get(collection) != {'at': receipt['checked_at'], 'run_id': receipt['run_id'], 'gate': 'duplicates'}
        or old_state.get('source_last_progress', {}) != new_state.get('source_last_progress', {})):
        raise ValueError('Checkpoint alters unrelated attempts or source progress')
    ledger_path = 'config/content_review_candidate_lifecycle.json'
    old_ledger, new_ledger = original[ledger_path], changed[ledger_path]
    if not _only_changed(old_ledger, new_ledger, {'records', 'updated_at', 'counts', 'source_counts'}):
        raise ValueError('Checkpoint changes unrelated lifecycle metadata')
    old_records, new_records = old_ledger.get('records'), new_ledger.get('records')
    key = collection + ':' + candidate
    if not isinstance(old_records, dict) or not isinstance(new_records, dict) or key not in old_records or key not in new_records or not _only_changed(old_records, new_records, {key}):
        raise ValueError('Checkpoint changes another lifecycle candidate')
    for history in ('attempts', 'history'):
        old, new_items = old_records[key].get(history, []), new_records[key].get(history, [])
        if not isinstance(old, list) or not isinstance(new_items, list) or new_items[:len(old)] != old:
            raise ValueError('Existing lifecycle history was not retained')
    attempts = new_records[key].get('attempts', [])
    if (len(attempts) != len(old_records[key].get('attempts', [])) + 1 or attempts[-1].get('attempt_id') != expected_id
        or attempts[-1].get('evidence_ref') != receipt_path or attempts[-1].get('stage') != 'duplicates'
        or attempts[-1].get('outcome') != 'success' or new_records[key].get('content_sha256') != receipt['content_sha256']):
        raise ValueError('Lifecycle attempt is not bound to the checkpoint receipt')
    policy_raw, _ = _path_blob(repo, review_commit, 'config/content_review_lifecycle_policy.json')
    policy = json.loads(policy_raw)
    if not isinstance(policy, dict):
        raise ValueError('Committed lifecycle policy is invalid')
    recorded = record_attempt(old_records[key], attempt_id=expected_id, at=checked_at, stage='duplicates',
                              outcome='success', reason='Complete local duplicate and exclusion check passed.',
                              evidence_ref=receipt_path)
    if evaluate(row, recorded, checked_at, policy) != new_records[key]:
        raise ValueError('Checkpoint lifecycle is not derived from the committed policy')
    expected_counts = dict(Counter(x['state'] for x in new_records.values()))
    expected_sources = {c: dict(Counter(x['state'] for x in new_records.values() if x.get('collection') == c))
                        for c in sorted({x.get('collection') for x in new_records.values() if x.get('collection')})}
    if new_ledger.get('counts') != expected_counts or new_ledger.get('source_counts') != expected_sources:
        raise ValueError('Checkpoint lifecycle counts are inconsistent')
    tree = _git(repo, 'rev-parse', review_commit + '^{tree}').decode('ascii').strip()
    if not SHA.fullmatch(tree):
        raise ValueError('Commit tree is invalid')
    return {'expected_head': review_commit, 'base_tree_sha': tree, 'blobs': blobs,
            'new_path': receipt_path, 'requires_remote_head_d1_and_lease_recheck': True, 'writes': 0}
