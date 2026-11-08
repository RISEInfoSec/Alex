import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_site_source_result_writer import request
ROOT=Path(__file__).resolve().parents[1]


def invoke(value,mode):
    code=r"""import {discoverSourceWorkflow} from './tools/content_review/site_source_discovery_service.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode,ok=x=>({isError:false,structuredContent:x});
const input={expectedHead:v.input.expectedHead,expectedMain:v.input.expectedMain,reservationHead:v.input.expectedHead,owner:'worker',runId:'run'};
let gets=0,verified=0;const api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?input.expectedMain:input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>commit_sha===input.expectedHead?ok({sha:commit_sha,parents:[v.source]}):({isError:true}),
 fetchFile:async({path,ref})=>{const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})}};
const run={...v.observed.native_run,repository:{full_name:'RISEInfoSec/Alex'},head_repository:{full_name:'RISEInfoSec/Alex'}};
const artifact={id:v.input.artifactId,name:'content-review-source-'+run.id+'-'+run.run_attempt,expired:false,
 size_in_bytes:100,digest:'sha256:'+'a'.repeat(64),workflow_run:{id:run.id}};
const fetcher=async(url,options)=>{gets++;if(!url.startsWith('https://api.github.com/repos/RISEInfoSec/Alex/'))throw Error('destination');
 if(options.headers.Authorization!=='Bearer secret'||options.redirect!=='manual')throw Error('authentication');
 if(mode==='http')return new Response('',{status:429});
 if(url.includes('/workflows/')){
  if(!url.includes('head_sha='+input.reservationHead))throw Error('head not bound');
  if(mode==='none')return Response.json({total_count:0,workflow_runs:[]});
  if(mode==='queued')return Response.json({total_count:1,workflow_runs:[{...run,status:'in_progress',conclusion:null}]});
  if(mode==='failed')return Response.json({total_count:1,workflow_runs:[{...run,conclusion:'failure'}]});
  if(mode==='ambiguous')return Response.json({total_count:2,workflow_runs:[run,{...run,id:run.id+1}]});
  return Response.json({total_count:1,workflow_runs:[run]});}
 if(mode==='no_artifact')return Response.json({total_count:0,artifacts:[]});
 return Response.json({total_count:1,artifacts:[artifact]});};
const verify=async()=>{verified++;if(mode==='unverified')throw Error('worker not verified')};
try{const result=await discoverSourceWorkflow({github:api,getToken:()=> 'secret',input,now:()=>v.now,fetcher,verify,heartbeatFactory:()=>async()=>({renewed:false})});
 process.stdout.write(JSON.stringify({result,gets,verified}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,gets,verified}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_discovery_binds_native_run_and_artifact_without_claiming_processing(tmp_path):
    result=invoke(request(tmp_path),'ready')
    assert result.get('result',{}).get('status')=='source_artifact_ready',result
    assert result['result']['source_workflow_verified'] is False and result['result']['candidate_processing'] is False
    assert result['gets']==2 and result['verified']==2


@pytest.mark.parametrize('mode,status,gets',[('none','source_run_pending',1),('queued','source_run_pending',1),
                                               ('failed','source_run_failed',1),('no_artifact','source_artifact_pending',2)])
def test_discovery_distinguishes_pending_and_failed_from_work(mode,status,gets,tmp_path):
    result=invoke(request(tmp_path),mode)
    assert result.get('result',{}).get('status')==status,result
    assert result['result']['candidate_processing'] is False and result['gets']==gets


@pytest.mark.parametrize('mode',['ambiguous','http','unverified'])
def test_discovery_never_retries_or_guesses_across_denials_or_ambiguous_runs(mode,tmp_path):
    result=invoke(request(tmp_path),mode)
    assert 'error' in result
    if mode=='http':assert '429' in result['error'] and result['gets']==1
    if mode=='unverified':assert result['gets']==0
