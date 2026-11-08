from copy import deepcopy
from datetime import datetime,timezone
import json,subprocess
from pathlib import Path

import pytest
from tests.test_content_review_site_source_gate_readback import actual_request
from tests.test_content_review_verified_inputs import git
from tools.content_review.source_gate_run_completion import prepare

ROOT=Path(__file__).resolve().parents[1]


def request(repo, *, pending=False):
    value=actual_request(repo,pending=pending);head=value['input']['expectedHead'];main=value['input']['expectedMain'];hb=git(repo,'rev-parse','completion-heartbeat')
    now=datetime.fromtimestamp(value['now']/1000,timezone.utc)
    proposal=prepare(repo,head,main,hb,value['native'],value['snapshot'],deepcopy(value['snapshot']),'worker','run2',value['path'],at=now)
    value['input'].update(checkpointCommit=head,files=proposal['files'])
    return value


def invoke(value,mode):
    script=r"""import fs from 'node:fs';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {writeSourceGateCompletion} from './tools/content_review/site_source_gate_completion_writer.mjs';
import {verifySourceGateCheckpoint} from './tools/content_review/site_source_gate_readback.mjs';
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
  if(commit_sha===heartbeatHead)return ok({sha:heartbeatHead,tree_sha:v.details[v.source].tree_sha,parents:[]});
  if(commit_sha===commit)return ok({sha:commit,tree_sha:tree,parents:[v.input.expectedHead]});return {isError:true}},
 fetchFile:async({path,ref})=>{
  if(path==='config/content_review_detached_heartbeat.json'&&ref===heartbeatHead)return ok({sha:hash(heartbeatContent),content:heartbeatContent});
  if(ref===commit&&saved[path])return ok({sha:hash(saved[path]),content:saved[path]});
  const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 createBlob:async({content})=>ok({sha:hash(content)}),
 createTree:async({base_tree_sha})=>{
  if(base_tree_sha===v.details[v.reservationParent].tree_sha)return ok({sha:v.details[v.reservation].tree_sha});
  if(base_tree_sha===v.details[v.source].tree_sha)return ok({sha:v.details[v.input.expectedHead].tree_sha});
  if(mode==='d1change')sqlite.prepare('INSERT INTO review_submissions VALUES (?,?,?,?,?,?,?,?,?)')
   .run('new-submission','user','weekly',1,1,0,1,'0'.repeat(64),v.heartbeat.started_at);return ok({sha:tree})},
 commitOnBranch:async({branch_name,additions})=>{if(branch_name==='codex/content-review-heartbeat'){
   heartbeatUpdates++;heartbeatContent=additions[0].content;heartbeatHead='f'.repeat(40);return ok({success:true,sha:heartbeatHead});}
  commits++;if(mode==='ambiguous')throw Error('lost');for(const x of additions)saved[x.path]=x.content;head=commit;return ok({success:true,sha:commit})}};
const artifactReader=async({heartbeat})=>{await heartbeat();return v.observed};
const check=async options=>verifySourceGateCheckpoint({...options,artifactReader});
let outcome;try{outcome={result:await writeSourceGateCompletion({db,github:api,getToken:()=>'',input:v.input,now:()=>v.now,check})}}
catch(e){outcome={error:e.message}}
outcome.commits=commits;outcome.heartbeat_updates=heartbeatUpdates;
outcome.fence=sqlite.prepare('SELECT phase FROM content_review_write_fence').all().map(x=>x.phase);
if(saved['config/content_review_worker_status.json']){
 const after=JSON.parse(saved['config/content_review_worker_status.json']);
 const before=JSON.parse(v.files[v.input.expectedHead+':config/content_review_worker_status.json'].content);
 outcome.pending_preserved=JSON.stringify(after.current_run.pending_source_request)===JSON.stringify(before.current_run.pending_source_request);
}
if(mode==='ambiguous'){
 try{sqlite.prepare('INSERT INTO review_submissions VALUES (?,?,?,?,?,?,?,?,?)')
  .run('blocked','user','weekly',1,1,0,1,'0'.repeat(64),v.heartbeat.started_at);outcome.blocked=false;}
 catch(e){outcome.blocked=e.message.includes('review_checkpoint_in_progress')}
}
process.stdout.write(JSON.stringify(outcome));sqlite.close();"""
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('mode',['success','d1change','ambiguous'])
def test_source_completion_reaudits_and_fences_live_decisions(tmp_path,mode):
    result=invoke(request(tmp_path),mode)
    if mode=='success':
        assert result.get('result',{}).get('status')=='committed_and_read_back',result
        assert result['result']['candidate_processing'] is True and result['result']['native_completion_verified'] is False
        assert result['heartbeat_updates']==1 and result['commits']==1 and result['fence']==[]
    if mode=='d1change':assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[]
    if mode=='ambiguous':assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True


def test_source_gate_completion_preserves_pending_source_under_real_d1_fence(tmp_path):
    result=invoke(request(tmp_path,pending=True),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['pending_preserved'] is True and result['fence']==[] and result['commits']==1
