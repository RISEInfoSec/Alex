from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tools.content_review.run_state import begin


def fixture():
    now = datetime(2026, 11, 6, 22, 0, tzinfo=timezone.utc)
    state = {'lease': {'owner':'worker', 'run_id':'new', 'expires_at':(now + timedelta(minutes=10)).isoformat()},
             'current_run': {'run_id':'old', 'application_status':'complete', 'completed_actions':['old receipt']},
             'lease_history': [], 'unrelated_checkpoint': {'previous':'preserved'}}
    return now, state


def start(now, state):
    return begin(state, 'worker', 'new', started_at=now.isoformat(), scheduled_for=now.isoformat(), at=now)


def test_start_preserves_the_entire_previous_run_and_other_state():
    now, state = fixture(); before = deepcopy(state)
    result = start(now, state)
    assert state == before
    assert result['run_history'] == [before['current_run']]
    assert result['unrelated_checkpoint'] == before['unrelated_checkpoint']
    assert result['current_run']['run_id'] == 'new'
    assert result['current_run']['application_status'] == 'running'


def test_old_running_state_needs_evidence_its_lease_expired():
    now, state = fixture(); state['current_run']['application_status'] = 'running'
    with pytest.raises(ValueError, match='expired-lease evidence'):
        start(now, state)
    state['lease_history'].append({'run_id':'old', 'status':'expired'})
    assert start(now, state)['run_history'][0] == state['current_run']


def test_duplicate_run_or_conflicting_history_is_rejected():
    now, state = fixture(); state['run_history'] = [{'run_id':'new'}]
    with pytest.raises(ValueError, match='cannot be reused'):
        start(now, state)
    state['run_history'] = [{'run_id':'old', 'application_status':'changed'}]
    with pytest.raises(ValueError, match='history conflicts'):
        start(now, state)


def test_stale_run_or_foreign_lease_is_rejected():
    now, state = fixture()
    with pytest.raises(ValueError, match='work window'):
        begin(state, 'worker', 'new', started_at=(now-timedelta(minutes=10)).isoformat(),
              scheduled_for=now.isoformat(), at=now)
    state['lease']['owner'] = 'someone-else'
    with pytest.raises(ValueError, match='matching unexpired lease'):
        start(now, state)


def test_unknown_prior_status_requires_reconciliation():
    now, state = fixture(); state['current_run']['application_status'] = 'unknown'
    with pytest.raises(ValueError, match='status is unknown'):
        start(now, state)
