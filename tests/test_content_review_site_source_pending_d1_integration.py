import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_site_source_pending_writer import request as original_request
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def request(repo,failed=False):
    value=original_request(repo,failed=failed);head=value['input']['expectedHead']
    content=subprocess.check_output(['git','-C',str(repo),'show',head+':config/content_review_monitor_config.json'])
    value['files']['config/content_review_monitor_config.json']={'sha':hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest(),'content':content.decode()}
    value['heartbeat']=json.loads(git(repo,'show','pending-heartbeat:config/content_review_detached_heartbeat.json'))
    return value


def invoke(value,mode):
    code=r"""import fs from 'node:fs';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {writeSourcePending} from './tools/content_review/site_source_pending_writer.mjs';
import {makeHeartbeatKeeper} from './tools/content_review/site_heartbeat_keeper.mjs';
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
 fetchCommitDetails:async({commit_sha})=>{if(commit_sha===v.input.expectedHead||commit_sha===heartbeatHead)return ok({sha:commit_sha,tree_sha:'b'.repeat(40),parents:[]});
  if(commit_sha===commit)return ok({sha:commit,tree_sha:tree,parents:[v.input.expectedHead]});return {isError:true}},
 fetchFile:async({path,ref})=>{
  if(path==='config/content_review_detached_heartbeat.json'&&ref===heartbeatHead)return ok({sha:hash(heartbeatContent),content:heartbeatContent});
  if(ref===commit&&saved[path])return ok({sha:hash(saved[path]),content:saved[path]});
  return v.files[path]?ok(v.files[path]):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 createBlob:async({content})=>ok({sha:hash(content)}),
 createTree:async()=>{if(mode==='d1change')sqlite.prepare('INSERT INTO review_submissions VALUES (?,?,?,?,?,?,?,?,?)')
   .run('new-submission','user','weekly',1,1,0,1,'0'.repeat(64),v.heartbeat.started_at);return ok({sha:tree})},
 commitOnBranch:async({branch_name,additions})=>{if(branch_name==='codex/content-review-heartbeat'){
   heartbeatUpdates++;heartbeatContent=additions[0].content;heartbeatHead='f'.repeat(40);return ok({success:true,sha:heartbeatHead});}
  commits++;if(mode==='ambiguous')throw Error('lost');for(const x of additions)saved[x.path]=x.content;head=commit;return ok({success:true,sha:commit})}};
const discover=async({github,input,now})=>{const pulse=makeHeartbeatKeeper({github,input,now});await pulse();
 return mode==='advanced'?{...v.discovery,source_run_id:123}:v.discovery};
let outcome;try{outcome={result:await writeSourcePending({db,github:api,getToken:()=> 'not-used',input:v.input,now:()=>v.now,discover,heartbeatFactory:()=>async()=>{}})}}
catch(e){outcome={error:e.message}}
outcome.commits=commits;outcome.heartbeat_updates=heartbeatUpdates;
if(saved['config/content_review_worker_status.json']){
 const state=JSON.parse(saved['config/content_review_worker_status.json']);outcome.unresolved=state.source_unresolved_requests||[];
}
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
def test_source_pending_deferral_is_fenced_and_never_retried(tmp_path,mode):
    result=invoke(request(tmp_path),mode)
    if mode=='success':
        assert result.get('result',{}).get('status')=='committed_and_read_back',result
        assert result['result']['candidate_processing'] is False and result['result']['native_completion_verified'] is False
        assert result['heartbeat_updates']==1 and result['commits']==1 and result['fence']==[]
    if mode=='d1change':assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[]
    if mode=='ambiguous':assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True


@pytest.mark.parametrize('mode',['success','d1change','ambiguous'])
def test_failed_source_is_retained_under_real_d1_fence_without_guessing_usage(tmp_path,mode):
    result=invoke(request(tmp_path,failed=True),mode)
    if mode=='success':
        assert result.get('result',{}).get('status')=='committed_and_read_back',result
        assert result['result']['source_status']=='source_run_failed' and result['commits']==1 and result['fence']==[]
        assert len(result['unresolved'])==1 and result['unresolved'][0]['origin_provider_requests'] is None
    if mode=='d1change':assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[]
    if mode=='ambiguous':assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True


def test_workflow_start_during_d1_read_keeps_request_pending_under_fence(tmp_path):
    result=invoke(request(tmp_path),'advanced')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['source_status']=='source_run_pending' and result['result']['candidate_processing'] is False
    assert result['commits']==1 and result['fence']==[]
