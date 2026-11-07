"""Prepare run observations without losing the previous worker record.

This is a pure state transition, not a lease acquisition or a scheduler API.
The caller must persist it with expected-head compare-and-swap, read it back,
and maintain the shared lease and heartbeat throughout all work.
"""
from copy import deepcopy
from datetime import datetime, timezone

from tools.content_review.lifecycle import instant


def begin(state, owner, run_id, *, started_at, scheduled_for, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware run observation required')
    if not isinstance(state, dict) or not isinstance(owner, str) or not owner or not isinstance(run_id, str) or not run_id:
        raise ValueError('Worker state and unique run identity required')
    lease = state.get('lease') or {}
    if not isinstance(lease, dict):
        raise ValueError('Invalid lease state')
    expires = instant(lease.get('expires_at'))
    started, scheduled = instant(started_at), instant(scheduled_for)
    if (lease.get('owner') != owner or lease.get('run_id') != run_id or
            not expires or expires <= now):
        raise ValueError('A matching unexpired lease is required')
    if not started or not scheduled or started > now or (now - started).total_seconds() >= 600:
        raise ValueError('Native run has no remaining bounded work window')
    history = state.get('run_history', [])
    if not isinstance(history, list) or any(not isinstance(x, dict) or not x.get('run_id') for x in history):
        raise ValueError('Existing run history is invalid')
    if any(x['run_id'] == run_id for x in history):
        raise ValueError('Prior run identity cannot be reused')
    previous = state.get('current_run')
    if previous is not None:
        if not isinstance(previous, dict) or not previous.get('run_id') or previous['run_id'] == run_id:
            raise ValueError('Prior current run is invalid or reused')
        if previous.get('application_status') not in ('complete', 'failed', 'deferred', 'running'):
            raise ValueError('Prior run status is unknown; reconciliation is required')
        if previous.get('application_status') == 'running':
            expiries = state.get('lease_history', [])
            if not isinstance(expiries, list) or not any(
                    x.get('run_id') == previous['run_id'] and x.get('status') == 'expired'
                    for x in expiries if isinstance(x, dict)):
                raise ValueError('Prior running observation has no expired-lease evidence')
        matches = [x for x in history if x['run_id'] == previous['run_id']]
        if matches and (len(matches) != 1 or matches[0] != previous):
            raise ValueError('Prior run history conflicts with current observation')
    result = deepcopy(state)
    if previous is not None and not any(x['run_id'] == previous['run_id'] for x in history):
        result.setdefault('run_history', []).append(deepcopy(previous))
    result['current_run'] = {'run_id': run_id, 'application_status': 'running',
                             'started_at': started.isoformat(), 'scheduled_for': scheduled.isoformat(),
                             'observed_at': now.isoformat()}
    return result
