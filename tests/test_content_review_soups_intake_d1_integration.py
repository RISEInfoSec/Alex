import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_soups_intake_writer import make_request

ROOT = Path(__file__).resolve().parents[1]


def invoke(value, mode):
    code="""import fs from 'node:fs';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {writeIntake} from './tools/content_review/soups_intake_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,commitCount=0;
const heartbeatHead='e'.repeat(40),commit='d'.repeat(40),tree='c'.repeat(40),base='b'.repeat(40),iso=n=>new Date(n).toISOString();
const start=iso(v.now-10000),expiry=iso(v.now+1200000),observed=iso(v.now),target='Automation_worker';
const state={lease:{owner:'worker',run_id:'run',acquired_at:start,expires_at:expiry},current_run:{run_id:'run',
 application_status:'running',started_at:start,scheduled_for:start,scheduler:{id:target,is_enabled:true,observed_at:observed,
 last_run:{id:'run',recorded_status:'in_progress',started_at:start,scheduled_for:start}}}};
const config={target_automation_id:target,heartbeat_ref:'codex/content-review-heartbeat'};
const hb={schema_version:1,review_head:v.input.expectedHead,owner:'worker',run_id:'run',scheduler_id:target,
 started_at:start,lease_acquired_at:start,lease_expires_at:expiry,observed_at:observed};
const sqlite=new DatabaseSync(':memory:');
sqlite.exec(`CREATE TABLE review_submissions (id TEXT PRIMARY KEY,user_id TEXT,collection TEXT,batch INTEGER,revision INTEGER,accepted INTEGER,rejected INTEGER,payload_hash TEXT,created_at TEXT);
 CREATE TABLE review_decisions (id TEXT PRIMARY KEY);CREATE TABLE review_jobs (id TEXT PRIMARY KEY);`);
sqlite.exec(fs.readFileSync('tools/content_review/site_write_fence_migration.sql','utf8'));
function prepared(sql,values=[]){return {sql,values,bind(...args){return prepared(sql,args)},
 async run(){const r=sqlite.prepare(sql).run(...values);return {success:true,meta:{changes:Number(r.changes)}}},
 async first(){return sqlite.prepare(sql).get(...values)||null}}}
const db={prepare:sql=>prepared(sql),async batch(items){return items.map(({sql,values})=>({success:true,results:sqlite.prepare(sql).all(...values)}))}};
const saved={};const api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:commit_sha==='codex/content-review-heartbeat'?heartbeatHead:head}}),
 fetchFile:async({path,ref})=>{let obj;
  if(path==='config/content_review_worker_status.json')obj=state;
  else if(path==='config/content_review_monitor_config.json')obj=config;
  else if(path==='config/content_review_detached_heartbeat.json')obj=hb;
  else if(Object.hasOwn(v.old,path))obj=v.old[path];
  else if(ref===commit&&saved[path])return ok({sha:hash(saved[path]),content:saved[path]});
  else return {isError:true,structuredContent:{error_code:'NOT_FOUND'}};
  const content=JSON.stringify(obj);return ok({sha:hash(content),content});},
 fetchCommitDetails:async({commit_sha})=>commit_sha===v.input.expectedHead?ok({sha:commit_sha,tree_sha:base,parents:[]}):
  ok({sha:commit,tree_sha:tree,parents:[v.input.expectedHead]}),
 createBlob:async({content})=>ok({sha:hash(content)}),
 createTree:async()=>{if(mode==='d1change')sqlite.prepare('INSERT INTO review_submissions (id,user_id,collection,batch,revision,accepted,rejected,payload_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?)')
  .run('new-submission','user','soups',1,1,0,1,'0'.repeat(64),observed);return ok({sha:tree});},
 commitOnBranch:async({additions})=>{commitCount++;if(mode==='ambiguous')throw Error('lost');
  for(const x of additions)saved[x.path]=x.content;head=commit;return ok({success:true,sha:commit})}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
let outcome;try{outcome={result:await writeIntake({db,github:api,input:v.input,now:()=>v.now,read,heartbeatFactory:()=>async()=>{}})}}
catch(e){outcome={error:e.message}};
outcome.commits=commitCount;outcome.fence=sqlite.prepare('SELECT phase FROM content_review_write_fence').all().map(x=>x.phase);
outcome.submissions=sqlite.prepare('SELECT COUNT(*) AS n FROM review_submissions').get().n;
if(mode==='ambiguous'){
 try{sqlite.prepare('INSERT INTO review_submissions (id,user_id,collection,batch,revision,accepted,rejected,payload_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?)')
  .run('blocked','user','soups',1,1,0,1,'0'.repeat(64),observed);outcome.blocked=false;}
 catch(e){outcome.blocked=e.message.includes('review_checkpoint_in_progress');}
}
process.stdout.write(JSON.stringify(outcome));sqlite.close();"""
    data={**value,'mode':mode}
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps(data),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('mode',['success','d1change','ambiguous'])
def test_real_d1_fence_controls_the_atomic_intake_writer(tmp_path,mode):
    result=invoke(make_request(tmp_path),mode)
    if mode=='success':
        assert result['result']['status']=='committed_and_read_back' and result['commits']==1 and result['fence']==[]
    if mode=='d1change':
        assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[] and result['submissions']==1
    if mode=='ambiguous':
        assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True
