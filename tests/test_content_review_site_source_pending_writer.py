import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_pending import fixture,call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def request(repo,failed=False):
    values=fixture(repo);now,head,main,hb,native,snapshot,reservation,discovery=values
    if failed:discovery.update(status='source_run_failed',source_run_id=123,conclusion='failure')
    proposal=call(repo,values)
    before=json.loads(git(repo,'show',head+':config/content_review_worker_status.json'));rid=before['current_run']['pending_source_request']['request_id']
    paths=['config/content_review_worker_status.json','config/content_review_source_requests/'+rid+'.json'];files={}
    for path in paths:
        raw=subprocess.check_output(['git','-C',str(repo),'show',head+':'+path]);files[path]={'sha':git(repo,'rev-parse',head+':'+path),'content':raw.decode()}
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'files':files,'discovery':discovery,
       'input':{'expectedHead':head,'expectedMain':main,'reservationHead':reservation,'owner':'worker','runId':'run','files':proposal['files']}}


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeSourcePending} from './tools/content_review/site_source_pending_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex'),ok=x=>({isError:false,structuredContent:x});
let phase='idle',commits=0,blobs=0,events=[],clockOffset=0,pulses=0;const commit='d'.repeat(40),tree='c'.repeat(40),api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:v.input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>ok({sha:commit_sha,tree_sha:'b'.repeat(40),parents:[]}),
 fetchFile:async({path})=>v.files[path]?ok(v.files[path]):({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)})},createTree:async()=>{if(mode==='expired')clockOffset=181000;return ok({sha:tree})},
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');return ok({success:true,sha:commit})}};
const control=async({input})=>{events.push(input.action);if(input.action==='acquire'){phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){phase='idle';return {status:'aborted'}}if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:commit}}};
const read=async({heartbeat})=>{if(mode==='slow'){clockOffset=45000;await heartbeat()}return {snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false}};
const verify=async()=>{if(mode==='unverified')throw Error('worker unavailable')};
const discover=async()=>mode==='ready'?{...v.discovery,status:'source_artifact_ready'}:v.discovery;
if(mode==='receipt'){const p=Object.keys(v.input.files).find(x=>x.includes('run_receipts/')),r=JSON.parse(v.input.files[p]);
 r.candidate_processing=true;v.input.files[p]=JSON.stringify(r)}
try{const result=await writeSourcePending({db:{},github:api,getToken:()=> 'not-used',input:v.input,now:()=>v.now+clockOffset,read,control,verify,discover,heartbeatFactory:()=>async()=>{pulses++}});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events,pulses}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events,pulses}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_pending_deferral_rechecks_workflow_and_fences_lease_release(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['source_status']=='source_run_pending' and result['result']['candidate_processing'] is False
    assert result['events']==['acquire','begin','release'] and result['commits']==1


@pytest.mark.parametrize('mode',['ready','receipt','unverified','changed','ambiguous','expired'])
def test_pending_deferral_fails_closed_and_preserves_ambiguous_fence(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode in ('ready','receipt','unverified'):assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
    if mode=='expired':assert result['commits']==0 and result['events']==[]


def test_pending_deferral_renews_heartbeat_during_slow_snapshot(tmp_path):
    result=invoke(request(tmp_path),'slow')
    assert result['result']['status']=='committed_and_read_back' and result['pulses'] >= 2
