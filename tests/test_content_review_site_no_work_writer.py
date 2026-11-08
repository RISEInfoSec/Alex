from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_run_completion import fixture, call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def setup(repo):
    data=fixture(repo,with_checkpoint=False);result=call(repo,data)
    before=json.loads(git(repo,'show',data[1]+':config/content_review_worker_status.json'))
    return {'now':int((data[0]+timedelta(seconds=10)).timestamp()*1000),'before':before,'snapshot':data[5],
      'input':{'expectedHead':data[1],'expectedMain':data[2],'owner':'worker','runId':'run','files':result['files']}}


def invoke(value,mode):
    code="""import crypto from 'node:crypto';import {writeNoWork} from './tools/content_review/site_no_work_writer.mjs';
let text='';for await(const part of process.stdin)text+=part;const v=JSON.parse(text),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,phase='idle',commits=0,blobs=0,events=[],clock=v.now,pulses=0;
const commit='d'.repeat(40),tree='c'.repeat(40);
const api={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:head}}),
 fetchFile:async({path})=>path==='config/content_review_worker_status.json'?(()=>{const content=JSON.stringify(v.before);return ok({sha:hash(content),content})})():
  ({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
 fetchCommitDetails:async()=>ok({sha:v.input.expectedHead,tree_sha:'b'.repeat(40),parents:[]}),
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)})},createTree:async()=>ok({sha:tree}),
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');head=commit;return ok({success:true,sha:commit})}};
const control=async({input})=>{events.push(input.action);
 if(input.action==='acquire'){phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){if(phase==='preparing')phase='idle';return {status:'aborted'}}
 if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:commit}}};
const read=async({heartbeat})=>{if(mode==='long'||mode==='expired'){clock+=mode==='long'?45000:181000;await heartbeat();}
 return {snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false}};
const verify=async()=>{};
if(mode==='tampered'){const p='config/content_review_worker_status.json',s=JSON.parse(v.input.files[p]);s.source_attempts={lost:true};v.input.files[p]=JSON.stringify(s)}
try{const result=await writeNoWork({db:{},github:api,input:v.input,now:()=>clock,read,control,verify,heartbeatFactory:()=>async()=>{pulses++;return {renewed:false}}});process.stdout.write(JSON.stringify({result,commits,blobs,phase,events,pulses}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events,pulses}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_no_work_writer_releases_only_after_fenced_commit_readback(tmp_path):
    result=invoke(setup(tmp_path),'success')
    assert result['result']['status']=='committed_and_read_back' and result['result']['candidate_processing'] is False
    assert result['result']['native_completion_verified'] is False and result['events']==['acquire','begin','release']


def test_long_snapshot_renews_heartbeat_but_expired_proposal_cannot_commit(tmp_path):
    value=setup(tmp_path)
    slow=invoke(value,'long')
    assert slow['result']['candidate_processing'] is False and slow['commits']==1 and slow['pulses']>=2
    expired=invoke(value,'expired')
    assert 'expired' in expired['error'].lower() and expired['commits']==0 and expired['events']==[]


@pytest.mark.parametrize('mode',['tampered','changed','ambiguous'])
def test_no_work_writer_rejects_tampering_and_keeps_ambiguous_fence(tmp_path,mode):
    result=invoke(setup(tmp_path),mode)
    assert 'error' in result
    if mode=='tampered':assert result['blobs']==0 and result['commits']==0
    if mode=='changed':assert result['commits']==0 and result['phase']=='idle' and result['events']==['acquire','begin','abort']
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing' and 'abort' not in result['events']
