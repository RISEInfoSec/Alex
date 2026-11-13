"""Prepare one verified source-evidence retention without writing or passing gates.

Private D1 rows are used only in memory. The caller must independently recheck
the heads, lease and D1 state immediately before any atomic leased write.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.heartbeat_evidence import verify as verify_heartbeat
from tools.content_review.lifecycle import instant
from tools.content_review.manifest_integrity import reviewed_digest, validate_update
from tools.content_review.source_handoff import retain, verify
from tools.content_review.source_result_guard import _verify_request_commit
from tools.content_review.source_worker import MANIFESTS, digest
from tools.content_review.verified_inputs import SHA, _path_blob, load_inputs


def prepare(repo, review_head, main_head, heartbeat_head, snapshot, confirmed, request_id,
            result_bytes, native_run, artifact, collection, candidate_id, owner, run_id,
            *, observed_heads, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware source retention time is required')
    if not all(isinstance(x, str) and SHA.fullmatch(x) for x in (review_head, main_head, heartbeat_head)):
        raise ValueError('Immutable review, main and heartbeat heads are required')
    if not isinstance(observed_heads, dict) or observed_heads.get('review') != review_head or observed_heads.get('main') != main_head:
        raise ValueError('Current source heads are unavailable or changed')
    if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', request_id):
        raise ValueError('Invalid source request identity')
    if collection not in MANIFESTS or not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError('Candidate requires a supported source adapter')
    if not isinstance(result_bytes, bytes) or len(result_bytes) > 32 * 1024 * 1024:
        raise ValueError('Complete bounded source artifact is required')
    if (not isinstance(native_run, dict) or not isinstance(artifact, dict)
        or type(artifact.get('id')) is not int or artifact['id'] < 1
        or artifact.get('run_id') != native_run.get('id')
        or artifact.get('sha256') != hashlib.sha256(result_bytes).hexdigest()):
        raise ValueError('Source artifact identity or bytes differ')
    try:
        result = json.loads(result_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Invalid source artifact JSON') from exc
    if not isinstance(result, dict) or result.get('schema_version') != 1 or result.get('status') != 'complete' or result.get('read_only') is not True:
        raise ValueError('Complete read-only source artifact is required')

    inputs = load_inputs(repo, review_head, main_head)
    state = inputs['worker_state']
    beat_raw, _ = _path_blob(repo, heartbeat_head, 'config/content_review_detached_heartbeat.json')
    verify_heartbeat(json.loads(beat_raw), state, review_head, owner, run_id, at=now)
    started = instant((state.get('current_run') or {}).get('started_at'))
    expiry = instant((state.get('lease') or {}).get('expires_at'))
    policy = (inputs.get('workflow') or {}).get('bounded_processing_pilot') or {}
    total, reserve = policy.get('total_runtime_seconds'), policy.get('checkpoint_reserve_seconds')
    if (type(total) is not int or type(reserve) is not int or total > 720 or reserve < 120
        or total <= reserve or not started or not expiry or (now-started).total_seconds() < 0
        or (now-started).total_seconds() + 20 >= total-reserve or (expiry-now).total_seconds() <= reserve+20):
        raise ValueError('Source retention has no bounded work window and checkpoint reserve')
    request_path = 'config/content_review_source_requests/' + request_id + '.json'
    receipt_path = 'config/content_review_source_receipts/' + request_id + '.json'
    request_raw, _ = _path_blob(repo, review_head, request_path)
    receipt_raw, _ = _path_blob(repo, review_head, receipt_path)
    request, receipt = json.loads(request_raw), json.loads(receipt_raw)
    if (not isinstance(request, dict) or request.get('request_id') != request_id
        or digest({k: v for k, v in request.items() if k != 'request_id'}) != request_id):
        raise ValueError('Committed source request identity differs')
    _verify_request_commit(repo, review_head, request_path, request_raw, request, native_run)
    verify(request, result, native_run)
    expected_receipt = {'schema_version': 1, 'independently_verified': True, 'request': request,
                        'native_run': {k: native_run.get(k) for k in ('id', 'event', 'head_branch', 'path', 'status', 'conclusion', 'head_sha', 'run_attempt')},
                        'artifact_id': artifact['id'], 'artifact_sha256': artifact['sha256'], 'result': result}
    if receipt != expected_receipt:
        raise ValueError('Committed source receipt differs from independently read evidence')
    runs = [state.get('current_run')] + (state.get('run_history') if isinstance(state.get('run_history'), list) else [])
    entries = [entry for run in runs if isinstance(run, dict)
               for entry in run.get('accounted_source_requests', []) if isinstance(entry, dict) and entry.get('request_id') == request_id]
    if (len(entries) != 1 or entries[0].get('artifact_id') != artifact['id']
        or entries[0].get('artifact_sha256') != artifact['sha256'] or entries[0].get('native_run_id') != native_run['id']
        or entries[0].get('requests') != result.get('requests')):
        raise ValueError('Source receipt has no unique durable accounting entry')
    items = [item for item in result.get('records', [])
             if item.get('collection') == collection and item.get('candidate_id') == candidate_id]
    if len(items) != 1:
        raise ValueError('Source artifact candidate is missing or ambiguous')
    item = items[0]
    if (item.get('status') not in ('retrieved', 'held') or not isinstance(item.get('next_action'), str)
        or not item['next_action'] or not isinstance(item.get('evidence'), list)
        or (item['status'] == 'retrieved' and not item['evidence'])):
        raise ValueError('Source candidate result is incomplete')

    checked = reconcile(snapshot, confirmed, {k: v.get('records', []) for k, v in inputs['reconciliation_manifests'].items()})
    for decision in checked['matched_decisions'] + checked['held']:
        if decision.get('collection') == collection and decision.get('candidate_id') == candidate_id:
            raise ValueError('Current private review decision or reconciliation hold prevents retention')
    manifest = inputs['manifests'].get(collection)
    if not isinstance(manifest, dict):
        raise ValueError('Committed candidate manifest is unavailable')
    rows = manifest.get('records', []) + manifest.get('preflight_records', [])
    found = [row for row in rows if row.get('candidate_id') == candidate_id]
    if len(found) != 1:
        raise ValueError('Committed candidate is missing or ambiguous')
    row = found[0]
    if (row.get('decision', 'pending') not in ('pending', 'unreviewed')
        or row.get('content_sha256') != item.get('content_sha256') or reviewed_digest(row) != row.get('content_sha256')):
        raise ValueError('Candidate decision or reviewed content has changed')
    if (row.get('source_processing') or {}).get('receipt') == receipt_path:
        raise ValueError('Source evidence was already retained; reconcile before retrying')
    updated = retain(manifest, [item], receipt_path)
    before = json.dumps(manifest, ensure_ascii=False)
    content = json.dumps(updated, ensure_ascii=False, indent=2) + '\n'
    validate_update(before, content)
    raw = content.encode('utf-8')
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Source retention manifest exceeds bounded size')
    path = MANIFESTS[collection]
    current_raw, base = _path_blob(repo, review_head, path)
    if json.loads(current_raw) != manifest:
        raise ValueError('Registered manifest does not match the writable source path')
    return {'status': 'prepared', 'writes': 0, 'path': path, 'content': content, 'base_blob': base,
            'blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
            'd1_fingerprint_private': checked['snapshot_sha256'], 'review_head': review_head, 'main_head': main_head,
            'heartbeat_head': heartbeat_head, 'checked_at': now.isoformat(), 'requires_remote_d1_head_and_lease_recheck': True,
            'gate_passed': False, 'publication_authorized': False}
