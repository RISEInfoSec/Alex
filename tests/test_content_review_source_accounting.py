from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json

import pytest

from tools.content_review.source_accounting import prepare
from tools.content_review.source_worker import BRANCH,WORKFLOW,digest


def fixture():
    now=datetime(2026,11,7,0,0,tzinfo=timezone.utc);started=now-timedelta(seconds=30)
    state={'lease':{'owner':'worker','run_id':'scheduler-run','expires_at':(now+timedelta(minutes=10)).isoformat()},
           'current_run':{'run_id':'scheduler-run','application_status':'running','started_at':started.isoformat(),
                          'request_counts':{'source':0,'paid':0,'openalex':0}}}
    request={'schema_version':1,'started_at':started.isoformat(),'work_deadline':(started+timedelta(seconds=600)).isoformat(),
             'lease_owner':'worker','coordinator_run_id':'scheduler-run','source_request_limit':30,
             'records':[{'collection':'weekly','candidate_id':'one','content_sha256':'a'*64}]}
    request['request_id']=digest(request)
    state['current_run']['pending_source_request']={'request_id':request['request_id'],'reserved_limit':30}
    run={'id':123,'event':'push','head_branch':BRANCH,'path':WORKFLOW,'status':'completed','conclusion':'success',
         'head_sha':'b'*40,'run_attempt':1}
    result={'request_id':request['request_id'],'records':[{'collection':'weekly','candidate_id':'one','content_sha256':'a'*64,'evidence':[]}],
            'requests':2,'request_log':[{},{}],
            'provenance':{'GITHUB_SHA':run['head_sha'],'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
                          'GITHUB_REF':'refs/heads/'+BRANCH,'GITHUB_WORKFLOW_REF':'RISEInfoSec/Alex/'+WORKFLOW+'@refs/heads/'+BRANCH}}
    raw=json.dumps(result).encode();artifact={'id':987,'run_id':123,'sha256':hashlib.sha256(raw).hexdigest()}
    return now,state,request,raw,run,artifact


def call(now,state,request,raw,run,artifact):
    return prepare(state,request,raw,run,artifact,'worker','scheduler-run',at=now)


def test_verified_artifact_is_accounted_once_without_writes():
    now,state,request,raw,run,artifact=fixture();before=deepcopy(state)
    result=call(now,state,request,raw,run,artifact)
    assert result['status']=='prepared' and result['writes']==0 and result['requires_atomic_lease_and_readback']
    assert result['state']['current_run']['request_counts']['source']==2
    assert result['state']['current_run']['pending_source_request'] is None
    assert result['receipt']['independently_verified'] is True and state==before
    again=call(now,result['state'],request,raw,run,artifact)
    assert again['status']=='already_accounted' and again['state']==result['state']


def test_changed_artifact_or_unverified_run_cannot_be_counted():
    now,state,request,raw,run,artifact=fixture()
    with pytest.raises(ValueError,match='artifact identity'):
        call(now,state,request,raw+b' ',run,artifact)
    run['conclusion']='failure'
    with pytest.raises(ValueError,match='not independently verified'):
        call(now,state,request,raw,run,artifact)


def test_budget_and_existing_ambiguous_evidence_fail_closed():
    now,state,request,raw,run,artifact=fixture()
    state['current_run']['request_counts']['source']=29
    with pytest.raises(ValueError,match='single pending request'):
        call(now,state,request,raw,run,artifact)
    state['current_run']['request_counts']['source']=0
    state['current_run']['accounted_source_requests']=[{'request_id':request['request_id'],'requests':99}]
    with pytest.raises(ValueError,match='already accounted with different evidence'):
        call(now,state,request,raw,run,artifact)
