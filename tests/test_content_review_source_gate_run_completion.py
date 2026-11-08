from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json

import pytest
from tests.test_content_review_site_source_gate_writer import request as source_fixture,rebeat
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.source_gate_checkpoint import prepare as checkpoint
from tools.content_review.source_gate_run_completion import prepare
from tools.content_review.verified_inputs import load_inputs


def fixture(repo):
    value=source_fixture(repo);old=value['input']['expectedHead'];main=value['input']['expectedMain']
    state=json.loads(value['files'][old+':config/content_review_worker_status.json']['content'])
    prior=deepcopy(state['current_run']);now=(datetime.fromtimestamp(value['now']/1000,timezone.utc)+timedelta(seconds=1)).replace(microsecond=0)
    started=now.isoformat();state['run_history']=[prior];state['lease_history']=[]
    state['lease']={'owner':'worker','run_id':'run2','acquired_at':started,'expires_at':(now+timedelta(minutes=20)).isoformat()}
    state['current_run']={'run_id':'run2','application_status':'running','started_at':started,'scheduled_for':started,'observed_at':started,
        'scheduler':{'id':'Automation_worker','is_enabled':True,'observed_at':started,
                     'last_run':{'id':'run2','recorded_status':'in_progress','started_at':started,'scheduled_for':started}},
        'request_counts':{'source':0,'paid':0,'openalex':0}}
    state['source_attempts']={};state['source_last_progress']={}
    put(repo,'config/content_review_worker_status.json',state)
    put(repo,'config/content_review_monitor_config.json',{'target_automation_id':'Automation_worker','heartbeat_ref':'codex/content-review-heartbeat'})
    git(repo,'add','.');git(repo,'commit','-qm','new native run');review=git(repo,'rev-parse','HEAD')
    # The helper supplies a run-bound detached heartbeat.
    from tools.content_review.heartbeat_evidence import prepare as heartbeat
    branch=git(repo,'symbolic-ref','--short','HEAD');beat=heartbeat(state,review,'worker','run2',at=now)
    git(repo,'checkout','-qb','completion-heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    inputs=load_inputs(repo,review,main);row=inputs['manifests']['weekly']['records'][0]
    proposal=checkpoint(repo,value['snapshot'],deepcopy(value['snapshot']),inputs,inputs['lifecycle'],state,'worker','run2','weekly',row['candidate_id'],'access',
        observed_heads={'review':review,'main':main},source_attempts={},source_progress={},at=now,heartbeat=beat)
    for path,content in proposal['files'].items():put(repo,path,content)
    git(repo,'add','.');git(repo,'commit','-qm','source gate');review=git(repo,'rev-parse','HEAD')
    state=json.loads((repo/'config/content_review_worker_status.json').read_text());beat=heartbeat(state,review,'worker','run2',at=now)
    git(repo,'checkout','-q','completion-heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','rebound heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    schedule='BEGIN:VEVENT\nDTSTART:'+now.strftime('%Y%m%dT%H%M%SZ')+'\nRRULE:FREQ=HOURLY\nEND:VEVENT'
    native={'automations':[{'id':'Automation_worker','is_enabled':True,'schedule':schedule,
        'run_details':{'last_run':{'id':'run2','recorded_status':'in_progress','started_at':started,'scheduled_for':started}}}]}
    path=proposal['new_paths_must_be_absent'][0]
    return now,review,main,hb,native,value['snapshot'],path


def call(repo,values,**changes):
    now,review,main,hb,native,snapshot,path=values
    return prepare(repo,review,main,hb,changes.get('native',native),snapshot,deepcopy(snapshot),'worker','run2',path,at=now)


def test_source_gate_completion_releases_with_truthful_receipt(tmp_path):
    values=fixture(tmp_path);result=call(tmp_path,values)
    assert result['status']=='prepared' and result['writes']==0 and result['native_completion_verified'] is False
    receipt=json.loads(result['files'][result['receipt_path']]);state=json.loads(result['files']['config/content_review_worker_status.json'])
    assert receipt['completed_actions'][0]['gate']=='access' and receipt['candidate_processing'] is True
    assert receipt['native_completion_verified'] is False and receipt['publication_approved'] is False and state['lease'] is None


def test_native_mismatch_and_intervening_head_fail_closed(tmp_path):
    values=fixture(tmp_path);bad=deepcopy(values[4]);bad['automations'][0]['run_details']['last_run']['recorded_status']='no_update'
    with pytest.raises(ValueError,match='in-progress'):call(tmp_path,values,native=bad)
    put(tmp_path,'unrelated.txt','changed');git(tmp_path,'add','.');git(tmp_path,'commit','-qm','intervening change')
    changed=list(values);changed[1]=git(tmp_path,'rev-parse','HEAD')
    with pytest.raises(ValueError):call(tmp_path,changed)
