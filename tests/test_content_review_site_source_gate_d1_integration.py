from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json,subprocess
from pathlib import Path

import pytest
from tests.test_content_review_site_source_gate_writer import request as original_request
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.source_gate_checkpoint import prepare as checkpoint
from tools.content_review.verified_inputs import load_inputs

ROOT=Path(__file__).resolve().parents[1]


def request(repo,gate='access'):
    value=original_request(repo,gate=gate);old=value['input']['expectedHead'];main=value['input']['expectedMain']
    state=json.loads(value['files'][old+':config/content_review_worker_status.json']['content']);run=state['current_run']
    now=datetime.fromtimestamp(value['now']/1000,timezone.utc);started=run['started_at'];run['scheduled_for']=started
    run['scheduler']={'id':'Automation_worker','is_enabled':True,'observed_at':now.isoformat(),
        'last_run':{'id':'run','recorded_status':'in_progress','started_at':started,'scheduled_for':started}}
    put(repo,'config/content_review_worker_status.json',state)
    put(repo,'config/content_review_monitor_config.json',{'target_automation_id':'Automation_worker','heartbeat_ref':'codex/content-review-heartbeat'})
    git(repo,'add','config/content_review_worker_status.json','config/content_review_monitor_config.json');git(repo,'commit','-qm','scheduler')
    head=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD');beat=prepare_heartbeat(state,head,'worker','run',at=now)
    git(repo,'checkout','-qb','source-gate-heartbeat');put(repo,'config/content_review_detached_heartbeat.json',beat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat');git(repo,'checkout','-q',branch)
    inputs=load_inputs(repo,head,main);row=inputs['manifests']['weekly']['records'][0]
    proposal=checkpoint(repo,value['snapshot'],deepcopy(value['snapshot']),inputs,inputs['lifecycle'],state,'worker','run','weekly',row['candidate_id'],gate,
        observed_heads={'review':head,'main':main},source_attempts=state.get('source_attempts',{}),
        source_progress=state.get('source_last_progress',{}),at=now,heartbeat=beat)
    paths=['config/content_review_worker_status.json','config/content_review_monitor_config.json','config/content_review_candidate_lifecycle.json',
           'config/review_console.json','config/content_review_lifecycle_policy.json','config/content_review_preflight_status.json',
           'config/weekly_review_manifest.json',row['source_processing']['receipt'],row['source_processing']['receipt'].replace('_receipts/','_requests/')]
    for path in paths:
        content=subprocess.check_output(['git','-C',str(repo),'show',head+':'+path]);sha=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        value['files'][head+':'+path]={'sha':sha,'content':content.decode('utf8')}
    value['details'][head]={'sha':head,'tree_sha':git(repo,'rev-parse',head+'^{tree}'),'parents':[old]}
    value['input'].update(expectedHead=head,files=proposal['files']);value['heartbeat']=beat
    return value


def invoke(value,mode):
    code=r"""import fs from 'node:fs';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {writeSourceGate} from './tools/content_review/site_source_gate_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex'),ok=x=>({isError:false,structuredContent:x});
let head=v.input.expectedHead,heartbeatHead='e'.repeat(40),heartbeatContent=JSON.stringify(v.heartbeat),heartbeatUpdates=0,commits=0;
const commit='d'.repeat(40),tree='c'.repeat(40),sqlite=new DatabaseSync(':memory:');
sqlite.exec(`CREATE TABLE review_submissions (id TEXT PRIMARY KEY,user_id TEXT,collection TEXT,batch INTEGER,revision INTEGER,accepted INTEGER,rejected INTEGER,payload_hash TEXT,created_at TEXT);
 CREATE TABLE review_decisions (id TEXT PRIMARY KEY,submission_id TEXT,user_id TEXT,collection TEXT,batch INTEGER,revision INTEGER,candidate_id TEXT,review_number INTEGER,content_sha256 TEXT,decision TEXT);
 CREATE TABLE review_jobs (id TEXT PRIMARY KEY,submission_id TEXT,user_id TEXT,collection TEXT,revision INTEGER,candidate_id TEXT,content_sha256 TEXT,kind TEXT);`);
sqlite.exec(fs.readFileSync('tools/content_review/site_write_fence_migration.sql','utf8'));
function prepared(sql,values=[]){return {sql,values,bind(...args){return prepared(sql,args)},
 async run(){const r=sqlite.prepare(sql).run(...values);return {success:true,meta:{changes:Number(r.changes)}}},
 async first(){return sqlite.prepare(sql).get(...values)||null}}}
const db={prepare:sql=>prepared(sql),async batch(items){return items.map(({sql,values})=>({success:true,results:sqlite.prepare(sql).all(...values)}))}};
const saved={},api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:commit_sha==='codex/content-review-heartbeat'?heartbeatHead:head}}),
 fetchCommitDetails:async({commit_sha})=>{if(v.details[commit_sha])return ok(v.details[commit_sha]);
  if(commit_sha===heartbeatHead)return ok({sha:heartbeatHead,tree_sha:v.details[v.parent].tree_sha,parents:[]});
  if(commit_sha===commit)return ok({sha:commit,tree_sha:tree,parents:[v.input.expectedHead]});return {isError:true}},
 fetchFile:async({path,ref})=>{
  if(path==='config/content_review_detached_heartbeat.json'&&ref===heartbeatHead)return ok({sha:hash(heartbeatContent),content:heartbeatContent});
  if(ref===commit&&saved[path])return ok({sha:hash(saved[path]),content:saved[path]});
  const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 createBlob:async({content})=>ok({sha:hash(content)}),
 createTree:async({base_tree_sha})=>{if(base_tree_sha===v.details[v.parent].tree_sha)return ok({sha:v.details[v.reservation].tree_sha});
  if(mode==='d1change')sqlite.prepare('INSERT INTO review_submissions VALUES (?,?,?,?,?,?,?,?,?)')
   .run('new-submission','user','weekly',1,1,0,1,'0'.repeat(64),v.heartbeat.started_at);return ok({sha:tree})},
 commitOnBranch:async({branch_name,additions})=>{if(branch_name==='codex/content-review-heartbeat'){
   heartbeatUpdates++;heartbeatContent=additions[0].content;heartbeatHead='f'.repeat(40);return ok({success:true,sha:heartbeatHead});}
  commits++;if(mode==='ambiguous')throw Error('lost');for(const x of additions)saved[x.path]=x.content;head=commit;return ok({success:true,sha:commit})}};
const artifactReader=async({heartbeat})=>{await heartbeat();return v.observed};
let outcome;try{outcome={result:await writeSourceGate({db,github:api,getToken:()=> 'not-used',input:v.input,now:()=>v.now,artifactReader})}}
catch(e){outcome={error:e.message}}
outcome.commits=commits;outcome.heartbeat_updates=heartbeatUpdates;
outcome.fence=sqlite.prepare('SELECT phase FROM content_review_write_fence').all().map(x=>x.phase);
if(mode==='ambiguous'){
 try{sqlite.prepare('INSERT INTO review_submissions VALUES (?,?,?,?,?,?,?,?,?)')
  .run('blocked','user','weekly',1,1,0,1,'0'.repeat(64),v.heartbeat.started_at);outcome.blocked=false;}
 catch(e){outcome.blocked=e.message.includes('review_checkpoint_in_progress')}
}
process.stdout.write(JSON.stringify(outcome));sqlite.close();"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('mode',['success','d1change','ambiguous'])
def test_source_gate_is_fenced_and_never_retried(tmp_path,mode):
    result=invoke(request(tmp_path),mode)
    if mode=='success':
        assert result.get('result',{}).get('status')=='committed_and_read_back',result
        assert result['result']['candidate_processing'] is True and result['result']['publication_verified'] is False
        assert result['heartbeat_updates']==1 and result['commits']==1 and result['fence']==[]
    if mode=='d1change':assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[]
    if mode=='ambiguous':assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True


@pytest.mark.parametrize('mode',['success','d1change','ambiguous'])
def test_explicit_format_gate_uses_the_same_real_d1_fence(tmp_path,mode):
    result=invoke(request(tmp_path,gate='format'),mode)
    if mode=='success':
        assert result.get('result',{}).get('status')=='committed_and_read_back',result
        assert result['result']['gate']=='format' and result['result']['publication_verified'] is False
        assert result['commits']==1 and result['fence']==[]
    if mode=='d1change':assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[]
    if mode=='ambiguous':assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True
