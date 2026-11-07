from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json

import pytest

from tests.test_content_review_verified_inputs import fixture as inputs_fixture,git,put
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.lifecycle import evaluate
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.source_plan import prepare


def fixture(repo,url='https://example.org/paper',extra_url=None):
    _,main,_=inputs_fixture(repo);now=datetime.now(timezone.utc)
    row={'candidate_id':'source-1','review_number':1,'title':'Example','authors':'Author','year':2025,'doi':'',
         'source_url':url,'abstract':'','document_type':'research_paper','decision':'pending','preflight':{'checks':{}}}
    row['content_sha256']=reviewed_digest(row)
    row['preflight']['checks']['duplicates']={'status':'passed','content_sha256':row['content_sha256'],
                                               'checked_at':now.isoformat(),'evidence':'verified local inventory'}
    life=evaluate(row,at=now);life['collection']='weekly';rows=[row];entries={'weekly:source-1':life}
    if extra_url:
        peer={**deepcopy(row),'candidate_id':'source-2','review_number':2,'source_url':extra_url}
        peer['content_sha256']=reviewed_digest(peer)
        peer['preflight']['checks']['duplicates']['content_sha256']=peer['content_sha256']
        peer_life=evaluate(peer,at=now);peer_life['collection']='weekly'
        rows.append(peer);entries['weekly:source-2']=peer_life
    state={'lease':{'owner':'worker','run_id':'run','acquired_at':(now-timedelta(seconds=10)).isoformat(),
                    'expires_at':(now+timedelta(minutes=20)).isoformat()},
           'current_run':{'run_id':'run','application_status':'running','started_at':(now-timedelta(seconds=10)).isoformat(),
                          'observed_at':(now-timedelta(seconds=10)).isoformat(),
                          'request_counts':{'source':0,'paid':0,'openalex':0},
                          'scheduler':{'id':'Automation_worker','last_run':{'id':'run','recorded_status':'in_progress'}}}}
    put(repo,'config/weekly_review_manifest.json',{'records':rows,'preflight_records':[]})
    put(repo,'config/content_review_candidate_lifecycle.json',{'records':entries})
    put(repo,'config/content_review_worker_status.json',state)
    put(repo,'config/content_review_workflow.json',{'bounded_processing_pilot':{'total_runtime_seconds':720,'checkpoint_reserve_seconds':120}})
    git(repo,'add','.');git(repo,'commit','-qm','source fixture')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    beat=prepare_heartbeat(state,review,'worker','run',at=now)
    git(repo,'checkout','-qb','heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    snap={'submissions':[],'decisions':[],'jobs':[]}
    snap['read_evidence']={k:{'complete':True,'rows_received':0,'truncated_values':0,'omitted_columns':0}
                           for k in ('submissions','decisions','jobs')}
    return now,review,main,hb,row,snap


def call(repo,now,review,main,hb,snap):
    return prepare(repo,review,main,hb,snap,deepcopy(snap),'worker','run',
                   observed_heads={'review':review,'main':main},at=now)


def test_source_request_is_hash_bound_and_never_dispatched(tmp_path,monkeypatch):
    import socket
    now,review,main,hb,row,snap=fixture(tmp_path)
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('unexpected network'))
    result=call(tmp_path,now,review,main,hb,snap)
    assert result['status']=='prepared' and result['writes']==result['provider_requests']==0
    assert result['request']['records'][0]['content_sha256']==row['content_sha256']
    assert result['request']['source_request_limit']==30 and result['requires_live_recheck_before_dispatch']
    assert result['request']['coordinator_run_id']=='run'
    assert result['reserved_state']['current_run']['pending_source_request']['request_id']==result['request']['request_id']
    assert result['requires_atomic_reservation_and_live_recheck'] is True


def test_d1_rejection_never_enters_a_source_request(tmp_path):
    now,review,main,hb,row,snap=fixture(tmp_path)
    snap['submissions']=[{'id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                          'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    snap['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                        'candidate_id':row['candidate_id'],'review_number':1,'content_sha256':row['content_sha256'],'decision':'rejected'}]
    for k in ('submissions','decisions'):snap['read_evidence'][k]['rows_received']=1
    result=call(tmp_path,now,review,main,hb,snap)
    assert result['status']=='no_due_source_in_plan' and result['request'] is None


def test_changed_working_manifest_and_uncontrolled_openalex_target_fail_closed(tmp_path):
    now,review,main,hb,row,snap=fixture(tmp_path)
    put(tmp_path,'config/weekly_review_manifest.json',{'records':[]})
    with pytest.raises(ValueError,match='Incomplete or altered Git blob'):
        call(tmp_path,now,review,main,hb,snap)
    other=tmp_path/'openalex';other.mkdir();now,review,main,hb,row,snap=fixture(other,'https://api.openalex.org/works/example')
    result=call(other,now,review,main,hb,snap)
    assert result['status']=='all_source_candidates_held' and result['request'] is None
    assert result['held'][0]['reason']=='openalex_requires_controlled_route'


def test_controlled_openalex_route_does_not_block_an_eligible_peer(tmp_path):
    now,review,main,hb,row,snap=fixture(tmp_path,'https://api.openalex.org/works/example','https://example.org/peer')
    result=call(tmp_path,now,review,main,hb,snap)
    assert result['status']=='prepared' and result['held'][0]['reason']=='openalex_requires_controlled_route'
    assert [x['candidate_id'] for x in result['request']['records']]==['source-2']


def test_doi_target_can_be_prepared_after_owner_release(tmp_path):
    now,review,main,hb,row,snap=fixture(tmp_path,'https://doi.org/10.1/example')
    result=call(tmp_path,now,review,main,hb,snap)
    assert result['status']=='prepared' and result['request']['records'][0]['url']==row['source_url']


def test_request_count_must_match_the_committed_run_ledger(tmp_path):
    now,review,main,hb,row,snap=fixture(tmp_path)
    with pytest.raises(ValueError,match='request accounting'):
        prepare(tmp_path,review,main,hb,snap,deepcopy(snap),'worker','run',
                observed_heads={'review':review,'main':main},source_requests_used=1,at=now)


def test_source_runner_requires_the_single_durable_reservation(tmp_path):
    from tools.content_review.source_worker import validate
    now,review,main,hb,row,snap=fixture(tmp_path)
    proposal=call(tmp_path,now,review,main,hb,snap);request=proposal['request'];state=proposal['reserved_state']
    request_path=tmp_path/'config/content_review_source_requests'/(request['request_id']+'.json')
    put(tmp_path,str(request_path.relative_to(tmp_path)),request)
    put(tmp_path,'config/content_review_worker_status.json',state)
    assert validate(tmp_path,request_path)['request_id']==request['request_id']
    state['current_run']['pending_source_request']=None;put(tmp_path,'config/content_review_worker_status.json',state)
    with pytest.raises(ValueError,match='single pending source request'):
        validate(tmp_path,request_path)


def test_pending_request_prevents_a_second_dispatch_plan(tmp_path):
    now,review,main,hb,row,snap=fixture(tmp_path)
    first=call(tmp_path,now,review,main,hb,snap)
    put(tmp_path,'config/content_review_worker_status.json',first['reserved_state'])
    git(tmp_path,'add','config/content_review_worker_status.json');git(tmp_path,'commit','-qm','pending reservation')
    new_head=git(tmp_path,'rev-parse','HEAD')
    second=call(tmp_path,now,new_head,main,hb,snap)
    assert second['status']=='pending_source_result' and second['request'] is None
