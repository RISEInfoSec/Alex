from datetime import datetime,timezone,timedelta
import pytest
from tools.content_review.checkpoint import prepare,heartbeat

def test_checkpoint_rejects_expired_or_other_lease(tmp_path):
    at=datetime.now(timezone.utc)
    with pytest.raises(ValueError,match='lease'):prepare(tmp_path,[],{},dict(owner='other',expires_at=(at+timedelta(minutes=1)).isoformat()),'mine',at)
    with pytest.raises(ValueError,match='lease'):prepare(tmp_path,[],{},dict(owner='mine',expires_at=at.isoformat()),'mine',at)

def test_heartbeat_cannot_relabel_another_run():
    with pytest.raises(ValueError,match='run mismatch'):heartbeat({'lease':{'owner':'me'},'current_run':{'run_id':'old'}},'me','new')
