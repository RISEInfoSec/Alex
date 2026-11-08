import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_site_source_result_writer import request
ROOT=Path(__file__).resolve().parents[1]


def invoke(value,mode):
    code=r"""import {readSourceEvidence} from './tools/content_review/site_source_artifact_service.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode,ok=x=>({isError:false,structuredContent:x});
let reads=0,verifies=0;const api={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:v.input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>ok({sha:commit_sha,parents:mode==='history'?[]:[v.source]}),
 fetchFile:async({path,ref})=>{const item=v.files[ref+':'+path];return item?ok(item):({isError:true})}};
const input={...v.input};delete input.files;
const verify=async()=>{verifies++;if(mode==='unverified')throw Error('Current worker lease or heartbeat is unavailable')};
const artifactReader=async()=>{reads++;if(mode==='mismatch'){const x=structuredClone(v.observed);const data=JSON.parse(x.result_text);data.request_id='0'.repeat(64);x.result_text=JSON.stringify(data);return x}return v.observed};
try{const result=await readSourceEvidence({github:api,getToken:()=> 'secret',input,now:()=>v.now,verify,artifactReader,heartbeatFactory:()=>async()=>({renewed:false})});
 process.stdout.write(JSON.stringify({status:result.status,request_id:result.request_id,candidate_processing:result.candidate_processing,publication_verified:result.publication_verified,reads,verifies}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,reads,verifies}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_handoff_requires_pending_request_and_returns_verified_artifact_for_accounting(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('status')=='verified_source_artifact',result
    assert result['candidate_processing'] is False and result['publication_verified'] is False and result['verifies']==2


@pytest.mark.parametrize('mode',['unverified','mismatch'])
def test_handoff_blocks_unleased_or_wrong_artifact(tmp_path,mode):
    result=invoke(request(tmp_path),mode)
    assert 'error' in result
    if mode=='unverified':assert result['reads']==0
