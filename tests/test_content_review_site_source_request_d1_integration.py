import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_site_source_request_writer import request

ROOT=Path(__file__).resolve().parents[1]


def invoke(value,mode):
    code=r"""import fs from 'node:fs';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {writeSourceRequest} from './tools/content_review/site_source_request_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex'),ok=x=>({isError:false,structuredContent:x});
let head=v.input.expectedHead,commits=0;const heartbeatHead='e'.repeat(40),commit='d'.repeat(40),tree='c'.repeat(40),base='b'.repeat(40);
const sqlite=new DatabaseSync(':memory:');
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
 fetchFile:async({path,ref})=>{
  if(path==='config/content_review_detached_heartbeat.json'&&ref===heartbeatHead){const content=JSON.stringify(v.heartbeat);return ok({sha:hash(content),content})}
  if(ref===commit&&saved[path])return ok({sha:hash(saved[path]),content:saved[path]});
  const item=v.old[path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 fetchCommitDetails:async({commit_sha})=>commit_sha===v.input.expectedHead?ok({sha:commit_sha,tree_sha:base,parents:[]}):
  ok({sha:commit,tree_sha:tree,parents:[v.input.expectedHead]}),
 createBlob:async({content})=>ok({sha:hash(content)}),
 createTree:async()=>{if(mode==='d1change')sqlite.prepare('INSERT INTO review_submissions VALUES (?,?,?,?,?,?,?,?,?)')
  .run('new-submission','user','weekly',1,1,0,1,'0'.repeat(64),v.heartbeat.started_at);return ok({sha:tree})},
 commitOnBranch:async({additions})=>{commits++;if(mode==='ambiguous')throw Error('lost');
  for(const x of additions)saved[x.path]=x.content;head=commit;return ok({success:true,sha:commit})}};
let outcome;try{outcome={result:await writeSourceRequest({db,github:api,input:v.input,now:()=>v.now})}}catch(e){outcome={error:e.message}}
outcome.commits=commits;outcome.fence=sqlite.prepare('SELECT phase FROM content_review_write_fence').all().map(x=>x.phase);
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
def test_source_reservation_is_fenced_before_workflow_can_start(tmp_path,mode):
    result=invoke(request(tmp_path),mode)
    if mode=='success':
        assert result.get('result',{}).get('status')=='committed_and_read_back',result
        assert result['result']['source_workflow_verified'] is False and result['result']['candidate_processing'] is False
        assert result['commits']==1 and result['fence']==[]
    if mode=='d1change':assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[]
    if mode=='ambiguous':assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True
