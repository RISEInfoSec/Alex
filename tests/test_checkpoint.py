from datetime import datetime,timezone,timedelta
import pytest
from tools.content_review.checkpoint import prepare,heartbeat

def test_checkpoint_rejects_expired_or_other_lease(tmp_path):
    at=datetime.now(timezone.utc)
    with pytest.raises(ValueError,match='lease'):prepare(tmp_path,[],{},dict(owner='other',expires_at=(at+timedelta(minutes=1)).isoformat()),'mine',at)
    with pytest.raises(ValueError,match='lease'):prepare(tmp_path,[],{},dict(owner='mine',expires_at=at.isoformat()),'mine',at)

def test_heartbeat_cannot_relabel_another_run():
    at=datetime.now(timezone.utc)
    lease={'owner':'me','run_id':'new','expires_at':(at+timedelta(minutes=1)).isoformat()}
    with pytest.raises(ValueError,match='run mismatch'):heartbeat({'lease':lease,'current_run':{'run_id':'old'}},'me','new',at)

def test_heartbeat_rejects_expired_or_foreign_lease_without_mutation():
    at=datetime.now(timezone.utc)
    for lease in ({'owner':'me','run_id':'run','expires_at':at.isoformat()},
                  {'owner':'me','run_id':'other','expires_at':(at+timedelta(minutes=1)).isoformat()},
                  {'owner':'me','run_id':'run'}):
        state={'lease':lease,'current_run':{'run_id':'run'}}
        with pytest.raises(ValueError,match='lease'):heartbeat(state,'me','run',at)
        assert 'last_heartbeat_at' not in state and 'observed_at' not in state['current_run']

def test_matching_unexpired_lease_can_heartbeat_but_cannot_go_back_in_time():
    at=datetime.now(timezone.utc)
    state={'lease':{'owner':'me','run_id':'run','expires_at':(at+timedelta(minutes=1)).isoformat()},
           'current_run':{'run_id':'run'}}
    heartbeat(state,'me','run',at)
    assert state['current_run']['observed_at']==at.isoformat()
    with pytest.raises(ValueError,match='backwards'):heartbeat(state,'me','run',at-timedelta(seconds=1))
    assert state['current_run']['observed_at']==at.isoformat()
