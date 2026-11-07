from copy import deepcopy
from datetime import timedelta
import json
import subprocess

import pytest

from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_unattended_simulation import commit_files
from tests.test_content_review_verified_inputs import fixture as input_fixture, git, put
from tools.content_review.checkpoint_guard import verify
from tools.content_review.duplicate_checkpoint import prepare as prepare_checkpoint
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.lease_transition import prepare as prepare_lease
from tools.content_review.operations import verified_completion
from tools.content_review.run_completion import prepare
from tools.content_review.verified_inputs import load_inputs
from tools.content_review.work_plan import processing_progress


def fixture(repo, *, with_checkpoint=True):
    now, snapshot, inputs, state, ledger = setup_bundle()
    state['lease']=None
    state['current_run']={'run_id':'old','application_status':'complete','receipt':'preserved'}
    worker='Automation_worker1'
    _, main, _=input_fixture(repo)
    for path, value in {
        'config/weekly_review_manifest.json':inputs['manifests']['weekly'],
        'config/content_review_candidate_lifecycle.json':ledger,
        'config/content_review_preflight_status.json':inputs['preflight_status'],
        'config/content_review_worker_status.json':state,
        'config/content_review_lifecycle_policy.json':inputs['lifecycle_policy'],
        'config/content_review_monitor_config.json':{'target_automation_id':worker},
    }.items():put(repo,path,value)
    git(repo,'add','.');git(repo,'commit','-qm','fixture')
    head=git(repo,'rev-parse','HEAD')
    native={'id':worker,'is_enabled':True,
        'schedule':'BEGIN:VEVENT\nDTSTART:20261106T200000Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
        'run_details':{'last_run':{'id':'run','recorded_status':'in_progress',
             'scheduled_for':now.isoformat(),'started_at':now.isoformat()}}}
    lease=prepare_lease(repo,head,native,'worker','run','start',at=now)
    head=commit_files(repo,head,{lease['path']:lease['content']},'lease')
    state=json.loads(lease['content']);paths=[]
    if with_checkpoint:
        inputs=load_inputs(repo,head,main)
        bundle=prepare_checkpoint(snapshot,deepcopy(snapshot),inputs,ledger,state,'worker','run','weekly','fresh',
            observed_heads={'review':head,'main':main},source_attempts={},source_progress={},at=now+timedelta(seconds=5))
        verify(repo,head,main,bundle)
        head=commit_files(repo,head,bundle['files'],'duplicate checkpoint')
        state=json.loads(bundle['files']['config/content_review_worker_status.json'])
        paths=bundle['new_paths_must_be_absent']
    branch=git(repo,'symbolic-ref','--short','HEAD')
    heartbeat=prepare_heartbeat(state,head,'worker','run',at=now+timedelta(seconds=10))
    git(repo,'checkout','-qb','heartbeat')
    put(repo,'config/content_review_detached_heartbeat.json',heartbeat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat')
    hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    return now,head,main,hb,native,snapshot,paths


def call(repo, data, *, paths=None, native=None, snapshot=None, seconds=10):
    now,head,main,hb,native0,snap,paths0=data
    return prepare(repo,head,main,hb,native if native is not None else native0,
                   snapshot if snapshot is not None else snap,deepcopy(snapshot if snapshot is not None else snap),
                   'worker','run',paths if paths is not None else paths0,at=now+timedelta(seconds=seconds))


def test_real_committed_checkpoint_yields_receipt_and_lease_release_without_native_claim(tmp_path):
    data=fixture(tmp_path);now,head,main,hb,native,snapshot,paths=data
    proposal=call(tmp_path,data)
    assert proposal['status']=='prepared' and proposal['writes']==0
    assert proposal['native_completion_verified'] is False
    assert proposal['requires_remote_head_d1_and_lease_recheck'] is True
    worker=json.loads(proposal['files']['config/content_review_worker_status.json'])
    receipt=json.loads(proposal['files'][proposal['new_path']])
    assert worker['lease'] is None and worker['lease_history'][-1]['status']=='released'
    assert worker['run_history'][0]['receipt']=='preserved'
    assert receipt['status']=='complete' and len(receipt['completed_actions'])==1
    assert receipt['completed_actions'][0]['path']==paths[0]
    assert receipt['native_completion_verified'] is False and receipt['publication_approved'] is False
    assert receipt['pilot']['newly_passed_checks']['duplicates']==['fresh']
    assert processing_progress([receipt,receipt])['status']=='stalled_local_only'
    assert proposal['d1_fingerprint_private'] not in json.dumps(proposal['files'])
    finished=commit_files(tmp_path,head,proposal['files'],'run receipt')
    assert json.loads(git(tmp_path,'show',finished+':'+proposal['new_path']))==receipt
    native['run_details']['last_run'].update(recorded_status='completed',completed_at=(now+timedelta(seconds=12)).isoformat())
    assert verified_completion(native,receipt)['evidence_verified'] is True


def test_empty_pass_is_deferred_and_never_verifies_as_completed_work(tmp_path):
    data=fixture(tmp_path,with_checkpoint=False)
    result=call(tmp_path,data)
    receipt=json.loads(result['files'][result['new_path']])
    worker=json.loads(result['files']['config/content_review_worker_status.json'])
    assert receipt['status']=='no_work' and receipt['completed_actions']==[]
    assert worker['current_run']['application_status']=='deferred' and worker['lease'] is None
    native=deepcopy(data[4]);native['run_details']['last_run'].update(recorded_status='completed',completed_at=(data[0]+timedelta(seconds=12)).isoformat())
    assert verified_completion(native,receipt) is None


def test_native_action_and_stale_heartbeat_fail_closed(tmp_path):
    data=fixture(tmp_path)
    native=deepcopy(data[4]);native['run_details']['latest_result']={'run_id':'run','requires_user_action':True}
    with pytest.raises(ValueError,match='native run'):
        call(tmp_path,data,native=native)
    with pytest.raises(ValueError,match='heartbeat is stale'):
        call(tmp_path,data,seconds=51)


def test_unverified_or_duplicate_checkpoint_cannot_complete(tmp_path):
    data=fixture(tmp_path)
    with pytest.raises(ValueError,match='distinct mechanical checkpoints'):
        call(tmp_path,data,paths=data[6]*2)
    with pytest.raises(ValueError,match='Required committed input is missing'):
        call(tmp_path,data,paths=['config/content_review_mechanical_checkpoints/'+'a'*64+'.json'])


def test_incomplete_or_changed_private_snapshot_stops_completion(tmp_path):
    data=fixture(tmp_path);snapshot=deepcopy(data[5])
    snapshot['read_evidence']['decisions']['complete']=False
    with pytest.raises(ValueError,match='Incomplete decisions'):
        call(tmp_path,data,snapshot=snapshot)


def test_new_review_decision_stops_completion_for_that_candidate(tmp_path):
    data=fixture(tmp_path);snapshot=deepcopy(data[5])
    manifest=json.loads(git(tmp_path,'show',data[1]+':config/weekly_review_manifest.json'))
    row=manifest['records'][0]
    snapshot['submissions']=[{'id':'submission','user_id':'private-owner','collection':'weekly',
      'batch':1,'revision':1,'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    snapshot['decisions']=[{'id':'decision','submission_id':'submission','user_id':'private-owner',
      'collection':'weekly','batch':1,'revision':1,'candidate_id':row['candidate_id'],
      'review_number':row['review_number'],'content_sha256':row['content_sha256'],'decision':'rejected'}]
    for k in ('submissions','decisions'):snapshot['read_evidence'][k]['rows_received']=1
    with pytest.raises(ValueError,match='reviewed or held candidate'):
        call(tmp_path,data,snapshot=snapshot)


def test_python_completion_bundle_is_accepted_by_atomic_javascript_writer(tmp_path):
    data=fixture(tmp_path);proposal=call(tmp_path,data)
    evidence={path:json.loads(git(tmp_path,'show',data[1]+':'+path)) for path in data[6]}
    script=r"""
const {commitCheckpoint}=require('./tools/content_review/github_atomic_checkpoint.cjs');
const crypto=require('node:crypto');let raw='';process.stdin.setEncoding('utf8');
process.stdin.on('data',x=>raw+=x);process.stdin.on('end',async()=>{
 const {proposal:p,evidence}=JSON.parse(raw), old=p.expected_head, worker='config/content_review_worker_status.json';
 const ok=x=>({isError:false,structuredContent:x}),hash=x=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(x)}\0`).update(x).digest('hex');
 let head=old,treeEntries=[],saved={};const commit='d'.repeat(40),tree=p.expected_tree;
 const api={fetchCommit:async()=>ok({commit:{sha:head}}),
  fetchFile:async({path,ref})=>{
   if(ref===old&&path===worker)return ok({sha:p.base_blobs[worker].blob_sha,content:JSON.stringify(p.fence_state)});
   if(ref===old&&evidence[path])return ok({sha:'e'.repeat(40),content:JSON.stringify(evidence[path])});
   if(ref===commit&&saved[path])return ok({sha:saved[path]});
   return {isError:true,structuredContent:{error_code:'NOT_FOUND'}};
  },createBlob:async({content})=>ok({sha:hash(content)}),
  createTree:async({tree_elements})=>{treeEntries=tree_elements;return ok({sha:tree})},
  createCommit:async()=>{saved=Object.fromEntries(treeEntries.map(x=>[x.path,x.sha]));return ok({sha:commit})},
  updateRef:async({expected_sha,sha,force})=>{if(head!==expected_sha||force!==false)throw Error('bad CAS');head=sha;return ok({success:true})}};
 const receipt=JSON.parse(p.files[p.new_path]),lease=p.fence_state.lease;
 const fence=async()=>({verified:true,expectedHead:old,main_head:p.expected_main,d1_fingerprint_private:p.d1_fingerprint_private,
  lease_owner:p.lease_owner,run_id:p.run_id,checked_at:receipt.completed_at,heartbeat_at:receipt.completed_at,
  lease_expires_at:lease.expires_at,started_at:receipt.started_at});
 try{const result=await commitCheckpoint({api,linkId:'test',bundle:p,proof:p,fence,now:()=>Date.parse(receipt.completed_at)});
  if(result.commit_sha!==commit||head!==commit)throw Error('bad readback');process.stdout.write('verified');
 }catch(e){process.stderr.write(e.message);process.exitCode=1;}
});
"""
    result=subprocess.run(['node','-e',script],input=json.dumps({'proposal':proposal,'evidence':evidence}),
                          text=True,capture_output=True,check=False)
    assert result.returncode==0, result.stderr
    assert result.stdout=='verified'
