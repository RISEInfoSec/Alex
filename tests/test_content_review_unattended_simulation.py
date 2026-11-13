"""Synthetic integration only: no native scheduler, live D1 or provider calls."""
from copy import deepcopy
from datetime import timedelta
import json
import subprocess

from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_verified_inputs import git, put, fixture as input_fixture
from tools.content_review.checkpoint_guard import verify
from tools.content_review.duplicate_checkpoint import prepare as prepare_checkpoint
from tools.content_review.lease_transition import prepare as prepare_lease
from tools.content_review.monitor_snapshot import prepare as prepare_monitor
from tools.content_review.verified_inputs import load_inputs


def commit_files(repo, parent, files, message):
    for name,content in files.items():put(repo,name,content)
    git(repo,'add',*files)
    tree=git(repo,'write-tree')
    commit=git(repo,'commit-tree',tree,'-p',parent,'-m',message)
    branch=git(repo,'symbolic-ref','HEAD')
    git(repo,'update-ref',branch,commit,parent)
    return commit


def test_local_native_lease_checkpoint_conflict_and_independent_monitor(tmp_path):
    now,snapshot,inputs,state,ledger=setup_bundle()
    state['lease']=None;state['current_run']={'run_id':'old','application_status':'complete','receipt':'retained'}
    inputs['worker_state']=deepcopy(state)
    worker_id='Automation_worker1';monitor_id='Automation_monitor1'
    config={'target_automation_id':worker_id,'automation_id':monitor_id}
    path_objects={'config/weekly_review_manifest.json':inputs['manifests']['weekly'],
                  'config/content_review_candidate_lifecycle.json':ledger,
                  'config/content_review_preflight_status.json':inputs['preflight_status'],
                  'config/content_review_worker_status.json':state}
    _, main, _ = input_fixture(tmp_path)
    for path,value in path_objects.items():put(tmp_path,path,value)
    put(tmp_path,'config/content_review_lifecycle_policy.json',inputs['lifecycle_policy'])
    put(tmp_path,'config/content_review_monitor_config.json',config)
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','fixture')
    head=git(tmp_path,'rev-parse','HEAD')
    scheduler={'id':worker_id,'is_enabled':True,
        'schedule':'BEGIN:VEVENT\nDTSTART:20261106T200000Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
        'run_details':{'last_run':{'id':'run','recorded_status':'in_progress',
            'scheduled_for':now.isoformat(),'started_at':now.isoformat()}}}
    lease=prepare_lease(tmp_path,head,scheduler,'worker','run','start',at=now)
    lease_head=commit_files(tmp_path,head,{lease['path']:lease['content']},'synthetic lease')
    leased=json.loads(lease['content'])
    assert leased['run_history'][0]['receipt']=='retained'
    inputs=load_inputs(tmp_path,lease_head,main)
    bundle=prepare_checkpoint(snapshot,deepcopy(snapshot),inputs,ledger,leased,'worker','run','weekly','fresh',
        observed_heads={'review':lease_head,'main':inputs['main_commit']},source_attempts={},source_progress={},at=now+timedelta(seconds=5))
    proof=verify(tmp_path,lease_head,inputs['main_commit'],bundle)
    assert proof['writes']==0 and proof['requires_remote_head_d1_and_lease_recheck']
    checkpoint_head=commit_files(tmp_path,lease_head,bundle['files'],'synthetic checkpoint')
    branch=git(tmp_path,'symbolic-ref','HEAD')
    conflict=subprocess.run(['git','-C',str(tmp_path),'update-ref',branch,head,lease_head],capture_output=True,check=False)
    assert conflict.returncode!=0 and git(tmp_path,'rev-parse','HEAD')==checkpoint_head
    manifest=json.loads(git(tmp_path,'show',checkpoint_head+':config/weekly_review_manifest.json'))
    assert manifest['records'][0]['decision']=='pending'
    observer={'id':monitor_id,'is_enabled':True,
        'schedule':'BEGIN:VEVENT\nDTSTART:20261106T200000Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
        'run_details':{'last_run':{'id':'monitor-run','recorded_status':'in_progress',
            'scheduled_for':now.isoformat(),'started_at':now.isoformat()}}}
    scheduler['run_details']['last_run'].update(recorded_status='no_update',completed_at=(now+timedelta(seconds=8)).isoformat())
    reported=prepare_monitor(config,scheduler,observer,leased,None,at=now+timedelta(seconds=10))
    assert reported['receipt_check']['verified'] is False
    assert reported['processing'] is None
