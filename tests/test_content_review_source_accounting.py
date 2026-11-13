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
    state['current_run']['pending_source_request']={'request_id':request['request_id'],'origin_run_id':'scheduler-run','reserved_limit':30}
    run={'id':123,'event':'push','head_branch':BRANCH,'path':WORKFLOW,'status':'completed','conclusion':'success',
         'head_sha':'b'*40,'run_attempt':1}
    result={'schema_version':1,'status':'complete','read_only':True,'request_id':request['request_id'],'records':[{'collection':'weekly','candidate_id':'one','content_sha256':'a'*64,'evidence':[]}],
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


def test_accounting_persists_429_cooldown_and_rejects_missing_replay_state():
    now,state,request,raw,run,artifact=fixture();result=json.loads(raw)
    result['request_log']=[{'url':'https://publisher.example/a','started_at':now.isoformat(),'http_status':429,
                            'retry_not_before':(now+timedelta(hours=2)).isoformat()},{}]
    result['origin_backoff']={'publisher.example':{'reason':'http_429','retry_not_before':(now+timedelta(hours=2)).isoformat()}}
    raw=json.dumps(result).encode();artifact['sha256']=hashlib.sha256(raw).hexdigest()
    saved=call(now,state,request,raw,run,artifact)['state']
    assert saved['source_origin_backoff']['publisher.example']['retry_not_before']==(now+timedelta(hours=2)).isoformat()
    assert call(now,saved,request,raw,run,artifact)['status']=='already_accounted'
    del saved['source_origin_backoff']
    with pytest.raises(ValueError,match='cooldown is missing'):call(now,saved,request,raw,run,artifact)


def test_partial_artifact_is_not_accounted_even_when_its_hash_matches():
    now,state,request,raw,run,artifact=fixture()
    result=json.loads(raw);result['status']='running';raw=json.dumps(result).encode()
    artifact['sha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='Complete read-only source artifact'):
        call(now,state,request,raw,run,artifact)


def test_budget_and_existing_ambiguous_evidence_fail_closed():
    now,state,request,raw,run,artifact=fixture()
    state['current_run']['request_counts']['source']=29
    with pytest.raises(ValueError,match='Original source request budget'):
        call(now,state,request,raw,run,artifact)
    state['current_run']['request_counts']['source']=0
    state['current_run']['accounted_source_requests']=[{'request_id':request['request_id'],'requests':99}]
    with pytest.raises(ValueError,match='already accounted with different evidence'):
        call(now,state,request,raw,run,artifact)


def test_late_artifact_is_retained_without_charging_or_repeating_new_run():
    now,state,request,raw,run,artifact=fixture();old=deepcopy(state['current_run'])
    old['application_status']='failed'
    state['run_history']=[old]
    state['lease_history']=[{'owner':'worker','run_id':'scheduler-run','status':'released'}]
    state['lease']={'owner':'next-worker','run_id':'next-run','expires_at':(now+timedelta(minutes=10)).isoformat()}
    state['current_run']={'run_id':'next-run','application_status':'running','started_at':(now-timedelta(seconds=5)).isoformat(),
        'request_counts':{'source':0,'paid':0,'openalex':0},'pending_source_request':deepcopy(old['pending_source_request'])}
    before=deepcopy(state)
    result=prepare(state,request,raw,run,artifact,'next-worker','next-run',at=now)
    saved=result['state']['current_run']
    assert saved['request_counts']['source']==0 and saved['pending_source_request'] is None
    assert saved['accounted_source_requests'][0]['origin_run_id']=='scheduler-run'
    assert saved['accounted_source_requests'][0]['charged_to_current_run'] is False
    assert result['state']['run_history']==before['run_history'] and state==before


@pytest.mark.parametrize('defect', ['missing_run','missing_lease','changed_pending','changed_budget'])
def test_late_artifact_requires_original_run_and_lease_evidence(defect):
    now,state,request,raw,run,artifact=fixture();old=deepcopy(state['current_run'])
    old['application_status']='failed'
    state['run_history']=[old]
    state['lease_history']=[{'owner':'worker','run_id':'scheduler-run','status':'released'}]
    state['lease']={'owner':'next-worker','run_id':'next-run','expires_at':(now+timedelta(minutes=10)).isoformat()}
    state['current_run']={'run_id':'next-run','application_status':'running','started_at':(now-timedelta(seconds=5)).isoformat(),
        'request_counts':{'source':0,'paid':0,'openalex':0},'pending_source_request':deepcopy(old['pending_source_request'])}
    if defect=='missing_run':state['run_history']=[]
    if defect=='missing_lease':state['lease_history']=[]
    if defect=='changed_pending':state['run_history'][0]['pending_source_request']['reserved_limit']=29
    if defect=='changed_budget':state['run_history'][0]['request_counts']['source']=1
    with pytest.raises(ValueError):
        prepare(state,request,raw,run,artifact,'next-worker','next-run',at=now)
