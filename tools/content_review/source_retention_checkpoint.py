"""Prepare a recomputed, receipt-bound atomic source-retention checkpoint.

This never performs a remote write. The live connector must recheck D1, both
source heads, native run and the shared lease, then CAS and read back every blob.
"""
from datetime import datetime, timezone
import hashlib
import json

from tools.content_review.lifecycle import instant
from tools.content_review.source_retention import prepare as prepare_retention
from tools.content_review.verified_inputs import SHA, _git, _path_blob

WORKER = 'config/content_review_worker_status.json'


def prepare(repo, review_head, main_head, heartbeat_head, snapshot, confirmed, request_id,
            result_bytes, native_run, artifact, collection, candidate_id, owner, run_id,
            proposal, *, observed_heads, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware checkpoint time is required')
    if not isinstance(proposal, dict) or proposal.get('status') != 'prepared' or proposal.get('writes') != 0:
        raise ValueError('Prepared source retention is required')
    checked_at = instant(proposal.get('checked_at'))
    if not checked_at or checked_at > now or (now-checked_at).total_seconds() > 40:
        raise ValueError('Source retention proposal is stale')
    expected = prepare_retention(repo, review_head, main_head, heartbeat_head, snapshot, confirmed,
                                 request_id, result_bytes, native_run, artifact, collection, candidate_id,
                                 owner, run_id, observed_heads=observed_heads, at=checked_at)
    if proposal != expected:
        raise ValueError('Source retention differs from the independently verified proposal')
    # Check freshness again at checkpoint preparation time, including work
    # reserve and the heartbeat, rather than trusting the earlier timestamp.
    prepare_retention(repo, review_head, main_head, heartbeat_head, snapshot, confirmed,
                      request_id, result_bytes, native_run, artifact, collection, candidate_id,
                      owner, run_id, observed_heads=observed_heads, at=now)
    result = json.loads(result_bytes)
    item = next(x for x in result['records'] if x['collection'] == collection and x['candidate_id'] == candidate_id)
    identity = hashlib.sha256((request_id+'\0'+collection+'\0'+candidate_id+'\0'+item['content_sha256']).encode()).hexdigest()
    receipt_path = 'config/content_review_source_checkpoints/' + identity + '.json'
    if _git(repo, 'ls-tree', '-z', review_head, '--', receipt_path):
        raise ValueError('Source retention checkpoint already exists; reconcile before retrying')
    receipt = {'schema_version': 1, 'kind': 'source_retention', 'request_id': request_id,
               'collection': collection, 'candidate_id': candidate_id, 'content_sha256': item['content_sha256'],
               'result_status': item['status'], 'artifact_sha256': artifact['sha256'], 'run_id': run_id,
               'checked_at': now.isoformat(), 'source_review_commit': review_head, 'source_main_commit': main_head,
               'provider_requests': 0, 'openalex_requests': 0, 'paid_requests': 0, 'publication_approved': False}
    worker_raw, worker_base = _path_blob(repo, review_head, WORKER)
    try:
        worker_content = worker_raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('Committed worker state is invalid') from exc
    files = {WORKER: worker_content, proposal['path']: proposal['content'],
             receipt_path: json.dumps(receipt, ensure_ascii=False, indent=2)+'\n'}
    bases = {WORKER: worker_base, proposal['path']: proposal['base_blob']}
    blobs = {}
    for path, content in files.items():
        raw = content.encode('utf-8')
        if not raw or len(raw) > 32*1024*1024:
            raise ValueError('Source checkpoint file exceeds bounded size')
        blobs[path] = {'blob_sha': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                       'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    tree = _git(repo, 'rev-parse', review_head+'^{tree}').decode('ascii').strip()
    if not SHA.fullmatch(tree):
        raise ValueError('Committed review tree is invalid')
    private = proposal['d1_fingerprint_private']
    bundle = {'status': 'prepared', 'writes': 0, 'files': files, 'd1_fingerprint_private': private}
    from tools.content_review.proposed_tree import bind_guarded
    expected_tree = bind_guarded(repo, review_head, files, bases, receipt_path, blobs)
    proof = {'kind': 'source_retention', 'expected_head': review_head, 'expected_main': main_head,
             'base_tree_sha': tree, 'expected_tree': expected_tree, 'blobs': blobs, 'base_blobs': bases, 'new_path': receipt_path,
             'heartbeat_head': heartbeat_head, 'd1_fingerprint_private': private, 'lease_owner': owner,
             'run_id': run_id, 'requires_remote_head_d1_and_lease_recheck': True, 'writes': 0}
    return {'status': 'prepared', 'bundle': bundle, 'proof': proof,
            'writes': 0, 'requires_atomic_update_and_readback': True}
