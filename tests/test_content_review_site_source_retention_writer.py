from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_retention import fixture,call
from tests.test_content_review_verified_inputs import git
from tools.content_review.source_retention_checkpoint import prepare as checkpoint

ROOT=Path(__file__).resolve().parents[1]


def request(repo):
    now,head,main,hb,snapshot,source_request,raw,run,artifact=fixture(repo)
    proposal=call(repo,now,head,main,hb,snapshot,source_request,raw,run,artifact)
    item=source_request['records'][0]
    bundle=checkpoint(repo,head,main,hb,snapshot,deepcopy(snapshot),source_request['request_id'],raw,run,artifact,
        item['collection'],item['candidate_id'],'worker','run',proposal,observed_heads={'review':head,'main':main},at=now)
    reservation=run['head_sha'];parent=git(repo,'rev-parse',reservation+'^')
    paths=['config/content_review_worker_status.json','config/content_review_candidate_lifecycle.json','config/review_console.json',
        'config/content_review_workflow.json',proposal['path'],
        'config/content_review_source_requests/'+source_request['request_id']+'.json',
        'config/content_review_source_receipts/'+source_request['request_id']+'.json']
    refs=git(repo,'rev-list','--max-count=20',head).splitlines();files={};details={}
    for ref in refs:
        parts=git(repo,'rev-list','--parents','-n','1',ref).split()
        details[ref]={'sha':ref,'tree_sha':git(repo,'rev-parse',ref+'^{tree}'),'parents':parts[1:]}
        for path in paths:
            p=subprocess.run(['git','-C',str(repo),'show',ref+':'+path],capture_output=True)
            if p.returncode==0:files[ref+':'+path]={'sha':git(repo,'rev-parse',ref+':'+path),'content':p.stdout.decode('utf8')}
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'files':files,'details':details,'reservation':reservation,'parent':parent,
        'observed':{'native_run':run,'artifact':artifact,'result_text':raw.decode('utf8')},
        'input':{'expectedHead':head,'expectedMain':main,'owner':'worker','runId':'run','sourceRunId':run['id'],
                 'artifactId':artifact['id'],'files':bundle['bundle']['files']}}


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeSourceRetention} from './tools/content_review/site_source_retention_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let phase='idle',commits=0,blobs=0,events=[];
const commit='d'.repeat(40),tree='c'.repeat(40),api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:v.input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>v.details[commit_sha]?ok(v.details[commit_sha]):({isError:true}),
 fetchFile:async({path,ref})=>{const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)})},
 createTree:async({base_tree_sha})=>ok({sha:base_tree_sha===v.details[v.parent].tree_sha?(mode==='tree'?'f'.repeat(40):v.details[v.reservation].tree_sha):tree}),
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');return ok({success:true,sha:commit})}};
const control=async({input})=>{events.push(input.action);if(input.action==='acquire'){phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){phase='idle';return {status:'aborted'}}if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:commit}}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
const verify=async()=>{if(mode==='unverified')throw Error('Worker lease unavailable')};
const artifactReader=async()=>{if(mode==='artifact')throw Error('Artifact digest differs');return v.observed};
const heartbeatFactory=()=>async()=>({renewed:false});
if(mode==='receipt'){const p=Object.keys(v.input.files).find(x=>x.includes('source_checkpoints/')),r=JSON.parse(v.input.files[p]);
 r.publication_approved=true;v.input.files[p]=JSON.stringify(r)}
try{const result=await writeSourceRetention({db:{},github:api,getToken:()=> 'not-used',input:v.input,now:()=>v.now,read,control,verify,artifactReader,heartbeatFactory});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_source_retention_fences_verified_evidence_without_passing_gate(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['gate_passed'] is False and result['result']['candidate_processing'] is False
    assert result['events']==['acquire','begin','release'] and result['commits']==1


@pytest.mark.parametrize('mode',['tree','artifact','receipt','unverified','changed','ambiguous'])
def test_source_retention_rejects_unverified_evidence_and_preserves_fence(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode in ('tree','artifact','receipt','unverified'):assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
