"""Prepare a bounded run receipt and lease release from committed evidence.

This module performs no network calls or writes. Its caller must obtain a real
native observation, atomically commit both files using the expected head, and
recheck D1, heads, native state and the lease immediately before that update.
Private review rows and their fingerprint never enter either public file.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.duplicate_evidence import audit
from tools.content_review.heartbeat_evidence import verify as verify_heartbeat
from tools.content_review.lease import release
from tools.content_review.lease_transition import RETIRED_TARGETS
from tools.content_review.lifecycle import current_pass, instant
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.operations import find_automation, hourly_anchor
from tools.content_review.verified_inputs import SHA, _git, _path_blob, load_inputs

WORKER = 'config/content_review_worker_status.json'
CONFIG = 'config/content_review_monitor_config.json'
RECEIPT = 'config/content_review_run_receipts/'
CHECKPOINT = re.compile(r'^config/content_review_mechanical_checkpoints/([0-9a-f]{64})\.json$')


def _json(repo, head, path):
    raw, metadata = _path_blob(repo, head, path)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Committed run evidence is invalid JSON') from exc
    if not isinstance(value, dict):
        raise ValueError('Committed run evidence must be an object')
    return value, metadata


def prepare(repo, review_head, main_head, heartbeat_head, native, snapshot, confirmed_snapshot,
            owner, run_id, checkpoint_paths, *, at=None):
    """Prepare two atomic files, never a native-success or publication claim."""
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware completion time is required')
    if not all(isinstance(s, str) and SHA.fullmatch(s) for s in (review_head, main_head, heartbeat_head)):
        raise ValueError('Immutable review, main and heartbeat heads are required')
    if not isinstance(owner, str) or not owner or not isinstance(run_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]+', run_id):
        raise ValueError('Valid lease owner and run ID are required')
    if (not isinstance(checkpoint_paths, list) or len(checkpoint_paths) > 5
        or any(not isinstance(p, str) or not CHECKPOINT.fullmatch(p) for p in checkpoint_paths)
        or len(set(checkpoint_paths)) != len(checkpoint_paths)):
        raise ValueError('At most five distinct mechanical checkpoints are allowed')
    state, state_meta = _json(repo, review_head, WORKER)
    config, _ = _json(repo, review_head, CONFIG)
    target = config.get('target_automation_id')
    observed = find_automation(native, target) if isinstance(target, str) and target not in RETIRED_TARGETS else None
    last = ((observed or {}).get('run_details') or {}).get('last_run') or {}
    latest = ((observed or {}).get('run_details') or {}).get('latest_result') or {}
    run = state.get('current_run') or {}
    started, due = instant(run.get('started_at')), instant(run.get('scheduled_for'))
    anchor = hourly_anchor((observed or {}).get('schedule', ''))
    manual=(run.get('scheduler') or {}).get('kind')=='manual'
    permit=config.get('manual_run_authorization') if manual else None
    until=instant(permit.get('expires_at')) if isinstance(permit,dict) else None
    if manual:
        if (native is not None or not isinstance(permit,dict) or set(permit)!={'run_id','owner','expires_at','scope'} or
            permit.get('run_id')!=run_id or permit.get('owner')!=owner or permit.get('scope')!='duplicate_only' or
            (run.get('scheduler') or {}).get('id')!=target or (run.get('scheduler') or {}).get('authorization')!='owner_request' or
            run.get('scheduled_for') is not None or not started or not until or started>now or until<=now or
            (until-started).total_seconds()>900 or (now-started).total_seconds()>600):
            raise ValueError('Exact manual authorization and work window required')
    elif (not observed or observed.get('is_enabled') is not True or (run.get('scheduler') or {}).get('id') != target or last.get('id') != run_id
        or last.get('recorded_status') != 'in_progress' or instant(last.get('started_at')) != started
        or instant(last.get('scheduled_for')) != due or not started or not due or not anchor
        or due < anchor or (due-anchor).total_seconds() % 3600 != 0 or started > now
        or (now-started).total_seconds() > 720
        or (latest.get('run_id') == run_id and (latest.get('requires_user_action') is True or latest.get('is_failure_message') is True))):
        raise ValueError('Matching in-progress native run is unavailable')
    heartbeat, _ = _json(repo, heartbeat_head, 'config/content_review_detached_heartbeat.json')
    verify_heartbeat(heartbeat, state, review_head, owner, run_id, at=now)
    counts = run.get('request_counts')
    if not isinstance(counts, dict) or any(type(counts.get(k)) is not int or counts[k] != 0 for k in ('source', 'paid', 'openalex')):
        raise ValueError('Only zero-provider mechanical runs are currently supported')
    pending=run.get('pending_source_request')
    if pending is not None:
        # The pending reservation is carried forward unchanged; an empty run
        # must use the source-pending adapter instead of claiming completion.
        origin=pending.get('origin_run_id') if isinstance(pending,dict) else None
        history=state.get('run_history')
        matches=[x for x in history if isinstance(x,dict) and x.get('run_id')==origin] if isinstance(history,list) else []
        if (not checkpoint_paths or not isinstance(pending,dict) or
            not re.fullmatch(r'[0-9a-f]{64}',pending.get('request_id') or '') or
            not isinstance(origin,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',origin) or
            type(pending.get('reserved_limit')) is not int or not 1<=pending['reserved_limit']<=30 or
            not instant(pending.get('prepared_at')) or len(matches)!=1 or
            matches[0].get('pending_source_request')!=pending):
            raise ValueError('Pending source reservation cannot be preserved')
    inputs = load_inputs(repo, review_head, main_head)
    manifests = inputs['reconciliation_manifests']
    checked = reconcile(snapshot, confirmed_snapshot, {k: v.get('records', []) for k, v in manifests.items()})
    # Historical decisions remain authoritative even after a later submission
    # supersedes them; the independent Site writer applies the same hold.
    decision_keys = {(x['collection'], x['candidate_id']) for x in snapshot['decisions']}
    held_keys = {(x['collection'], x['candidate_id']) for x in checked['held']}
    actions = []
    for path in checkpoint_paths:
        record, _ = _json(repo, review_head, path)
        collection, candidate, digest = record.get('collection'), record.get('candidate_id'), record.get('content_sha256')
        if (record.get('schema_version') != 1 or record.get('kind') != 'duplicate_checkpoint'
            or record.get('run_id') != run_id or record.get('status') != 'passed'
            or not isinstance(collection, str) or not isinstance(candidate, str)
            or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or record.get('source_main_commit') != main_head or record.get('publication_approved') is not False
            or any(record.get(k) != 0 for k in ('provider_requests', 'paid_requests', 'openalex_requests'))):
            raise ValueError('Mechanical checkpoint is invalid or exceeds scope')
        expected = hashlib.sha256((run_id+'\0'+collection+':'+candidate+'\0'+digest).encode()).hexdigest()
        if path != 'config/content_review_mechanical_checkpoints/'+expected+'.json':
            raise ValueError('Mechanical checkpoint identity differs')
        source = record.get('source_review_commit')
        if not isinstance(source, str) or not SHA.fullmatch(source):
            raise ValueError('Mechanical checkpoint source is unavailable')
        try:
            _git(repo, 'merge-base', '--is-ancestor', source, review_head)
        except ValueError as exc:
            raise ValueError('Mechanical checkpoint source is outside review history') from exc
        if (collection, candidate) in decision_keys or (collection, candidate) in held_keys:
            raise ValueError('A reviewed or held candidate requires reconciliation')
        created=instant(record.get('checked_at'))
        if not created or not started <= created <= now:
            raise ValueError('Mechanical checkpoint time is outside this run')
        additions = _git(repo, 'log', '--format=%H', '--diff-filter=A', review_head, '--', path).decode().splitlines()
        if len(additions) != 1:
            raise ValueError('Mechanical checkpoint creation is ambiguous')
        commit = additions[0]
        parents = _git(repo, 'rev-list', '--parents', '-n', '1', commit).decode().split()
        created_record, _ = _json(repo, commit, path)
        if parents != [commit, source] or created_record != record:
            raise ValueError('Mechanical checkpoint is not bound to its source commit')
        manifest = inputs['manifests'].get(collection) or {}
        rows = manifest.get('records', []) + manifest.get('preflight_records', [])
        matches = [row for row in rows if row.get('candidate_id') == candidate]
        if len(matches) != 1:
            raise ValueError('Current candidate identity is unavailable or ambiguous')
        row = matches[0]
        gate = row.get('preflight', {}).get('checks', {}).get('duplicates', {})
        evidence = gate.get('evidence') or {}
        if (row.get('decision', 'pending') not in ('pending', 'unreviewed')
            or row.get('content_sha256') != digest or reviewed_digest(row) != digest
            or not current_pass(row, 'duplicates') or gate.get('checked_at') != record.get('checked_at')
            or evidence.get('review_commit') != source or evidence.get('main_commit') != main_head):
            raise ValueError('Current candidate no longer matches the completed checkpoint')
        original = load_inputs(repo, source, main_head)
        source_manifest = original['manifests'].get(collection) or {}
        originals = [x for x in source_manifest.get('records', [])+source_manifest.get('preflight_records', [])
                     if x.get('candidate_id') == candidate]
        if len(originals) != 1 or reviewed_digest(originals[0]) != digest:
            raise ValueError('Checkpoint source candidate differs')
        collections = {'public': original['public']}
        for name, item in original['manifests'].items():
            collections[name] = item.get('records', [])+item.get('preflight_records', [])
        actual = audit(originals[0], collections, original['original_queue']+original['current_queue'],
                       original['exclusion_keys'], source_collection=collection)
        expected_evidence = {'method':'complete immutable corpus, exclusions, registered collections and upstream inventories',
                             'review_commit':source, 'main_commit':main_head, 'input_blobs':original['metadata'],
                             'matches':actual['matches'], 'exclusions':actual['exclusions'],
                             'upstream_aliases':actual['upstream_aliases']}
        if actual['status'] != 'passed' or evidence != expected_evidence:
            raise ValueError('Completed duplicate evidence differs from committed inputs')
        actions.append({'path': path, 'collection': collection, 'candidate_id': candidate,
                        'content_sha256': digest, 'gate': 'duplicates'})
    if len({a['candidate_id'] for a in actions}) != len(actions):
        raise ValueError('Candidate identities are ambiguous across checkpoints')
    receipt_path = RECEIPT + run_id + '.json'
    if _git(repo, 'ls-tree', '-z', review_head, '--', receipt_path):
        raise ValueError('Run receipt already exists')
    updated = release(state, owner, run_id, at=now)
    completed = bool(actions)
    updated['current_run']['application_status'] = 'complete' if completed else 'deferred'
    updated['current_run']['application_completed_at'] = now.isoformat()
    updated['current_run']['receipt'] = receipt_path
    receipt = {'schema_version': 1, 'run_id': run_id, 'trigger': 'manual' if manual else 'schedule',
               'scheduled_for': None if manual else due.isoformat(), 'started_at': started.isoformat(), 'completed_at': now.isoformat(),
               'status': 'complete' if completed else 'no_work', 'completed_actions': actions,
               'receipt_path': receipt_path, 'provider_requests': 0, 'paid_requests': 0, 'openalex_requests': 0,
               'publication_approved': False, 'native_completion_verified': False,
               'scope_note':'Mechanical duplicate checks only; review readiness and publication are not established.',
               'pilot':{'attempted_candidate_ids':[a['candidate_id'] for a in actions],
                        'newly_passed_checks':{'duplicates':[a['candidate_id'] for a in actions]},
                        'requests':{'source':0,'paid':0,'openalex':0}, 'manual_admitted':[],
                        'all_six_completed':[], 'actual_publications':[], 'integrity_passed':None,
                        'checkpoint_failures':None, 'resolvable_gate_count':None,
                        'all_candidates_legitimately_held':None,
                        'remaining_blockers':['Subsequent gates and source work were not executed in this mechanical pass.']}}
    files = {WORKER: json.dumps(updated, ensure_ascii=False, indent=2)+'\n',
             receipt_path: json.dumps(receipt, ensure_ascii=False, indent=2)+'\n'}
    blobs = {}
    for path, text in files.items():
        raw = text.encode('utf-8')
        blobs[path] = {'blob_sha': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                       'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    tree = _git(repo, 'rev-parse', review_head+'^{tree}').decode('ascii').strip()
    from tools.content_review.proposed_tree import bind_guarded
    expected_tree = bind_guarded(repo, review_head, files, {WORKER:state_meta}, receipt_path, blobs)
    return {'status':'prepared', 'kind':'run_completion', 'files':files, 'blobs':blobs,
            'base_blobs':{WORKER:state_meta}, 'new_path':receipt_path, 'expected_head':review_head,
            'expected_main':main_head, 'base_tree_sha':tree, 'expected_tree':expected_tree, 'heartbeat_head':heartbeat_head,
            'd1_fingerprint_private':checked['snapshot_sha256'], 'lease_owner':owner, 'run_id':run_id, 'fence_state':state,
            'requires_remote_head_d1_and_lease_recheck':True, 'native_completion_verified':False, 'writes':0}
