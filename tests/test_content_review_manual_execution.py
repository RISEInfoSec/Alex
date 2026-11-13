"""Manual runs require a committed one-use permit and never claim a native run."""
from copy import deepcopy
from datetime import timedelta
import json
import subprocess

import pytest

from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_unattended_simulation import commit_files
from tests.test_content_review_verified_inputs import fixture as input_fixture, git, put
from tools.content_review.duplicate_checkpoint import prepare as checkpoint
from tools.content_review.heartbeat_evidence import prepare as heartbeat
from tools.content_review.lease_transition import prepare_manual
from tools.content_review.run_completion import prepare as complete
from tools.content_review.verified_inputs import load_inputs


def node(module,method,value):
    code="const m=require('./tools/content_review/'+process.argv[1]);let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{try{const x=JSON.parse(s);process.stdout.write(JSON.stringify(m[process.argv[2]](...x)))}catch(e){process.stderr.write(e.message);process.exitCode=1}})"
    return subprocess.run(['node','-e',code,module,method],input=json.dumps(value),text=True,capture_output=True)


def fixture(repo, *, with_checkpoint=True):
    now,snapshot,inputs,state,ledger=setup_bundle();state['lease']=None
    previous={'run_id':'old','application_status':'complete','receipt':'preserved'};state['current_run']=previous
    _,main,_=input_fixture(repo)
    permit={'run_id':'manual-1','owner':'worker','scope':'duplicate_only','expires_at':(now+timedelta(minutes=14)).isoformat()}
    config={'target_automation_id':'Automation_worker1','manual_run_authorization':permit}
    for path,value in {'config/weekly_review_manifest.json':inputs['manifests']['weekly'],
      'config/content_review_candidate_lifecycle.json':ledger,'config/content_review_preflight_status.json':inputs['preflight_status'],
      'config/content_review_worker_status.json':state,'config/content_review_lifecycle_policy.json':inputs['lifecycle_policy'],
      'config/content_review_monitor_config.json':config}.items():put(repo,path,value)
    git(repo,'add','.');git(repo,'commit','-qm','manual fixture');head=git(repo,'rev-parse','HEAD')
    lease=prepare_manual(repo,head,'worker','manual-1',at=now);started=json.loads(lease['content'])
    result=node('lease_semantics.cjs','validateTransition',[state,started,'start',{'owner':'worker','runId':'manual-1','now':now.timestamp()*1000}])
    assert result.returncode==0,result.stderr
    assert started['current_run']['scheduler']['kind']=='manual' and started['current_run']['scheduled_for'] is None
    assert started['run_history'][-1]==previous and started['lease']['run_id']=='manual-1'
    head=commit_files(repo,head,{lease['path']:lease['content']},'manual lease');paths=[]
    if with_checkpoint:
        current=load_inputs(repo,head,main)
        proposal=checkpoint(snapshot,deepcopy(snapshot),current,ledger,started,'worker','manual-1','weekly','fresh',
          observed_heads={'review':head,'main':main},source_attempts={},source_progress={},at=now+timedelta(seconds=5))
        head=commit_files(repo,head,proposal['files'],'manual duplicate');started=json.loads(proposal['files']['config/content_review_worker_status.json'])
        paths=proposal['new_paths_must_be_absent']
    record=heartbeat(started,head,'worker','manual-1',at=now+timedelta(seconds=10))
    branch=git(repo,'symbolic-ref','--short','HEAD');git(repo,'checkout','-qb','manual-heartbeat')
    put(repo,'config/content_review_detached_heartbeat.json',record);git(repo,'add','.');git(repo,'commit','-qm','manual heartbeat')
    hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    return now,head,main,hb,snapshot,paths,config,started


def test_manual_checkpoint_completes_with_manual_receipt_and_no_native_claim(tmp_path):
    now,head,main,hb,snapshot,paths,config,state=fixture(tmp_path)
    result=complete(tmp_path,head,main,hb,None,snapshot,deepcopy(snapshot),'worker','manual-1',paths,at=now+timedelta(seconds=10))
    receipt=json.loads(result['files'][result['new_path']]);after=json.loads(result['files']['config/content_review_worker_status.json'])
    assert receipt['trigger']=='manual' and receipt['scheduled_for'] is None and receipt['native_completion_verified'] is False
    assert receipt['completed_actions'][0]['path']==paths[0] and after['lease'] is None
    action=receipt['completed_actions'][0]
    args={'before':state,'after':after,'receipt':receipt,'owner':'worker','runId':'manual-1','verifiedAction':action,'now':(now+timedelta(seconds=10)).timestamp()*1000}
    ok=node('site_run_complete_guard.cjs','validateComplete',[args]);assert ok.returncode==0,ok.stderr
    forged=deepcopy(args);forged['receipt']['trigger']='schedule';assert node('site_run_complete_guard.cjs','validateComplete',[forged]).returncode!=0
    with pytest.raises(ValueError,match='manual authorization'):
        complete(tmp_path,head,main,hb,{'fabricated':'native'},snapshot,deepcopy(snapshot),'worker','manual-1',paths,at=now+timedelta(seconds=10))


