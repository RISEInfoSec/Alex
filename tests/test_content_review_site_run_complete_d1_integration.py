from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_run_completion import fixture
from tests.test_content_review_site_checkpoint_readback import data as readback_data
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.run_completion import prepare

ROOT=Path(__file__).resolve().parents[1]


def request(repo):
    old=fixture(repo);now,checkpoint,main,_,native,snapshot,paths=old
    value=readback_data(repo,old)
    put(repo,'config/content_review_monitor_config.json',{'target_automation_id':'Automation_worker1',
                                                          'heartbeat_ref':'codex/content-review-heartbeat'})
    git(repo,'add','config/content_review_monitor_config.json');git(repo,'commit','-qm','monitor configuration')
    head=git(repo,'rev-parse','HEAD')
    state=json.loads(git(repo,'show',head+':config/content_review_worker_status.json'))
    heartbeat=prepare_heartbeat(state,head,'worker','run',at=now+timedelta(seconds=10))
    branch=git(repo,'symbolic-ref','--short','HEAD');git(repo,'checkout','-qb','heartbeat-for-completion')
    put(repo,'config/content_review_detached_heartbeat.json',heartbeat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    proposal=prepare(repo,head,main,hb,native,snapshot,deepcopy(snapshot),'worker','run',paths,at=now+timedelta(seconds=10))
    for path in ['config/weekly_review_manifest.json','config/content_review_candidate_lifecycle.json',
                 'config/content_review_preflight_status.json','config/content_review_worker_status.json',
                 'config/content_review_monitor_config.json',paths[0]]:
        raw=subprocess.check_output(['git','-C',str(repo),'show',head+':'+path])
        sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        value['files'][head+':'+path]={'sha':sha,'content':raw.decode('utf8')}
    value['input']={'expectedHead':head,'expectedMain':main,'owner':'worker','runId':'run',
                    'checkpointCommits':{paths[0]:checkpoint},'files':proposal['files']}
    value.update({'checkpointCommit':checkpoint,'currentTree':git(repo,'rev-parse',head+'^{tree}'),
                  'heartbeat':heartbeat,'now':int((now.timestamp()+10)*1000)})
    return value


def invoke(value,mode):
    code=r"""import fs from 'node:fs';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {writeCompletion} from './tools/content_review/site_run_complete_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const sha256=s=>crypto.createHash('sha256').update(s).digest('hex'),ok=x=>({isError:false,structuredContent:x});
let head=v.input.expectedHead,heartbeatHead='e'.repeat(40),heartbeatContent=JSON.stringify(v.heartbeat),heartbeatUpdates=0,commits=0;
const commit='d'.repeat(40),tree='c'.repeat(40);
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
 fetchCommitDetails:async({commit_sha})=>{
  if(commit_sha===v.input.expectedHead)return ok({sha:commit_sha,tree_sha:v.currentTree,parents:[v.checkpointCommit]});
  if(commit_sha===v.checkpointCommit)return ok({sha:commit_sha,tree_sha:v.tree,parents:[v.source]});
  if(commit_sha===v.source||commit_sha===heartbeatHead)return ok({sha:commit_sha,tree_sha:v.baseTree,parents:[]});
  if(commit_sha===commit)return ok({sha:commit,tree_sha:tree,parents:[v.input.expectedHead]});return {isError:true}},
 fetchFile:async({path,ref})=>{
  if(path==='config/content_review_detached_heartbeat.json'&&ref===heartbeatHead)return ok({sha:hash(heartbeatContent),content:heartbeatContent});
  if(ref===commit&&saved[path])return ok({sha:hash(saved[path]),content:saved[path]});
  const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 streamBlob:async({sha,onChunk})=>{const data=v.blobs[sha];if(data===undefined)return {isError:true};const bytes=Buffer.from(data);
  for(let i=0;i<bytes.length;i+=7)await onChunk(bytes.subarray(i,i+7));return ok({sha,size:bytes.length,sha256:sha256(bytes)})},
 createBlob:async({content})=>ok({sha:hash(content)}),
 createTree:async({tree_elements})=>{
  if(tree_elements.length===5)return ok({sha:v.tree});
  if(mode==='d1change')sqlite.prepare('INSERT INTO review_submissions VALUES (?,?,?,?,?,?,?,?,?)')
   .run('new-submission','user','weekly',1,1,0,1,'0'.repeat(64),v.heartbeat.started_at);
  return ok({sha:tree})},
 commitOnBranch:async({branch_name,additions})=>{if(branch_name==='codex/content-review-heartbeat'){
   heartbeatUpdates++;heartbeatContent=additions[0].content;heartbeatHead='f'.repeat(40);return ok({success:true,sha:heartbeatHead});}
  commits++;if(mode==='ambiguous')throw Error('lost');for(const x of additions)saved[x.path]=x.content;head=commit;return ok({success:true,sha:commit})}};
let outcome;try{outcome={result:await writeCompletion({db,github:api,input:v.input,now:()=>v.now})}}catch(e){outcome={error:e.message}}
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
def test_completion_reaudits_under_real_d1_fence(tmp_path,mode):
    result=invoke(request(tmp_path),mode)
    if mode=='success':
        assert result.get('result',{}).get('status')=='committed_and_read_back',result
        assert result['commits']==1 and result['heartbeat_updates']==1 and result['fence']==[]
        assert result['result']['native_completion_verified'] is False and result['result']['publication_verified'] is False
    if mode=='d1change':assert 'decisions changed' in result['error'].lower() and result['commits']==0 and result['fence']==[]
    if mode=='ambiguous':assert 'ambiguous' in result['error'] and result['commits']==1 and result['fence']==['committing'] and result['blocked'] is True
