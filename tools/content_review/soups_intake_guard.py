"""Recompute a SOUPS intake proposal from committed objects and private D1.

This produces an exact-tree proof, not a write. It is not a substitute for
server-side semantic validation or the live lease and D1 decision fence.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import _fingerprint
from tools.content_review.lifecycle import instant
from tools.content_review.proposed_tree import bind_guarded
from tools.content_review.soups_intake import PATH, STAGE_PATH, prepare as plan_intake
from tools.content_review.verified_inputs import SHA, _git, _path_blob, load_inputs

LEDGER = 'config/content_review_candidate_lifecycle.json'
HEARTBEAT = 'config/content_review_detached_heartbeat.json'


def prepare(repo, review_head, main_head, heartbeat_head, snapshot, confirmed, owner, run_id, proposal, *, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware intake guard time required')
    if not all(isinstance(x, str) and SHA.fullmatch(x) for x in (review_head, main_head, heartbeat_head)):
        raise ValueError('Immutable source and heartbeat heads required')
    if not isinstance(proposal, dict) or proposal.get('status') != 'prepared' or proposal.get('writes') != 0:
        raise ValueError('Prepared intake proposal required')
    prepared = instant((proposal.get('proposed_ledger') or {}).get('updated_at'))
    if not prepared or prepared > now or (now - prepared).total_seconds() > 40:
        raise ValueError('Intake proposal is stale or unavailable')
    inputs = load_inputs(repo, review_head, main_head)
    state, ledger = inputs['worker_state'], inputs['lifecycle']
    heartbeat_raw, _ = _path_blob(repo, heartbeat_head, HEARTBEAT)
    heartbeat = json.loads(heartbeat_raw)
    expected = plan_intake(snapshot, confirmed, inputs, ledger, state, owner, run_id,
        observed_heads={'review': review_head, 'main': main_head},
        source_attempts=state.get('source_attempts', {}), source_progress=state.get('source_last_progress', {}),
        heartbeat=heartbeat, at=prepared)
    if proposal != expected:
        raise ValueError('Intake proposal differs from independently recomputed inputs')
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]+', run_id):
        raise ValueError('Valid intake run identity required')
    receipt_id = hashlib.sha256((run_id + '\0' + review_head + '\0' + '\0'.join(expected['selected'])).encode()).hexdigest()
    receipt_path = 'config/content_review_intake_receipts/' + receipt_id + '.json'
    if _git(repo, 'ls-tree', '-z', review_head, '--', receipt_path):
        raise ValueError('Intake receipt already exists; reconcile before retry')
    receipt = {'schema_version': 1, 'kind': 'soups_intake', 'run_id': run_id, 'prepared_at': prepared.isoformat(),
               'source_review_commit': review_head, 'source_main_commit': main_head, 'selected': expected['selected'],
               'provider_requests': 0, 'paid_requests': 0, 'openalex_requests': 0, 'publication_approved': False,
               'candidate_processing': False}
    values = {PATH: expected['proposed_manifest'], LEDGER: expected['proposed_ledger'],
              STAGE_PATH: expected['proposed_stage'], receipt_path: receipt}
    files = {path: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n' for path, value in values.items()}
    bases = {}
    for path in (PATH, LEDGER, STAGE_PATH):
        _, bases[path] = _path_blob(repo, review_head, path)
    blobs = {}
    for path, content in files.items():
        raw = content.encode('utf8')
        if not 0 < len(raw) <= 32 * 1024 * 1024: raise ValueError('Intake checkpoint size invalid')
        blobs[path] = {'blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                       'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    tree = _git(repo, 'rev-parse', review_head + '^{tree}').decode('ascii').strip()
    expected_tree = bind_guarded(repo, review_head, files, bases, receipt_path, blobs)
    fingerprint = _fingerprint(snapshot)
    bundle = {'status': 'prepared', 'writes': 0, 'files': files, 'd1_fingerprint_private': fingerprint}
    proof = {'kind': 'soups_intake', 'expected_head': review_head, 'expected_main': main_head,
             'base_tree_sha': tree, 'expected_tree': expected_tree, 'blobs': blobs, 'base_blobs': bases,
             'new_path': receipt_path, 'heartbeat_head': heartbeat_head, 'd1_fingerprint_private': fingerprint,
             'lease_owner': owner, 'run_id': run_id, 'requires_remote_head_d1_and_lease_recheck': True, 'writes': 0}
    return {'bundle': bundle, 'proof': proof, 'writes': 0, 'requires_atomic_update_and_readback': True,
            'requires_independent_site_semantic_validation': True}