def test_manual_empty_pass_releases_without_processing_or_schedule_claim(tmp_path):
    now,head,main,hb,snapshot,paths,config,state=fixture(tmp_path,with_checkpoint=False)
    result=complete(tmp_path,head,main,hb,None,snapshot,deepcopy(snapshot),'worker','manual-1',paths,at=now+timedelta(seconds=10))
    receipt=json.loads(result['files'][result['new_path']]);after=json.loads(result['files']['config/content_review_worker_status.json'])
    assert receipt['trigger']=='manual' and receipt['status']=='no_work' and receipt['scheduled_for'] is None and after['lease'] is None
    args={'before':state,'after':after,'receipt':receipt,'owner':'worker','runId':'manual-1','now':(now+timedelta(seconds=10)).timestamp()*1000}
    ok=node('run_no_work_guard.cjs','validateNoWork',[args]);assert ok.returncode==0,ok.stderr
    args['receipt']['trigger']='schedule';assert node('run_no_work_guard.cjs','validateNoWork',[args]).returncode!=0


@pytest.mark.parametrize('change',['missing','wrong_run','wrong_owner','expired','too_long','scope','extra'])
def test_invalid_manual_permit_never_starts_or_authorizes(tmp_path,change):
    now,head,main,hb,snapshot,paths,config,state=fixture(tmp_path,with_checkpoint=False)
    permit=config['manual_run_authorization']
    if change=='missing':config.pop('manual_run_authorization')
    if change=='wrong_run':permit['run_id']='another'
    if change=='wrong_owner':permit['owner']='other'
    if change=='expired':permit['expires_at']=(now-timedelta(seconds=1)).isoformat()
    if change=='too_long':permit['expires_at']=(now+timedelta(hours=1)).isoformat()
    if change=='scope':permit['scope']='publication'
    if change=='extra':permit['extra']=True
    checked=node('manual_authorization.cjs','authorized',[config,state['current_run'],'worker','manual-1',now.timestamp()*1000])
    assert checked.returncode==0 and json.loads(checked.stdout) is False
    put(tmp_path,'config/content_review_monitor_config.json',config);git(tmp_path,'add','.');git(tmp_path,'commit','-qm','invalid permit')
    with pytest.raises(ValueError,match='manual authorization'):
        prepare_manual(tmp_path,git(tmp_path,'rev-parse','HEAD'),'worker','manual-1',at=now)


def test_manual_authorization_is_bound_to_current_run_and_expiry(tmp_path):
    now,head,main,hb,snapshot,paths,config,state=fixture(tmp_path,with_checkpoint=False)
    valid=[config,state['current_run'],'worker','manual-1',now.timestamp()*1000]
    assert json.loads(node('manual_authorization.cjs','authorized',valid).stdout) is True
    for index,value in [(2,'other'),(3,'other'),(4,(now+timedelta(minutes=15)).timestamp()*1000)]:
        changed=deepcopy(valid);changed[index]=value
        assert json.loads(node('manual_authorization.cjs','authorized',changed).stdout) is False


def test_source_retention_lease_requires_matching_manual_scope(tmp_path):
    now,snapshot,inputs,state,ledger=setup_bundle();state['lease']=None
    state['current_run']={'run_id':'old','application_status':'complete'}
    _,main,_=input_fixture(tmp_path)
    permit={'run_id':'manual-1','owner':'worker','scope':'source_retention_only','expires_at':(now+timedelta(minutes=14)).isoformat()}
    put(tmp_path,'config/content_review_worker_status.json',state)
    put(tmp_path,'config/content_review_monitor_config.json',{'target_automation_id':'Automation_worker1','manual_run_authorization':permit})
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','source retention permit');head=git(tmp_path,'rev-parse','HEAD')
    with pytest.raises(ValueError,match='manual authorization'):
        prepare_manual(tmp_path,head,'worker','manual-1',at=now)
    proposal=prepare_manual(tmp_path,head,'worker','manual-1',at=now,scope='source_retention_only')
    started=json.loads(proposal['content'])
    assert started['current_run']['scheduler']['kind']=='manual' and started['current_run']['scheduled_for'] is None
