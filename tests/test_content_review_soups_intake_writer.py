from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_soups_intake_guard import fixture
from tools.content_review.soups_intake_guard import prepare as guard

ROOT = Path(__file__).resolve().parents[1]


def make_request(repo):
    now, review, main, heartbeat, snapshot, proposal = fixture(repo)
    result = guard(repo, review, main, heartbeat, snapshot, deepcopy(snapshot), 'worker', 'run', proposal, at=now)
    from tools.content_review.verified_inputs import load_inputs
    inputs = load_inputs(repo, review, main)
    old = {'config/soups_review_manifest.json':inputs['manifests']['soups'],
           'config/content_review_candidate_lifecycle.json':inputs['lifecycle'],
           'config/content_review_preflight_status.json':inputs['preflight_status'],
           'config/content_review_lifecycle_policy.json':inputs['lifecycle_policy']}
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'old':old,
            'input':{'expectedHead':review,'expectedMain':main,'owner':'worker','runId':'run','files':result['bundle']['files']}}


def invoke(value, mode):
    code="""import crypto from 'node:crypto';
import {writeIntake} from './tools/content_review/soups_intake_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,phase='idle',commits=0,blobs=0,events=[],clockOffset=0,pulses=0;
const committed='d'.repeat(40),tree='c'.repeat(40);
const api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:head}}),
 fetchFile:async({path})=>Object.hasOwn(v.old,path)?(()=>{const content=JSON.stringify(v.old[path]);return ok({sha:hash(content),content})})():
  ({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
 fetchCommitDetails:async()=>ok({sha:v.input.expectedHead,tree_sha:'b'.repeat(40),parents:[]}),
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)});},createTree:async()=>{if(mode==='expired')clockOffset=181000;return ok({sha:tree})},
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');head=committed;return ok({success:true,sha:committed})}}
const control=async({input})=>{events.push(input.action);
 if(input.action==='acquire'){if(mode==='busy')return {status:'not_changed'};phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){if(phase==='preparing')phase='idle';return {status:'aborted'}}
 if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:committed}}};
const read=async({heartbeat})=>{if(mode==='slow'){clockOffset=45000;await heartbeat()}return {snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false}};
if(mode==='tampered'){
 const p='config/soups_review_manifest.json',m=JSON.parse(v.input.files[p]);m.records[0].decision='approved';v.input.files[p]=JSON.stringify(m);
}
const verify=async()=>{if(mode==='unverified')throw Error('Worker lease unavailable')};
try{const result=await writeIntake({db:{},github:api,input:v.input,now:()=>v.now+clockOffset,read,control,verify,heartbeatFactory:()=>async()=>{pulses++}});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events,pulses}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events,pulses}));} 
"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,
        input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_intake_writer_validates_then_fences_and_confirms_exact_commit(tmp_path):
    result=invoke(make_request(tmp_path),'success')
    assert result['result']['status']=='committed_and_read_back'
    assert result['result']['candidate_processing'] is False and result['result']['publication_verified'] is False
    assert result['events']==['acquire','begin','release'] and result['commits']==1 and result['phase']=='idle'


@pytest.mark.parametrize('mode', ['tampered','unverified','busy','changed','ambiguous'])
def test_intake_writer_fails_closed_before_or_after_the_commit_boundary(tmp_path,mode):
    result=invoke(make_request(tmp_path),mode)
    assert 'error' in result
    if mode=='tampered': assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='unverified': assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='busy': assert result['commits']==0 and result['phase']=='idle'
    if mode=='changed': assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous': assert result['commits']==1 and result['phase']=='committing' and 'abort' not in result['events']


def test_intake_renews_heartbeat_during_slow_snapshot_and_rejects_expired_proposal(tmp_path):
    value=make_request(tmp_path)
    slow=invoke(value,'slow')
    assert slow['result']['status']=='committed_and_read_back' and slow['pulses'] >= 2
    expired=invoke(value,'expired')
    assert 'expired' in expired['error'].lower() and expired['commits']==0 and expired['events']==[]
