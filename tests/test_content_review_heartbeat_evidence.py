from copy import deepcopy
from datetime import datetime,timedelta,timezone

import pytest

from tools.content_review.heartbeat_evidence import prepare,verify


def fixture():
    now=datetime(2026,11,7,0,0,tzinfo=timezone.utc); head='a'*40
    state={'lease':{'owner':'worker','run_id':'run','acquired_at':now.isoformat(),
                    'expires_at':(now+timedelta(minutes=30)).isoformat()},
           'current_run':{'run_id':'run','application_status':'running','started_at':now.isoformat(),
                          'scheduler':{'id':'Automation_worker','last_run':{'id':'run','recorded_status':'in_progress'}}}}
    return now,head,state


def test_separate_heartbeat_is_bound_to_exact_review_head_and_lease():
    now,head,state=fixture();before=deepcopy(state)
    beat=prepare(state,head,'worker','run',at=now+timedelta(seconds=30))
    assert verify(beat,state,head,'worker','run',at=now+timedelta(seconds=35))==now+timedelta(seconds=30)
    assert state==before
    with pytest.raises(ValueError,match='review head'):
        verify(beat,state,'b'*40,'worker','run',at=now+timedelta(seconds=35))
    with pytest.raises(ValueError,match='stale'):
        verify(beat,state,head,'worker','run',at=now+timedelta(seconds=71))


@pytest.mark.parametrize('field',['owner','run_id','lease_acquired_at','lease_expires_at','scheduler_id'])
def test_foreign_heartbeat_cannot_claim_current_worker(field):
    now,head,state=fixture();beat=prepare(state,head,'worker','run',at=now)
    beat[field]='other'
    with pytest.raises(ValueError,match='not bound'):
        verify(beat,state,head,'worker','run',at=now)


def test_expired_lease_and_backwards_heartbeat_fail_closed():
    now,head,state=fixture();beat=prepare(state,head,'worker','run',at=now+timedelta(seconds=5))
    with pytest.raises(ValueError,match='backwards'):
        prepare(state,head,'worker','run',previous=beat,at=now+timedelta(seconds=4))
    with pytest.raises(ValueError,match='unexpired'):
        verify(beat,state,head,'worker','run',at=now+timedelta(minutes=31))
