"""Prepare and verify a heartbeat stored separately from review checkpoints.

The caller must authenticate both Git refs, use expected-head updates on the
heartbeat ref, and check the review head again before any candidate write. A
heartbeat is liveness evidence, not a lease or publication authority.
"""
from datetime import datetime, timezone
import re

from tools.content_review.lifecycle import instant
from tools.content_review.verified_inputs import SHA


def _state(state, review_head, owner, run_id, now):
    if not isinstance(state,dict) or not isinstance(review_head,str) or not SHA.fullmatch(review_head):
        raise ValueError('Verified review state and head are required')
    if not isinstance(owner,str) or not owner or not isinstance(run_id,str) or not re.fullmatch(r'[a-zA-Z0-9-]+',run_id):
        raise ValueError('Valid lease owner and run are required')
    lease=state.get('lease') or {};run=state.get('current_run') or {};scheduler=run.get('scheduler') or {}
    expiry=instant(lease.get('expires_at'));acquired=instant(lease.get('acquired_at'));started=instant(run.get('started_at'))
    if (lease.get('owner')!=owner or lease.get('run_id')!=run_id or not expiry or expiry<=now
        or not acquired or acquired>now or run.get('run_id')!=run_id or run.get('application_status')!='running'
        or not started or started>now or not isinstance(scheduler.get('id'),str) or not scheduler['id']
        or (scheduler.get('last_run') or {}).get('id')!=run_id
        or (scheduler.get('last_run') or {}).get('recorded_status')!='in_progress'):
        raise ValueError('Matching unexpired native worker lease is required')
    return lease,run,scheduler


def prepare(state, review_head, owner, run_id, *, previous=None, at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware heartbeat is required')
    lease,run,scheduler=_state(state,review_head,owner,run_id,now)
    if previous is not None:
        if not isinstance(previous,dict):raise ValueError('Previous heartbeat is invalid')
        prior=instant(previous.get('observed_at'))
        if not prior or prior>now:raise ValueError('Heartbeat cannot move backwards')
        if previous.get('run_id')==run_id and (previous.get('owner')!=owner or previous.get('lease_acquired_at')!=lease['acquired_at']):
            raise ValueError('Heartbeat lease identity changed')
    return {'schema_version':1,'review_head':review_head,'owner':owner,'run_id':run_id,
            'scheduler_id':scheduler['id'],'started_at':run['started_at'],
            'lease_acquired_at':lease['acquired_at'],'lease_expires_at':lease['expires_at'],
            'observed_at':now.isoformat()}


def verify(record, state, review_head, owner, run_id, *, at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware heartbeat verification is required')
    lease,run,scheduler=_state(state,review_head,owner,run_id,now)
    if not isinstance(record,dict):raise ValueError('Separate heartbeat evidence is unavailable')
    expected={'schema_version':1,'review_head':review_head,'owner':owner,'run_id':run_id,
              'scheduler_id':scheduler['id'],'started_at':run['started_at'],
              'lease_acquired_at':lease['acquired_at'],'lease_expires_at':lease['expires_at']}
    if any(record.get(k)!=v for k,v in expected.items()):raise ValueError('Heartbeat is not bound to the current lease and review head')
    observed=instant(record.get('observed_at'))
    if not observed or observed<instant(run['started_at']) or observed<instant(lease['acquired_at']) or observed>now or (now-observed).total_seconds()>40:
        raise ValueError('Separate heartbeat is stale or unavailable')
    return observed
