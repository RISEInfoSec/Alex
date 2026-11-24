"""Reconcile only a prior, expired acquisition with no downstream effects."""
import json
from copy import deepcopy
from datetime import datetime, timezone
from tools.content_review.lease_transition import _proposal
from tools.content_review.lifecycle import instant
from tools.content_review.verified_inputs import _path_blob
from tools.content_review.source_clock_state import inspect, WORKER
from tools.content_review.site_worker_client import post

OWNER = 'weekly-source-processing'


def expired_proposal(repo, head, run_id, *, at):
    raw, meta = _path_blob(repo, head, WORKER)
    state = json.loads(raw)
    lease, run = state.get('lease') or {}, state.get('current_run') or {}
    expires, acquired = instant(lease.get('expires_at')), instant(lease.get('acquired_at'))
    if (lease.get('owner') != OWNER or lease.get('run_id') != run_id or run.get('run_id') != run_id
            or not expires or not acquired or not acquired < expires <= at
            or run.get('application_status') != 'running' or set(run) - {
                'run_id','application_status','started_at','scheduled_for','observed_at','request_counts','scheduler'}
            or run.get('request_counts') != {'source':0,'paid':0,'openalex':0}
            or any(h.get('run_id') == run_id for h in state.get('lease_history', []))):
        return None
    updated = deepcopy(state)
    stamp = at.isoformat()
    updated.setdefault('lease_history', []).append({**lease,'status':'expired','expiry_observed_at':stamp})
    updated['lease'] = None
    updated['current_run'].update(application_status='failed', application_completed_at=stamp, failure_code='reconciliation_hold')
    updated['last_error'] = 'reconciliation_hold'
    return _proposal(repo, head, meta, updated, 'expire')


def reconcile_prior(repo, token, new_run, state):
    prior = state.get('lease_run')
    if (not prior or prior == new_run or state.get('lease_owner') != OWNER
            or state.get('current_run') != prior or state.get('active_source_job_runs') != []
            or state.get('pending_request')):
        return state
    proof = inspect(repo, prior)
    if proof['review'] != state['review'] or proof['lease_run'] != prior or proof['receipt'] or proof['active_source_job_runs'] or proof['pending_request']:
        return state
    proposal = expired_proposal(repo, proof['review'], prior, at=datetime.now(timezone.utc))
    if proposal is None:
        return state
    # The Site proves the exact acquisition-only tree and a quiet heartbeat,
    # checks every write fence, then commits using the expected protected head.
    result = post('lease', {'owner':OWNER,'runId':prior,'proposal':proposal}, token)
    checked = inspect(repo, prior)
    if (result.get('status') != 'committed_and_read_back' or checked['review'] != result.get('commit_sha')
            or not checked['reconciled_zero_request_failure']):
        raise ValueError('Expired source lease outcome unconfirmed')
    return inspect(repo, new_run)
