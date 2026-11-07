from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_plan import fixture,call
from tests.test_content_review_source_request_guard import guarded
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.verified_inputs import load_inputs

ROOT=Path(__file__).resolve().parents[1]


def request(repo):
    now,review,main,hb,_,snapshot=fixture(repo)
    inputs=load_inputs(repo,review,main);state=inputs['worker_state'];run=state['current_run'];started=run['started_at']
    run['scheduled_for']=started;run['scheduler']={'id':'Automation_worker','is_enabled':True,'observed_at':now.isoformat(),
        'last_run':{'id':'run','recorded_status':'in_progress','started_at':started,'scheduled_for':started}}
    put(repo,'config/content_review_worker_status.json',state)
    put(repo,'config/content_review_monitor_config.json',{'target_automation_id':'Automation_worker','heartbeat_ref':'codex/content-review-heartbeat'})
    git(repo,'add','config/content_review_worker_status.json','config/content_review_monitor_config.json');git(repo,'commit','-qm','scheduler fixture')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    heartbeat=prepare_heartbeat(state,review,'worker','run',at=now)
    git(repo,'checkout','-qb','source-heartbeat');put(repo,'config/content_review_detached_heartbeat.json',heartbeat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    proposal=call(repo,now,review,main,hb,snapshot);result=guarded(repo,now,review,main,hb,snapshot,proposal)
    old={}
    for path in ['config/content_review_worker_status.json','config/content_review_candidate_lifecycle.json',
                 'config/review_console.json','config/weekly_review_manifest.json','config/content_review_monitor_config.json']:
        content=subprocess.check_output(['git','-C',str(repo),'show',review+':'+path]).decode('utf8')
        old[path]={'content':content,'sha':git(repo,'rev-parse',review+':'+path)}
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'old':old,'heartbeat':heartbeat,
            'input':{'expectedHead':review,'expectedMain':main,'owner':'worker','runId':'run','files':result['bundle']['files']}}


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeSourceRequest} from './tools/content_review/site_source_request_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,phase='idle',commits=0,blobs=0,events=[];
const commit='d'.repeat(40),tree='c'.repeat(40),api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:head}}),
 fetchFile:async({path})=>Object.hasOwn(v.old,path)?ok(v.old[path]):({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
 fetchCommitDetails:async()=>ok({sha:v.input.expectedHead,tree_sha:'b'.repeat(40),parents:[]}),
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)})},createTree:async()=>ok({sha:tree}),
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');head=commit;return ok({success:true,sha:commit})}};
const control=async({input})=>{events.push(input.action);if(input.action==='acquire'){phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){phase='idle';return {status:'aborted'}}if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:commit}}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
const verify=async()=>{if(mode==='unverified')throw Error('Worker lease unavailable')};
if(mode==='tampered'){const p=Object.keys(v.input.files).find(x=>x.includes('source_requests/')),r=JSON.parse(v.input.files[p]);
 r.records[0].url='https://different.example/';v.input.files[p]=JSON.stringify(r)}
try{const result=await writeSourceRequest({db:{},github:api,input:v.input,now:()=>v.now,read,control,verify});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_source_reservation_is_validated_and_reports_no_workflow_success(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['source_request_reserved'] is True and result['result']['source_workflow_verified'] is False
    assert result['result']['candidate_processing'] is False and result['result']['publication_verified'] is False
    assert result['events']==['acquire','begin','release'] and result['commits']==1


@pytest.mark.parametrize('mode',['tampered','unverified','changed','ambiguous'])
def test_source_reservation_stops_or_keeps_fence_on_uncertain_outcome(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode in ('tampered','unverified'):assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
