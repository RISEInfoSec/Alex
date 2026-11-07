"""Prepare a native-run-bound shared lease or heartbeat; never write remotely."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from tools.content_review.checkpoint import heartbeat
from tools.content_review.lease import acquire, release
from tools.content_review.lifecycle import instant
from tools.content_review.operations import find_automation, hourly_anchor
from tools.content_review.run_state import begin
from tools.content_review.verified_inputs import SHA, _git, _path_blob

WORKER = 'config/content_review_worker_status.json'
CONFIG = 'config/content_review_monitor_config.json'
RETIRED_TARGETS = frozenset({'Automation_0ff7fb9b800481919b48ddb2593b8f88',
                             'Automation_4eb2dd829aa88191b542d57f7008ebe3',
                             'Automation_88611f57231c81918d7ee01f7cd59c42',
                             'Automation_5bfb7f72636c819198bdbf0367081338'})


def prepare(repo, head, native, owner, run_id, phase, *, at=None, failure_code=None):
    """Build one state blob for an expected-head GitHub update and readback.

    The caller must authenticate the native observation, perform the update
    atomically, and independently reread the winning lease before doing work.
    """
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware native observation is required')
    if not isinstance(head, str) or not SHA.fullmatch(head) or not isinstance(owner, str) or not owner:
        raise ValueError('Immutable review head and lease owner are required')
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]+', run_id):
        raise ValueError('Invalid native run identity')
    if phase not in ('start', 'heartbeat', 'abort'):
        raise ValueError('Unknown lease transition')
    raw, state_meta = _path_blob(repo, head, WORKER)
    config_raw, _ = _path_blob(repo, head, CONFIG)
    state, config = json.loads(raw), json.loads(config_raw)
    if not isinstance(state, dict) or not isinstance(config, dict):
        raise ValueError('Committed worker state or configuration is invalid')
    target = config.get('target_automation_id')
    if (not isinstance(target, str) or not re.fullmatch(r'Automation_[a-zA-Z0-9]+', target)
        or (target in RETIRED_TARGETS and phase != 'abort')):
        raise ValueError('Current target automation is unavailable')
    # A failure may make native access unavailable. Release only the exact
    # current owner's unexpired lease, retaining a dated application failure.
    if phase == 'abort':
        if failure_code not in ('access_unavailable','checkpoint_failure','deadline','reconciliation_hold','heartbeat_stale'):
            raise ValueError('A bounded failure code is required for abort')
        current = state.get('current_run') or {}
        if current.get('run_id') != run_id or current.get('application_status') != 'running':
            raise ValueError('Matching running application state is required')
        updated = release(state, owner, run_id, at=now)
        updated['current_run']['application_status'] = 'failed'
        updated['current_run']['application_completed_at'] = now.isoformat()
        updated['current_run']['failure_code'] = failure_code
        updated['last_error'] = failure_code
        return _proposal(repo, head, state_meta, updated, phase)
    observed = find_automation(native, target)
    if not observed or observed.get('is_enabled') is not True:
        raise ValueError('Enabled native target observation is required')
    run = (observed.get('run_details') or {}).get('last_run') or {}
    if run.get('id') != run_id or run.get('recorded_status') != 'in_progress':
        raise ValueError('Matching in-progress native run is required')
    started, due, anchor = instant(run.get('started_at')), instant(run.get('scheduled_for')), hourly_anchor(observed.get('schedule', ''))
    if (not started or not due or not anchor or due < anchor or (due-anchor).total_seconds() % 3600 != 0
        or started < due - timedelta(minutes=5)
        or started > now or due > now + timedelta(minutes=5)
        or not 0 <= (now-started).total_seconds() < 600):
        raise ValueError('Native run timing or work window is invalid')
    latest = (observed.get('run_details') or {}).get('latest_result') or {}
    if latest.get('run_id') == run_id and latest.get('requires_user_action') is True:
        raise ValueError('Native run requires user action')
    native_snapshot = {'id': target, 'observed_at': now.isoformat(), 'is_enabled': True,
                       'schedule': observed.get('schedule'),
                       'last_run': {k: run.get(k) for k in ('id','recorded_status','scheduled_for','started_at','completed_at')}}
    if phase == 'start':
        previous_run=state.get('current_run') or {}
        pending=previous_run.get('pending_source_request')
        if pending is not None:
            if (not isinstance(pending,dict) or not isinstance(pending.get('origin_run_id'),str)
                or not re.fullmatch(r'[0-9a-f]{64}',pending.get('request_id') or '')):
                raise ValueError('Prior pending source request is invalid')
            if pending['origin_run_id']!=previous_run.get('run_id') and not any(
                    isinstance(x,dict) and x.get('run_id')==pending['origin_run_id'] and x.get('pending_source_request')==pending
                    for x in state.get('run_history',[])):
                raise ValueError('Original pending source run is unavailable')
        updated = begin(acquire(state, owner, run_id, at=now), owner, run_id,
                        started_at=run['started_at'], scheduled_for=run['scheduled_for'], at=now)
        updated['last_started_at'] = run['started_at']
        updated['current_run']['request_counts'] = {'source':0,'paid':0,'openalex':0}
        if pending is not None:updated['current_run']['pending_source_request']=deepcopy(pending)
    else:
        previous = instant((state.get('current_run') or {}).get('observed_at'))
        if not previous or not 0 <= (now-previous).total_seconds() <= 40:
            raise ValueError('Previous worker heartbeat is stale or unavailable')
        updated = heartbeat(deepcopy(state), owner, run_id, at=now)
    updated['current_run']['scheduler'] = native_snapshot
    updated['last_heartbeat_at'] = now.isoformat()
    return _proposal(repo, head, state_meta, updated, phase)


def _proposal(repo, head, state_meta, updated, phase):
    content = json.dumps(updated, ensure_ascii=False, indent=2) + '\n'
    raw_new = content.encode('utf-8')
    tree = _git(repo, 'rev-parse', head + '^{tree}').decode('ascii').strip()
    if not SHA.fullmatch(tree):raise ValueError('Committed base tree is invalid')
    return {'phase': phase, 'expected_head': head, 'base_tree_sha': tree, 'path': WORKER,
            'base_blob': state_meta, 'content': content,
            'blob_sha': hashlib.sha1(b'blob ' + str(len(raw_new)).encode() + b'\0' + raw_new).hexdigest(),
            'size': len(raw_new), 'requires_atomic_update_and_lease_readback': True, 'writes': 0}
