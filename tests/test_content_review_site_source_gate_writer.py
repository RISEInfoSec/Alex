from copy import deepcopy
from datetime import timedelta
import hashlib,json,subprocess
from pathlib import Path

import pytest
from tests.test_content_review_source_result_guard import setup,call_guard
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as heartbeat
from tools.content_review.source_retention import prepare as retain
from tools.content_review.source_retention_checkpoint import prepare as retain_checkpoint
from tools.content_review.source_gate_checkpoint import prepare as gate_checkpoint
from tools.content_review.stage_summary import derive
from tools.content_review.verified_inputs import load_inputs

ROOT=Path(__file__).resolve().parents[1]


def rebeat(repo,state,review,now):
    branch=git(repo,'symbolic-ref','--short','HEAD');beat=heartbeat(state,review,'worker','run',at=now)
    git(repo,'checkout','-q','heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat update');head=git(repo,'rev-parse','HEAD')
    git(repo,'checkout','-q',branch);return head


def request(repo):
    now,review,main,hb,snapshot,source,raw,run,artifact=setup(repo)
    result=json.loads(raw);item=source['records'][0];url=item['url'];text='Actual published source evidence.'
    result['records'][0].update(status='retrieved',next_action='Inspect retained evidence.',evidence=[{
        'requested_url':url,'final_url':url,'text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'body_sha256':'f'*64,'retrieved_at':now.isoformat(),'http_status':200,'container_type':'html','metadata':{}}])
    raw=json.dumps(result).encode();artifact['sha256']=hashlib.sha256(raw).hexdigest()
    guarded=call_guard(repo,now,review,main,hb,snapshot,source,raw,run,artifact)
    for path,content in guarded['bundle']['files'].items():put(repo,path,content)
    git(repo,'add','.');git(repo,'commit','-qm','account source');review=git(repo,'rev-parse','HEAD');now+=timedelta(seconds=1)
    state=json.loads((repo/'config/content_review_worker_status.json').read_text());hb=rebeat(repo,state,review,now)
    proposal=retain(repo,review,main,hb,snapshot,deepcopy(snapshot),source['request_id'],raw,run,artifact,
        item['collection'],item['candidate_id'],'worker','run',observed_heads={'review':review,'main':main},at=now)
    checkpoint=retain_checkpoint(repo,review,main,hb,snapshot,deepcopy(snapshot),source['request_id'],raw,run,artifact,
        item['collection'],item['candidate_id'],'worker','run',proposal,observed_heads={'review':review,'main':main},at=now)
    for path,content in checkpoint['bundle']['files'].items():put(repo,path,content)
    manifest=json.loads((repo/proposal['path']).read_text());row=manifest['records'][0]
    stage_rows=[{'collection':item['collection'],'candidate_id':item['candidate_id'],'review_number':row['review_number'],
                 'content_sha256':row['content_sha256'],'checks':deepcopy(row['preflight']['checks']),'status':'held','review_ready':False}]
    put(repo,'config/content_review_preflight_status.json',{'records':stage_rows,'summary':derive(stage_rows)})
    git(repo,'add','.');git(repo,'commit','-qm','retain source');review=git(repo,'rev-parse','HEAD');now+=timedelta(seconds=1)
    state=json.loads((repo/'config/content_review_worker_status.json').read_text());hb=rebeat(repo,state,review,now)
    inputs=load_inputs(repo,review,main)
    bundle=gate_checkpoint(repo,snapshot,deepcopy(snapshot),inputs,inputs['lifecycle'],state,'worker','run',
        item['collection'],item['candidate_id'],'access',observed_heads={'review':review,'main':main},
        source_attempts=state.get('source_attempts',{}),source_progress=state.get('source_last_progress',{}),at=now,
        heartbeat=json.loads(git(repo,'show',hb+':config/content_review_detached_heartbeat.json')))
    reservation=run['head_sha'];parent=git(repo,'rev-parse',reservation+'^')
    paths=['config/content_review_worker_status.json','config/content_review_candidate_lifecycle.json',
        'config/review_console.json','config/content_review_lifecycle_policy.json','config/content_review_preflight_status.json',
        'config/weekly_review_manifest.json','config/content_review_source_requests/'+source['request_id']+'.json',
        'config/content_review_source_receipts/'+source['request_id']+'.json']
    refs=git(repo,'rev-list','--max-count=100',review).splitlines();files={};details={}
    for ref in refs:
        parts=git(repo,'rev-list','--parents','-n','1',ref).split()
        details[ref]={'sha':ref,'tree_sha':git(repo,'rev-parse',ref+'^{tree}'),'parents':parts[1:]}
        for path in paths:
            p=subprocess.run(['git','-C',str(repo),'show',ref+':'+path],capture_output=True)
            if p.returncode==0:files[ref+':'+path]={'sha':git(repo,'rev-parse',ref+':'+path),'content':p.stdout.decode('utf8')}
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'files':files,'details':details,'reservation':reservation,'parent':parent,
        'observed':{'native_run':run,'artifact':artifact,'result_text':raw.decode('utf8')},
        'input':{'expectedHead':review,'expectedMain':main,'owner':'worker','runId':'run','files':bundle['files']}}


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeSourceGate} from './tools/content_review/site_source_gate_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let phase='idle',commits=0,blobs=0,events=[],clockOffset=0;
const commit='d'.repeat(40),tree='c'.repeat(40),api={
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
const verify=async()=>{if(mode==='unverified')throw Error('Worker lease unavailable')};
const artifactReader=async()=>{if(mode==='artifact')throw Error('Artifact digest differs');return v.observed};
const heartbeatFactory=()=>async()=>({renewed:false});
if(mode==='receipt'){const p=Object.keys(v.input.files).find(x=>x.includes('source_gate_checkpoints/')),r=JSON.parse(v.input.files[p]);
 r.publication_approved=true;v.input.files[p]=JSON.stringify(r)}
try{const result=await writeSourceGate({db:{},github:api,getToken:()=> 'not-used',input:v.input,now:()=>v.now+clockOffset,read,control,verify,artifactReader,heartbeatFactory,auditOnly:mode==='audit'});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_source_gate_writer_fences_independently_verified_evidence(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['candidate_processing'] is True and result['result']['publication_verified'] is False
    assert result['events']==['acquire','begin','release'] and result['commits']==1


def test_internal_source_gate_audit_never_commits_or_acquires_fence(tmp_path):
    result=invoke(request(tmp_path),'audit')
    assert result.get('result',{}).get('status')=='validated',result
    assert result['events']==[] and result['commits']==0 and result['blobs']==0


@pytest.mark.parametrize('mode',['tree','artifact','receipt','unverified','changed','ambiguous','expired'])
def test_source_gate_writer_fails_closed(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode in ('tree','artifact','receipt','unverified'):assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='expired':assert result['commits']==0 and result['events']==[] and 'expired' in result['error']
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
