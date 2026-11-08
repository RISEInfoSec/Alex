"""Prepare a narrow source-evidence gate proposal without remote writes.

The separate Site writer must independently verify source provenance and the
entire proposed checkpoint, then fence and recheck private review decisions.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re

from tools.content_review.coordinator import plan
from tools.content_review.manifest_integrity import reviewed_digest, validate_update
from tools.content_review.source_gate_rules import audit
from tools.content_review.verified_inputs import _path_blob

RECEIPT = re.compile(r'^config/content_review_source_receipts/[0-9a-f]{64}\.json$')


def prepare(repo, snapshot, confirmed, inputs, ledger, state, owner, run_id, collection, candidate_id, gate,
            *, observed_heads, source_attempts, source_progress, at=None, heartbeat=None):
    now = at or datetime.now(timezone.utc)
    if gate not in ('access', 'metadata') or not isinstance(inputs, dict) or not isinstance(observed_heads, dict):
        raise ValueError('Supported source gate and verified inputs required')
    if observed_heads != {'review': inputs.get('review_commit'), 'main': inputs.get('main_commit')}:
        raise ValueError('Source heads changed or are unavailable')
    if ledger != inputs.get('lifecycle') or state != inputs.get('worker_state'):
        raise ValueError('Worker state or lifecycle differs from verified inputs')
    if collection in ('apwg', 'corpus-audit'):
        raise ValueError('Collection requires its separate adapter')
    selection = plan(snapshot, confirmed, inputs['reconciliation_manifests'], ledger, inputs['registry'], state, owner, run_id,
                     source_attempts=source_attempts, source_progress=source_progress, at=now,
                     heartbeat=heartbeat, review_head=inputs['review_commit'],stages=('source','metadata'),retained_source_only=True)
    selected = [x for x in selection['selected'] if x['collection'] == collection and x['candidate_id'] == candidate_id]
    if len(selected) != 1 or selected[0]['next_stage'] not in ('source', 'metadata'):
        raise ValueError('Candidate is not selected for source evidence')
    manifest = inputs['manifests'].get(collection)
    if not isinstance(manifest, dict):
        raise ValueError('Candidate manifest unavailable')
    rows = manifest.get('records', []) + manifest.get('preflight_records', [])
    found = [x for x in rows if x.get('candidate_id') == candidate_id]
    if len(found) != 1 or found[0].get('content_sha256') != selected[0].get('content_sha256'):
        raise ValueError('Candidate identity or reviewed hash changed')
    row = found[0]
    if row.get('decision', 'pending') not in ('pending', 'unreviewed') or reviewed_digest(row) != row['content_sha256']:
        raise ValueError('Candidate decision or reviewed content changed')
    retained = row.get('source_processing')
    path = retained.get('receipt') if isinstance(retained, dict) else None
    if (not isinstance(path, str) or not RECEIPT.fullmatch(path) or retained.get('content_sha256') != row['content_sha256']
            or retained.get('retrieval_status') != 'retrieved'):
        return {'status': 'held', 'reason': 'retained_source_unavailable', 'writes': 0}
    raw, proof = _path_blob(repo, inputs['review_commit'], path)
    receipt = json.loads(raw)
    result = audit(row, collection, receipt, now=now)
    check = result.get('checks', {}).get(gate)
    if not isinstance(check, dict) or check.get('status') != 'passed':
        return {'status': 'held', 'reason': 'source_gate_evidence_insufficient', 'writes': 0}
    if check['evidence'].get('request_id') != path.rsplit('/', 1)[-1][:-5]:
        raise ValueError('Retained source receipt identity differs')
    after = deepcopy(manifest)
    changed = [x for x in after.get('records', []) + after.get('preflight_records', []) if x.get('candidate_id') == candidate_id]
    if len(changed) != 1:
        raise ValueError('Candidate identity changed during preparation')
    preflight = changed[0].setdefault('preflight', {})
    checks = preflight.setdefault('checks', {}) if isinstance(preflight, dict) else None
    if not isinstance(checks, dict):
        raise ValueError('Candidate checks unavailable')
    old = deepcopy(checks.get(gate))
    checks[gate] = {'status': 'passed', 'content_sha256': row['content_sha256'], 'checked_at': now.isoformat(),
                    'evidence': {**check['evidence'], 'source_receipt': path, 'source_receipt_blob': proof['blob_sha']}}
    if old is not None:
        checks[gate]['prior_evidence'] = old
    validate_update(json.dumps(manifest), json.dumps(after))
    return {'status': 'prepared', 'manifest': after, 'gate': gate, 'collection': collection,
            'candidate_id': candidate_id, 'content_sha256': row['content_sha256'], 'checked_at': now.isoformat(),
            'writes': 0, 'provider_requests': 0, 'publication_authorized': False,
            'requires_atomic_semantic_validation_and_live_d1_fence': True}
