"""Prepare single-writer lease transitions; the caller must enforce remote CAS.

These pure operations do not acquire a remote lock. Read the current worker
state and branch head, prepare a transition, commit it with an expected-head
update, then read back both the branch and lease before doing any work.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from tools.content_review.lifecycle import instant

MAX_LEASE_SECONDS = 1800


def _now(value):
    current = value or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('A timezone-aware lease time is required')
    return current.astimezone(timezone.utc)


def _identity(owner, run_id):
    if not isinstance(owner, str) or not owner or not isinstance(run_id, str) or not run_id:
        raise ValueError('A unique owner and run identity are required')


def _duration(seconds):
    if type(seconds) is not int or not 1 <= seconds <= MAX_LEASE_SECONDS:
        raise ValueError('Invalid bounded lease duration')


def _existing(state):
    if not isinstance(state, dict):
        raise ValueError('Invalid worker state')
    lease = state.get('lease')
    if lease is None:
        return None, None
    if not isinstance(lease, dict):
        raise ValueError('Invalid existing lease')
    _identity(lease.get('owner'), lease.get('run_id'))
    expiry = instant(lease.get('expires_at'))
    if not expiry:
        raise ValueError('Invalid existing lease expiry')
    return lease, expiry


def acquire(state, owner, run_id, seconds=MAX_LEASE_SECONDS, at=None):
    _identity(owner, run_id); _duration(seconds); now = _now(at)
    current, expiry = _existing(state)
    history = state.get('lease_history', [])
    if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
        raise ValueError('Invalid lease history')
    if any(entry.get('run_id') == run_id for entry in history):
        raise ValueError('An earlier run identity cannot be reused for acquisition')
    if current and expiry > now:
        raise ValueError('Another active lease must finish before acquisition')
    if current and current['run_id'] == run_id:
        raise ValueError('An expired run identity cannot be reused for acquisition')
    result = deepcopy(state)
    history = result.setdefault('lease_history', [])
    if current:
        history.append({**deepcopy(current), 'status': 'expired', 'expiry_observed_at': now.isoformat()})
    result['lease'] = {'owner': owner, 'run_id': run_id, 'acquired_at': now.isoformat(),
                       'expires_at': (now + timedelta(seconds=seconds)).isoformat()}
    return result


def renew(state, owner, run_id, seconds=MAX_LEASE_SECONDS, at=None):
    _identity(owner, run_id); _duration(seconds); now = _now(at)
    current, expiry = _existing(state)
    if not current or current['owner'] != owner or current['run_id'] != run_id or expiry <= now:
        raise ValueError('A matching unexpired lease is required for renewal')
    acquired = instant(current.get('acquired_at'))
    renewed = instant(current.get('renewed_at')) if current.get('renewed_at') else acquired
    if not acquired or not renewed or now < acquired or now < renewed:
        raise ValueError('Lease renewal cannot precede acquisition or renewal')
    result = deepcopy(state)
    result['lease']['expires_at'] = max(expiry, now + timedelta(seconds=seconds)).isoformat()
    result['lease']['renewed_at'] = now.isoformat()
    return result


def release(state, owner, run_id, at=None):
    _identity(owner, run_id); now = _now(at)
    current, expiry = _existing(state)
    if not current or current['owner'] != owner or current['run_id'] != run_id or expiry <= now:
        raise ValueError('A matching unexpired lease is required for release')
    acquired = instant(current.get('acquired_at'))
    renewed = instant(current.get('renewed_at')) if current.get('renewed_at') else acquired
    if not acquired or not renewed or now < acquired or now < renewed:
        raise ValueError('Lease release cannot precede acquisition or renewal')
    result = deepcopy(state)
    history = result.setdefault('lease_history', [])
    if not isinstance(history, list):
        raise ValueError('Invalid lease history')
    history.append({**deepcopy(current), 'status': 'released', 'released_at': now.isoformat()})
    result['lease'] = None
    return result
