from copy import deepcopy
from datetime import timedelta
import hashlib
import json

import pytest

from tests.test_content_review_source_plan import fixture,call
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as heartbeat
from tools.content_review.source_result_guard import prepare
from tools.content_review.source_worker import BRANCH,WORKFLOW


def setup(repo):
    now,review,main,hb,row,snapshot=fixture(repo)
    proposal=call(repo,now,review,main,hb,snapshot);request=proposal['request'];state=proposal['reserved_state']
    request_path='config/content_review_source_requests/'+request['request_id']+'.json'
    put(repo,'config/content_review_worker_status.json',state);put(repo,request_path,request)
    git(repo,'add','.');git(repo,'commit','-qm','reserved')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    beat=heartbeat(state,review,'worker','run',at=now+timedelta(seconds=5))
    git(repo,'checkout','-q','heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','new heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    run={'id':123,'event':'push','head_branch':BRANCH,'path':WORKFLOW,'status':'completed','conclusion':'success',
         'head_sha':review,'run_attempt':1}
    item=request['records'][0]
    result={'schema_version':1,'status':'complete','read_only':True,'request_id':request['request_id'],'records':[{'collection':item['collection'],'candidate_id':item['candidate_id'],
             'content_sha256':item['content_sha256'],'evidence':[]}], 'requests':2,'request_log':[{},{}],
            'provenance':{'GITHUB_SHA':review,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
                          'GITHUB_REF':'refs/heads/'+BRANCH,'GITHUB_WORKFLOW_REF':'RISEInfoSec/Alex/'+WORKFLOW+'@refs/heads/'+BRANCH}}
    raw=json.dumps(result).encode();artifact={'id':987,'run_id':123,'sha256':hashlib.sha256(raw).hexdigest()}
    return now+timedelta(seconds=5),review,main,hb,snapshot,request,raw,run,artifact


def call_guard(repo,now,review,main,hb,snapshot,request,raw,run,artifact):
    return prepare(repo,review,main,hb,snapshot,deepcopy(snapshot),request['request_id'],raw,run,artifact,
                   'worker','run',observed_heads={'review':review,'main':main},at=now)


def test_receipt_and_usage_are_prepared_atomically_without_publication(tmp_path):
    values=setup(tmp_path);result=call_guard(tmp_path,*values)
    assert result['status']=='prepared' and result['writes']==0
    proof,bundle=result['proof'],result['bundle']
    assert proof['kind']=='source_result' and len(bundle['files'])==2
    state=json.loads(bundle['files']['config/content_review_worker_status.json'])
    receipt=json.loads(bundle['files'][proof['new_path']])
    assert state['current_run']['request_counts']['source']==2 and state['current_run']['pending_source_request'] is None
    assert receipt['independently_verified'] is True and proof['requires_remote_head_d1_and_lease_recheck']


def test_altered_artifact_or_changed_remote_head_stops_result(tmp_path):
    now,review,main,hb,snapshot,request,raw,run,artifact=setup(tmp_path)
    with pytest.raises(ValueError,match='artifact identity'):
        call_guard(tmp_path,now,review,main,hb,snapshot,request,raw+b' ',run,artifact)
    with pytest.raises(ValueError,match='heads are unavailable or changed'):
        prepare(tmp_path,review,main,hb,snapshot,deepcopy(snapshot),request['request_id'],raw,run,artifact,
                'worker','run',observed_heads={'review':'f'*40,'main':main},at=now)


@pytest.mark.parametrize('forged_head', ['nonancestor','prior_commit'])
def test_successful_artifact_must_come_from_atomic_request_commit(tmp_path,forged_head):
    now,review,main,hb,snapshot,request,raw,run,artifact=setup(tmp_path)
    bad_head=hb if forged_head=='nonancestor' else git(tmp_path,'rev-parse',review+'^')
    run['head_sha']=bad_head
    result=json.loads(raw);result['provenance']['GITHUB_SHA']=bad_head
    raw=json.dumps(result).encode();artifact['sha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='not bound to the retained atomic reservation'):
        call_guard(tmp_path,now,review,main,hb,snapshot,request,raw,run,artifact)
