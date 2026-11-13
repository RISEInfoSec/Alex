import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_run_completion import fixture, call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def invoke(value,mode):
    code="""import fs from 'node:fs';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {writeNoWork} from './tools/content_review/site_no_work_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,commits=0;
const hbHead='e'.repeat(40),commit='d'.repeat(40),tree='c'.repeat(40),base='b'.repeat(40),saved={};
const config={target_automation_id:v.before.current_run.scheduler.id,heartbeat_ref:'codex/content-review-heartbeat'};
const sqlite=new DatabaseSync(':memory:');sqlite.exec(`CREATE TABLE review_submissions (id TEXT PRIMARY KEY,user_id TEXT,collection TEXT,batch INTEGER,revision INTEGER,accepted INTEGER,rejected INTEGER,payload_hash TEXT,created_at TEXT);
CREATE TABLE review_decisions (id TEXT PRIMARY KEY);CREATE TABLE review_jobs (id TEXT PRIMARY KEY);`);
sqlite.exec(fs.readFileSync('tools/content_review/site_write_fence_migration.sql','utf8'));
function stmt(sql,values=[]){return {sql,values,bind(...args){return stmt(sql,args)},async run(){const r=sqlite.prepare(sql).run(...values);return {success:true,meta:{changes:Number(r.changes)}}},async first(){return sqlite.prepare(sql).get(...values)||null}}}
const db={prepare:sql=>stmt(sql),async batch(items){return items.map(({sql,values})=>({success:true,results:sqlite.prepare(sql).all(...values)}))}};
const api={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:commit_sha==='codex/content-review-heartbeat'?hbHead:head}}),
 fetchFile:async({path,ref})=>{let obj;if(path==='config/content_review_worker_status.json'&&ref===v.input.expectedHead)obj=v.before;
 else if(path==='config/content_review_monitor_config.json')obj=config;else if(path==='config/content_review_detached_heartbeat.json')obj=v.heartbeat;
 else if(ref===commit&&saved[path])return ok({sha:hash(saved[path]),content:saved[path]});
 else return {isError:true,structuredContent:{error_code:'NOT_FOUND'}};const content=JSON.stringify(obj);return ok({sha:hash(content),content})},
 fetchCommitDetails:async({commit_sha})=>commit_sha===v.input.expectedHead?ok({sha:commit_sha,tree_sha:base,parents:[]}):ok({sha:commit,tree_sha:tree,parents:[v.input.expectedHead]}),
 createBlob:async({content})=>ok({sha:hash(content)}),
 createTree:async()=>{if(mode==='d1change')sqlite.prepare('INSERT INTO review_submissions (id,user_id,collection,batch,revision,accepted,rejected,payload_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?)')
  .run('submission','user','soups',1,1,0,1,'0'.repeat(64),new Date(v.now).toISOString());return ok({sha:tree})},
 commitOnBranch:async({additions})=>{commits++;if(mode==='ambiguous')throw Error('lost');for(const a of additions)saved[a.path]=a.content;head=commit;return ok({success:true,sha:commit})}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
let out;try{out={result:await writeNoWork({db,github:api,input:v.input,now:()=>v.now,read,heartbeatFactory:()=>async()=>({renewed:false})})}}catch(e){out={error:e.message}};
out.commits=commits;out.fence=sqlite.prepare('SELECT phase FROM content_review_write_fence').all().map(x=>x.phase);
out.submissions=sqlite.prepare('SELECT COUNT(*) AS n FROM review_submissions').get().n;
process.stdout.write(JSON.stringify(out));sqlite.close();"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('mode',['success','d1change','ambiguous'])
def test_no_work_release_uses_real_d1_fence_and_preserves_ambiguous_commit(tmp_path,mode):
    data=fixture(tmp_path,with_checkpoint=False);result=call(tmp_path,data)
    before=json.loads(git(tmp_path,'show',data[1]+':config/content_review_worker_status.json'))
    hb=json.loads(git(tmp_path,'show',data[3]+':config/content_review_detached_heartbeat.json'))
    from datetime import timedelta
    value={'now':int((data[0]+timedelta(seconds=10)).timestamp()*1000),'before':before,'heartbeat':hb,'snapshot':data[5],
           'input':{'expectedHead':data[1],'expectedMain':data[2],'owner':'worker','runId':'run','files':result['files']}}
    out=invoke(value,mode)
    if mode=='success':assert out['result']['candidate_processing'] is False and out['commits']==1 and out['fence']==[]
    if mode=='d1change':assert 'decisions changed' in out['error'].lower() and out['commits']==0 and out['fence']==[] and out['submissions']==1
    if mode=='ambiguous':assert 'ambiguous' in out['error'] and out['commits']==1 and out['fence']==['committing']
