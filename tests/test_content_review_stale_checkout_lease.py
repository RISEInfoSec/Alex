"""The lease starts after checkout; immutable heads are the source of truth."""
import json

from tests.test_content_review_source_plan import fixture, call
from tests.test_content_review_verified_inputs import put


def test_source_plan_uses_committed_lease_when_checkout_predates_acquisition(tmp_path):
    now,review,main,hb,row,snap=fixture(tmp_path)
    state=json.loads((tmp_path/'config/content_review_worker_status.json').read_text())
    state['lease']=None;state['current_run']=None
    put(tmp_path,'config/content_review_worker_status.json',state)
    result=call(tmp_path,now,review,main,hb,snap)
    assert result['status']=='prepared' and result['writes']==0 and result['provider_requests']==0
