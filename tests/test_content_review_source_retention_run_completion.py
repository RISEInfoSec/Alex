from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json

import pytest
from tests.test_content_review_site_source_retention_writer import request as source_fixture
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as heartbeat
from tools.content_review.source_retention import prepare as retain
from tools.content_review.source_retention_checkpoint import prepare as checkpoint
from tools.content_review.source_retention_run_completion import prepare


def fixture(repo, result_status='retrieved', manual=False, permit_scope='source_retention_only', permit_seconds=600):
    value=source_fixture(repo,result_status);old=value['input']['expectedHead'];main=value['input']['expectedMain']
    state=json.loads(value['files'][old+':config/content_review_worker_status.json']['content'])
    prior=deepcopy(state['current_run']);now=(datetime.fromtimestamp(value['now']/1000,timezone.utc)+timedelta(seconds=1)).replace(microsecond=0)
    started=now.isoformat();state['run_history']=[prior];state['lease_history']=[]
    state['lease']={'owner':'worker','run_id':'run2','acquired_at':started,'expires_at':(now+timedelta(minutes=20)).isoformat()}
    state['current_run']={'run_id':'run2','application_status':'running','started_at':started,'scheduled_for':started,'observed_at':started,
        'scheduler':{'id':'Automation_worker','is_enabled':True,'observed_at':started,
         'last_run':{'id':'run2','recorded_status':'in_progress','started_at':started,'scheduled_for':started}},
        'request_counts':{'source':0,'paid':0,'openalex':0}}
    config={'target_automation_id':'Automation_worker','heartbeat_ref':'codex/content-review-heartbeat'}
    if manual:
        state['current_run']['scheduled_for']=None
        state['current_run']['scheduler']={'id':'Automation_worker','kind':'manual','authorization':'owner_request','observed_at':started}
        config['manual_run_authorization']={'owner':'worker','run_id':'run2','scope':permit_scope,'expires_at':(now+timedelta(seconds=permit_seconds)).isoformat()}
    put(repo,'config/content_review_worker_status.json',state)
    put(repo,'config/content_review_monitor_config.json',config)
    git(repo,'add','.');git(repo,'commit','-qm','new native run');review=git(repo,'rev-parse','HEAD')
    branch=git(repo,'symbolic-ref','--short','HEAD');beat=heartbeat(state,review,'worker','run2',at=now)
    git(repo,'checkout','-qb','retention-completion-heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    source_path=next(k.split(':',1)[1] for k in value['files'] if ':config/content_review_source_requests/' in k)
    source=json.loads(git(repo,'show',review+':'+source_path));item=source['records'][0];observed=value['observed']
    args=(repo,review,main,hb,value['snapshot'],deepcopy(value['snapshot']),source['request_id'],observed['result_text'].encode(),
          observed['native_run'],observed['artifact'],item['collection'],item['candidate_id'],'worker','run2')
    proposal=retain(*args,observed_heads={'review':review,'main':main},at=now)
    bundle=checkpoint(*args,proposal,observed_heads={'review':review,'main':main},at=now)
    for path,content in bundle['bundle']['files'].items():put(repo,path,content)
    git(repo,'add','.');git(repo,'commit','-qm','source retention');review=git(repo,'rev-parse','HEAD')
    state=json.loads((repo/'config/content_review_worker_status.json').read_text());beat=heartbeat(state,review,'worker','run2',at=now)
    git(repo,'checkout','-q','retention-completion-heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','rebound heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    schedule='BEGIN:VEVENT\nDTSTART:'+now.strftime('%Y%m%dT%H%M%SZ')+'\nRRULE:FREQ=HOURLY\nEND:VEVENT'
    native={'automations':[{'id':'Automation_worker','is_enabled':True,'schedule':schedule,
        'run_details':{'last_run':{'id':'run2','recorded_status':'in_progress','started_at':started,'scheduled_for':started}}}]}
    if manual:native=None
    return now,review,main,hb,native,value['snapshot'],bundle['proof']['new_path']


def call(repo,values,**changes):
    now,review,main,hb,native,snapshot,path=values
    return prepare(repo,review,main,hb,changes.get('native',native),snapshot,deepcopy(snapshot),'worker','run2',path,at=now)


def test_retention_completion_releases_with_truthful_receipt(tmp_path):
    values=fixture(tmp_path);result=call(tmp_path,values)
    receipt=json.loads(result['files'][result['receipt_path']]);state=json.loads(result['files']['config/content_review_worker_status.json'])
    assert receipt['kind']=='source_retention_completion' and receipt['completed_actions'][0]['action']=='source_evidence_retained'
    assert receipt['candidate_processing'] is True and receipt['native_completion_verified'] is False
    assert receipt['publication_approved'] is False and state['lease'] is None


def test_held_source_completion_preserves_hold_and_defers_without_gate_claim(tmp_path):
    values=fixture(tmp_path,'held');result=call(tmp_path,values)
    receipt=json.loads(result['files'][result['receipt_path']]);state=json.loads(result['files']['config/content_review_worker_status.json'])
    assert receipt['status']=='deferred' and receipt['completed_actions'][0]['action']=='source_hold_retained'
    assert receipt['candidate_processing'] is False and receipt['native_completion_verified'] is False
    assert receipt['publication_approved'] is False and state['lease'] is None and state['current_run']['application_status']=='deferred'


def test_retention_completion_rejects_no_update_and_intervening_commit(tmp_path):
    values=fixture(tmp_path);bad=deepcopy(values[4]);bad['automations'][0]['run_details']['last_run']['recorded_status']='no_update'
    with pytest.raises(ValueError,match='in-progress'):call(tmp_path,values,native=bad)
    put(tmp_path,'unrelated.txt','changed');git(tmp_path,'add','.');git(tmp_path,'commit','-qm','intervening change')
    changed=list(values);changed[1]=git(tmp_path,'rev-parse','HEAD')
    with pytest.raises(ValueError):call(tmp_path,changed)


def test_private_review_decision_blocks_retention_completion(tmp_path):
    values=list(fixture(tmp_path));snapshot=deepcopy(values[5]);receipt=json.loads(git(tmp_path,'show',values[1]+':'+values[6]))
    snapshot['submissions']=[{'id':'s','user_id':'owner','collection':receipt['collection'],'batch':1,'revision':1,
                              'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    snapshot['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':receipt['collection'],'batch':1,
                            'revision':1,'candidate_id':receipt['candidate_id'],'review_number':1,
                            'content_sha256':receipt['content_sha256'],'decision':'rejected'}]
    for key in ('submissions','decisions'):snapshot['read_evidence'][key]['rows_received']=len(snapshot[key])
    values[5]=snapshot
    with pytest.raises(ValueError,match='Reviewed candidate requires reconciliation'):call(tmp_path,values)


def test_manual_retention_completion_reports_manual_without_native_claim(tmp_path):
    values=fixture(tmp_path,manual=True);result=call(tmp_path,values)
    receipt=json.loads(result['files'][result['receipt_path']])
    assert receipt['trigger']=='manual' and receipt['scheduled_for'] is None
    assert receipt['native_completion_verified'] is False and receipt['publication_approved'] is False
    with pytest.raises(ValueError,match='manual source retention authorization'):
        call(tmp_path,values,native={'fabricated':'native'})


@pytest.mark.parametrize('scope,seconds',[('duplicate_only',600),('publication',600),('source_retention_only',-1),('source_retention_only',901)])
def test_manual_retention_completion_requires_exact_fresh_scope(tmp_path,scope,seconds):
    values=fixture(tmp_path,manual=True,permit_scope=scope,permit_seconds=seconds)
    with pytest.raises(ValueError,match='manual source retention authorization'):call(tmp_path,values)
