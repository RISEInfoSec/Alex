"""Prepare independent monitor evidence for a separate Git ref, without writes.

The caller independently authenticates native scheduler observations and both
Git refs, applies the proposal with expected-head CAS, and reads it back. This
observer never takes the worker lease, processes a candidate or authorizes release.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from tools.content_review.monitor_snapshot import prepare as snapshot
from tools.content_review.operations import find_automation
from tools.content_review.verified_inputs import SHA, _git, _path_blob

PATH = 'config/content_review_independent_monitor.json'
CONFIG = 'config/content_review_monitor_config.json'
WORKER = 'config/content_review_worker_status.json'


def prepare(repo, review_head, monitor_head, worker_native, observer_native, *, observed_heads, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware monitor time is required')
    if not all(isinstance(x, str) and SHA.fullmatch(x) for x in (review_head, monitor_head)):
        raise ValueError('Immutable review and monitor heads are required')
    if not isinstance(observed_heads, dict) or observed_heads.get('review') != review_head or observed_heads.get('monitor') != monitor_head:
        raise ValueError('Current review and monitor heads are required')
    config_raw, config_meta = _path_blob(repo, review_head, CONFIG)
    worker_raw, worker_meta = _path_blob(repo, review_head, WORKER)
    config, worker = json.loads(config_raw), json.loads(worker_raw)
    if not isinstance(config, dict) or not isinstance(worker, dict):
        raise ValueError('Committed monitor configuration or worker state is invalid')
    target = config.get('target_automation_id')
    observed_worker = find_automation(worker_native, target) if isinstance(target, str) else None
    run = ((observed_worker or {}).get('run_details') or {}).get('last_run') or {}
    run_id = run.get('id')
    receipt, receipt_meta = None, None
    if isinstance(run_id, str) and re.fullmatch(r'[a-zA-Z0-9-]+', run_id):
        receipt_path = 'config/content_review_run_receipts/' + run_id + '.json'
        if _git(repo, 'ls-tree', '-z', review_head, '--', receipt_path):
            receipt_raw, receipt_meta = _path_blob(repo, review_head, receipt_path)
            receipt = json.loads(receipt_raw)
            if not isinstance(receipt, dict):raise ValueError('Committed worker receipt is invalid')
    record = snapshot(config, worker_native, observer_native, worker, receipt, at=now)
    old, base = None, None
    if _git(repo, 'ls-tree', '-z', monitor_head, '--', PATH):
        old, base = _path_blob(repo, monitor_head, PATH)
        if not isinstance(json.loads(old), dict):raise ValueError('Previous monitor snapshot is invalid')
    record['source_review_commit'] = review_head
    record['source_config_blob_sha'] = config_meta['blob_sha']
    record['source_worker_blob_sha'] = worker_meta['blob_sha']
    record['source_receipt_blob_sha'] = receipt_meta['blob_sha'] if receipt_meta else None
    record['previous_monitor_blob_sha'] = base['blob_sha'] if base else None
    content = json.dumps(record, ensure_ascii=False, indent=2)+'\n'
    raw = content.encode('utf-8')
    if not raw or len(raw) > 32768:raise ValueError('Monitor snapshot exceeds the bounded size')
    tree = _git(repo, 'rev-parse', monitor_head+'^{tree}').decode('ascii').strip()
    if not SHA.fullmatch(tree):raise ValueError('Monitor base tree is invalid')
    return {'path':PATH, 'review_head':review_head, 'monitor_head':monitor_head, 'base_tree_sha':tree,
            'base_blob':base, 'content':content, 'blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
            'size':len(raw), 'observer_id':record['observer']['automation_id'], 'run_id':record['observer']['run_id'],
            'writes':0, 'requires_expected_head_and_readback':True}
