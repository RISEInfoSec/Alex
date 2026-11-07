from copy import deepcopy
from datetime import timedelta
import hashlib
import json

import pytest

from tests.test_content_review_source_result_guard import setup, call_guard
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.heartbeat_evidence import prepare as heartbeat
from tools.content_review.source_retention import prepare


def fixture(repo):
    now,review,main,hb,snapshot,request,raw,run,artifact=setup(repo)
    result=json.loads(raw)
    result['records'][0].update(status='retrieved',next_action='Inspect retained evidence.',evidence=[{
        'text':'example evidence','text_sha256':hashlib.sha256(b'example evidence').hexdigest(),
        'body_sha256':'f'*64,'retrieved_at':now.isoformat(),'http_status':200}])
    raw=json.dumps(result).encode();artifact['sha256']=hashlib.sha256(raw).hexdigest()
    guarded=call_guard(repo,now,review,main,hb,snapshot,request,raw,run,artifact)
    for path,content in guarded['bundle']['files'].items():put(repo,path,content)
    git(repo,'add','.');git(repo,'commit','-qm','receipt')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    state=json.loads((repo/'config/content_review_worker_status.json').read_text())
    beat=heartbeat(state,review,'worker','run',at=now+timedelta(seconds=1))
    git(repo,'checkout','-q','heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','receipt heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    return now+timedelta(seconds=1),review,main,hb,snapshot,request,raw,run,artifact


def call(repo,now,review,main,hb,snapshot,request,raw,run,artifact):
    item=request['records'][0]
    return prepare(repo,review,main,hb,snapshot,deepcopy(snapshot),request['request_id'],raw,run,artifact,
                   item['collection'],item['candidate_id'],'worker','run',
                   observed_heads={'review':review,'main':main},at=now)


def test_retains_only_verified_source_evidence_without_passing_a_gate(tmp_path):
    values=fixture(tmp_path);proposal=call(tmp_path,*values)
    assert proposal['status']=='prepared' and proposal['writes']==0
    assert proposal['gate_passed'] is False and proposal['publication_authorized'] is False
    before=json.loads((tmp_path/proposal['path']).read_text())
    after=json.loads(proposal['content'])
    old,new=before['records'][0],after['records'][0]
    assert new['source_processing']['retrieval_status']=='retrieved'
    assert new['source_processing']['receipt'].endswith(values[5]['request_id']+'.json')
    assert new['content_sha256']==old['content_sha256'] and new['decision']==old['decision']
    assert new['preflight']==old['preflight'] and (tmp_path/proposal['path']).read_text()!=proposal['content']


def test_private_review_decision_prevents_source_retention(tmp_path):
    now,review,main,hb,snapshot,request,raw,run,artifact=fixture(tmp_path)
    item=request['records'][0]
    snapshot['submissions']=[{'id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                              'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    snapshot['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                            'candidate_id':item['candidate_id'],'review_number':1,'content_sha256':item['content_sha256'],'decision':'rejected'}]
    for key in ('submissions','decisions'):snapshot['read_evidence'][key]['rows_received']=1
    with pytest.raises(ValueError,match='private review decision'):
        call(tmp_path,now,review,main,hb,snapshot,request,raw,run,artifact)


def test_altered_artifact_and_moved_head_prevent_retention(tmp_path):
    now,review,main,hb,snapshot,request,raw,run,artifact=fixture(tmp_path)
    with pytest.raises(ValueError,match='artifact identity'):
        call(tmp_path,now,review,main,hb,snapshot,request,raw+b' ',run,artifact)
    with pytest.raises(ValueError,match='heads are unavailable or changed'):
        prepare(tmp_path,review,main,hb,snapshot,deepcopy(snapshot),request['request_id'],raw,run,artifact,
                'weekly','source-1','worker','run',observed_heads={'review':'a'*40,'main':main},at=now)


def test_retention_stops_before_the_checkpoint_reserve(tmp_path):
    now,review,main,hb,snapshot,request,raw,run,artifact=fixture(tmp_path)
    late=now+timedelta(seconds=580)
    state=json.loads((tmp_path/'config/content_review_worker_status.json').read_text())
    beat=heartbeat(state,review,'worker','run',at=late)
    branch=git(tmp_path,'symbolic-ref','--short','HEAD')
    git(tmp_path,'checkout','-q','heartbeat');put(tmp_path,'config/content_review_detached_heartbeat.json',beat)
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','late heartbeat');hb=git(tmp_path,'rev-parse','HEAD');git(tmp_path,'checkout','-q',branch)
    with pytest.raises(ValueError,match='checkpoint reserve'):
        call(tmp_path,late,review,main,hb,snapshot,request,raw,run,artifact)
