from copy import deepcopy
import json

import pytest

from tests.test_content_review_source_plan import fixture,call
from tools.content_review.source_request_guard import prepare


def guarded(repo,now,review,main,hb,snapshot,proposal):
    return prepare(repo,review,main,hb,snapshot,deepcopy(snapshot),'worker','run',proposal,at=now)


def test_source_request_and_reservation_are_a_two_file_atomic_bundle(tmp_path):
    now,review,main,hb,row,snapshot=fixture(tmp_path);proposal=call(tmp_path,now,review,main,hb,snapshot)
    result=guarded(tmp_path,now,review,main,hb,snapshot,proposal)
    proof,bundle=result['proof'],result['bundle'];path=proof['new_path']
    assert proof['kind']=='source_request' and proof['expected_head']==review and proof['heartbeat_head']==hb
    assert set(bundle['files'])=={'config/content_review_worker_status.json',path}
    assert json.loads(bundle['files'][path])==proposal['request']
    assert json.loads(bundle['files']['config/content_review_worker_status.json'])==proposal['reserved_state']
    assert result['writes']==0 and result['requires_atomic_update_and_readback']


def test_tampered_request_and_changed_review_decision_are_rejected(tmp_path):
    now,review,main,hb,row,snapshot=fixture(tmp_path);proposal=call(tmp_path,now,review,main,hb,snapshot)
    altered=deepcopy(proposal);altered['request']['records'][0]['url']='https://example.org/other'
    with pytest.raises(ValueError,match='differs from the verified plan'):
        guarded(tmp_path,now,review,main,hb,snapshot,altered)
    snapshot['submissions']=[{'id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                              'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    snapshot['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                            'candidate_id':row['candidate_id'],'review_number':1,'content_sha256':row['content_sha256'],'decision':'rejected'}]
    for k in ('submissions','decisions'):snapshot['read_evidence'][k]['rows_received']=1
    with pytest.raises(ValueError,match='differs from the verified plan'):
        guarded(tmp_path,now,review,main,hb,snapshot,proposal)
