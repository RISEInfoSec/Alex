import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_run_completion import call, fixture
from tests.test_content_review_site_checkpoint_readback import data as readback_data

ROOT=Path(__file__).resolve().parents[1]


def request(repo):
    fixture_data=fixture(repo);value=readback_data(repo,fixture_data);proposal=call(repo,fixture_data)
    value['input'].update({'checkpointCommits':{value['path']:value['checkpointCommit']},'files':proposal['files']})
    value['now']=int((fixture_data[0].timestamp()+10)*1000)
    return value


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeCompletion} from './tools/content_review/site_run_complete_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const sha256=s=>crypto.createHash('sha256').update(s).digest('hex'),ok=x=>({isError:false,structuredContent:x});
let head=v.input.expectedHead,phase='idle',commits=0,blobWrites=0,trees=0,events=[];const commit='d'.repeat(40),tree='c'.repeat(40);
const api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:head}}),
 fetchCommitDetails:async({commit_sha})=>{if(commit_sha===v.input.expectedHead)return ok({sha:commit_sha,tree_sha:v.tree,parents:[v.source]});
  if(commit_sha===v.source)return ok({sha:commit_sha,tree_sha:v.baseTree,parents:[]});return {isError:true}},
 fetchFile:async({path,ref})=>{const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 streamBlob:async({sha,onChunk})=>{const data=v.blobs[sha];if(data===undefined)return {isError:true};const bytes=Buffer.from(data);
  for(let i=0;i<bytes.length;i+=7)await onChunk(bytes.subarray(i,i+7));return ok({sha,size:bytes.length,sha256:sha256(bytes)})},
 createBlob:async({content})=>{blobWrites++;return ok({sha:hash(content)})},
 createTree:async({tree_elements})=>{trees++;return ok({sha:tree_elements.length===5?(mode==='tree'?'f'.repeat(40):v.tree):tree})},
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');head=commit;return ok({success:true,sha:commit})}};
const control=async({input})=>{events.push(input.action);if(input.action==='acquire'){phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){phase='idle';return {status:'aborted'}}
 if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:commit}}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
const verify=async()=>{},heartbeatFactory=()=>async()=>({renewed:false});
try{const result=await writeCompletion({db:{},github:api,input:v.input,now:()=>v.now,read,control,verify,heartbeatFactory});
 process.stdout.write(JSON.stringify({result,commits,blobWrites,trees,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobWrites,trees,phase,events}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_completion_reaudits_real_checkpoint_before_atomic_release(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['candidate_processing'] is True and result['result']['native_completion_verified'] is False
    assert result['events']==['acquire','begin','release'] and result['commits']==1


@pytest.mark.parametrize('mode',['tree','changed','ambiguous'])
def test_completion_does_not_hide_unrelated_changes_or_ambiguous_writes(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode=='tree':assert result['commits']==0 and result['blobWrites']==0 and result['events']==[]
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
