from copy import deepcopy
import json,subprocess
from pathlib import Path

import pytest
from tests.test_content_review_source_retention_run_completion import fixture,call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def request(repo,result_status='retrieved'):
    data=fixture(repo,result_status);proposal=call(repo,data);receipt=json.loads(proposal['files'][proposal['receipt_path']])
    return {'now':int((data[0].timestamp()+10)*1000),'snapshot':data[5],
            'before':json.loads(git(repo,'show',data[1]+':config/content_review_worker_status.json')),
            'action':deepcopy(receipt['completed_actions'][0]),
            'input':{'expectedHead':data[1],'expectedMain':data[2],'owner':'worker','runId':'run2',
                     'checkpointCommit':data[1],'files':proposal['files']}}


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeSourceRetentionCompletion} from './tools/content_review/site_source_retention_completion_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,phase='idle',commits=0,blobs=0,events=[];
const committed='d'.repeat(40),tree='c'.repeat(40),api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:head}}),
 fetchFile:async({path})=>path==='config/content_review_worker_status.json'?(()=>{const content=JSON.stringify(v.before);return ok({sha:hash(content),content})})():
  ({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
 fetchCommitDetails:async()=>ok({sha:v.input.expectedHead,tree_sha:'b'.repeat(40),parents:[]}),
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)})},createTree:async()=>ok({sha:tree}),
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');head=committed;return ok({success:true,sha:committed})}};
const control=async({input})=>{events.push(input.action);
 if(input.action==='acquire'){if(mode==='busy')return {status:'not_changed'};phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){phase='idle';return {status:'aborted'}}
 if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:committed}}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
const verify=async()=>{if(mode==='unverified')throw Error('Worker lease unavailable')};
const check=async()=>{if(mode==='bad_checkpoint')throw Error('Checkpoint evidence invalid');return v.action};
const heartbeatFactory=()=>async()=>({renewed:false});
if(mode==='false_receipt'){const p='config/content_review_run_receipts/run2.json',r=JSON.parse(v.input.files[p]);
 r.native_completion_verified=true;v.input.files[p]=JSON.stringify(r)}
try{const result=await writeSourceRetentionCompletion({db:{},github:api,getToken:()=>'',input:v.input,now:()=>v.now,read,control,verify,check,heartbeatFactory});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_source_retention_completion_releases_only_verified_checkpoint(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['candidate_processing'] is True and result['result']['native_completion_verified'] is False
    assert result['events']==['acquire','begin','release']


def test_source_hold_completion_uses_same_fence_and_does_not_claim_processing(tmp_path):
    result=invoke(request(tmp_path,'held'),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['candidate_processing'] is False and result['result']['native_completion_verified'] is False
    assert result['events']==['acquire','begin','release']


@pytest.mark.parametrize('mode',['unverified','bad_checkpoint','false_receipt','busy','changed','ambiguous'])
def test_source_retention_completion_fails_closed_across_fence(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode in ('unverified','bad_checkpoint','false_receipt'):assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='busy':assert result['commits']==0 and result['phase']=='idle'
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing' and 'abort' not in result['events']
