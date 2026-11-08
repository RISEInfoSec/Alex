import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_completion import fixture,call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def request(repo):
    values=fixture(repo);now,head,main,hb,native,snapshot,rid,raw,run,artifact=values
    proposal=call(repo,values);reservation=run['head_sha'];parent=git(repo,'rev-parse',reservation+'^')
    paths=['config/content_review_worker_status.json','config/content_review_candidate_lifecycle.json','config/review_console.json',
           'config/weekly_review_manifest.json','config/content_review_source_requests/'+rid+'.json','config/content_review_source_receipts/'+rid+'.json']
    refs=git(repo,'rev-list','--max-count=20',head).splitlines();files={};details={}
    for ref in refs:
        parts=git(repo,'rev-list','--parents','-n','1',ref).split();details[ref]={'sha':ref,'tree_sha':git(repo,'rev-parse',ref+'^{tree}'),'parents':parts[1:]}
        for path in paths:
            p=subprocess.run(['git','-C',str(repo),'show',ref+':'+path],capture_output=True)
            if p.returncode==0:files[ref+':'+path]={'sha':git(repo,'rev-parse',ref+':'+path),'content':p.stdout.decode()}
    artifact['archive_sha256']='f'*64
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'files':files,'details':details,'reservation':reservation,'parent':parent,
       'observed':{'native_run':run,'artifact':artifact,'result_text':raw.decode()},
       'input':{'expectedHead':head,'expectedMain':main,'owner':'worker','runId':'run','sourceRunId':run['id'],'artifactId':artifact['id'],'files':proposal['files']}}


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeSourceCompletion} from './tools/content_review/site_source_completion_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex'),ok=x=>({isError:false,structuredContent:x});
let phase='idle',commits=0,blobs=0,events=[],clockOffset=0;const commit='d'.repeat(40),tree='c'.repeat(40),api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:v.input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>v.details[commit_sha]?ok(v.details[commit_sha]):({isError:true}),
 fetchFile:async({path,ref})=>{const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)})},
 createTree:async({base_tree_sha})=>{if(base_tree_sha===v.details[v.parent].tree_sha)return ok({sha:mode==='tree'?'f'.repeat(40):v.details[v.reservation].tree_sha});
  if(mode==='expired')clockOffset=181000;return ok({sha:tree})},
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');return ok({success:true,sha:commit})}};
const control=async({input})=>{events.push(input.action);if(input.action==='acquire'){phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){phase='idle';return {status:'aborted'}}if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:commit}}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
const verify=async()=>{if(mode==='unverified')throw Error('worker unavailable')};
const artifactReader=async()=>{if(mode==='artifact')throw Error('artifact invalid');return v.observed};
const heartbeatFactory=()=>async()=>({renewed:false});
if(mode==='receipt'){const p=Object.keys(v.input.files).find(x=>x.includes('run_receipts/')),r=JSON.parse(v.input.files[p]);
 r.candidate_processing=true;v.input.files[p]=JSON.stringify(r)}
try{const result=await writeSourceCompletion({db:{},github:api,getToken:()=> 'not-used',input:v.input,now:()=>v.now+clockOffset,read,control,verify,artifactReader,heartbeatFactory});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_source_completion_revalidates_artifact_and_fences_lease_release(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['source_workflow_verified'] is True and result['result']['candidate_processing'] is False
    assert result['result']['native_completion_verified'] is False and result['events']==['acquire','begin','release'] and result['commits']==1


@pytest.mark.parametrize('mode',['tree','artifact','receipt','unverified','changed','ambiguous','expired'])
def test_source_completion_fails_closed_and_preserves_ambiguous_fence(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode in ('tree','artifact','receipt','unverified'):assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
    if mode=='expired':assert result['commits']==0 and result['events']==[]
