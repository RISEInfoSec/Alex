import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {controlFence} from '../tools/content_review/d1_fence_service.mjs';
import {SQL} from '../tools/content_review/d1_write_fence.mjs';
import fingerprints from '../tools/content_review/d1_fingerprint.cjs';

const at=Date.parse('2026-11-07T19:00:20Z'),review='a'.repeat(40),main='b'.repeat(40),hb='c'.repeat(40),next='d'.repeat(40);
const blob=text=>createHash('sha1').update(`blob ${Buffer.byteLength(text)}\0`).update(text).digest('hex');
const ok=x=>({isError:false,structuredContent:x});
function fixture(){
 let lock=null,reviewHead=review,mainHead=main;
 const snap={submissions:[],decisions:[],jobs:[],read_evidence:{}};
 const input={action:'acquire',operationId:'op-1',owner:'worker',runId:'run-1',expectedHead:review,expectedMain:main,
  expectedTree:'e'.repeat(40),receiptPath:'config/content_review_run_receipts/run-1.json',receiptBlob:'f'.repeat(40),
  d1Fingerprint:fingerprints.fingerprint(snap)};
 const lease={owner:'worker',run_id:'run-1',acquired_at:'2026-11-07T19:00:00Z',expires_at:'2026-11-07T19:20:00Z'};
 const run={run_id:'run-1',application_status:'running',started_at:'2026-11-07T19:00:00Z',scheduled_for:'2026-11-07T19:00:00Z',
  scheduler:{id:'Automation_worker1',is_enabled:true,observed_at:'2026-11-07T19:00:20Z',last_run:{id:'run-1',recorded_status:'in_progress',started_at:'2026-11-07T19:00:00Z',scheduled_for:'2026-11-07T19:00:00Z'}}};
 const state={lease,current_run:run},config={target_automation_id:'Automation_worker1',heartbeat_ref:'codex/content-review-heartbeat'};
 const heartbeat={schema_version:1,review_head:review,owner:'worker',run_id:'run-1',scheduler_id:'Automation_worker1',
  started_at:run.started_at,lease_acquired_at:lease.acquired_at,lease_expires_at:lease.expires_at,observed_at:'2026-11-07T19:00:20Z'};
 const db={prepare(sql){return {async first(){return lock;},bind(...v){return {async run(){
  if(sql===SQL.acquire){if(lock)return {success:true,meta:{changes:0}};lock={operation_id:v[0],owner:v[1],run_id:v[2],expected_head:v[3],expected_tree:v[4],receipt_path:v[5],receipt_blob_sha:v[6],phase:'preparing'};return {success:true,meta:{changes:1}};}
  const match=lock&&['operation_id','owner','run_id','expected_head','expected_tree','receipt_path','receipt_blob_sha'].every((k,i)=>lock[k]===v[i]);
  if(sql===SQL.beginCommit&&match&&lock.phase==='preparing'){lock.phase='committing';return {success:true,meta:{changes:1}};}
  if(sql===SQL.abortPreparation&&match&&lock.phase==='preparing'){lock=null;return {success:true,meta:{changes:1}};}
  if(sql===SQL.releaseVerified&&match&&lock.phase==='committing'){lock=null;return {success:true,meta:{changes:1}};}
  return {success:true,meta:{changes:0}};
 }};}};}};
 const github={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?mainHead:commit_sha==='codex/content-review-heartbeat'?hb:reviewHead}}),
  fetchFile:async({path})=>{
   if(path===input.receiptPath)return ok({sha:input.receiptBlob});
   const obj=path.endsWith('worker_status.json')?state:path.endsWith('monitor_config.json')?config:heartbeat;
   const content=JSON.stringify(obj);return ok({content,sha:blob(content)});
  },fetchCommitDetails:async()=>ok({sha:next,tree_sha:input.expectedTree,parents:[review]})};
 const inspect=async()=>({status:lock?'held':'idle'});
 const readSnapshot=async({heartbeat:beat})=>{await beat();return {snapshot:snap,confirmed_snapshot:structuredClone(snap),transactional_snapshot:false};};
 return {db,github,input,state,config,heartbeat,snap,inspect,readSnapshot,now:()=>at,
  current:()=>lock,setReview:value=>{reviewHead=value;},setMain:value=>{mainHead=value;}};
}
const call=(f,action,extra={})=>controlFence({...f,input:{...f.input,action,...extra}});

test('live-bound lease, heartbeat and matching D1 enter the committing fence',async()=>{
 const f=fixture();assert.equal((await call(f,'acquire')).status,'acquired');
 assert.equal(f.current().phase,'preparing');assert.equal((await call(f,'begin')).status,'committing');
 assert.equal(f.current().phase,'committing');assert.equal((await call(f,'abort')).status,'not_changed');
});
test('changed decisions fail before commit and a preparing fence can be aborted',async()=>{
 const f=fixture();await call(f,'acquire');f.snap.jobs.push({id:'private-id'});
 await assert.rejects(call(f,'begin'),/decisions changed/);assert.equal(f.current().phase,'preparing');
 assert.equal((await call(f,'abort')).status,'aborted');assert.equal(f.current(),null);
});
test('retired target, stale heartbeat or changed source never acquire a fence',async()=>{
 for(const mode of ['retired','stale','head']){
  const f=fixture();if(mode==='retired')f.config.target_automation_id='Automation_4eb2dd829aa88191b542d57f7008ebe3';
  if(mode==='stale')f.heartbeat.observed_at='2026-11-07T18:58:00Z';if(mode==='head')f.setReview('9'.repeat(40));
  await assert.rejects(call(f,'acquire'));assert.equal(f.current(),null);
 }
});
test('a fresh detached heartbeat permits a long-running native-bound worker',async()=>{
 const f=fixture();f.now=()=>at+180000;f.heartbeat.observed_at='2026-11-07T19:03:20Z';
 assert.equal((await call(f,'acquire')).status,'acquired');
});
test('a scheduler observation predating its run is rejected',async()=>{
 const f=fixture();f.state.current_run.scheduler.observed_at='2026-11-07T18:59:59Z';
 await assert.rejects(call(f,'acquire'),/worker lease or heartbeat/);assert.equal(f.current(),null);
});
test('manual work requires an exact unexpired permit and still fences changing decisions',async()=>{
 const make=()=>{const f=fixture();f.state.current_run.scheduled_for=null;
  f.state.current_run.scheduler={id:'Automation_worker1',kind:'manual',authorization:'owner_request',observed_at:'2026-11-07T19:00:20Z'};
  f.config.manual_run_authorization={run_id:'run-1',owner:'worker',scope:'duplicate_only',expires_at:'2026-11-07T19:14:00Z'};return f;};
 const f=make();assert.equal((await call(f,'acquire')).status,'acquired');f.snap.jobs.push({id:'private'});
 await assert.rejects(call(f,'begin'),/decisions changed/);assert.equal((await call(f,'abort')).status,'aborted');
 for(const mode of ['missing','expired','run','scope','owner']){
  const q=make();if(mode==='missing')delete q.config.manual_run_authorization;
  if(mode==='expired')q.config.manual_run_authorization.expires_at='2026-11-07T19:00:10Z';
  if(mode==='run')q.config.manual_run_authorization.run_id='other';if(mode==='scope')q.config.manual_run_authorization.scope='publication';
  if(mode==='owner')q.config.manual_run_authorization.owner='other';
  await assert.rejects(call(q,'acquire'));assert.equal(q.current(),null,mode);
 }
});
test('a retired target is rejected without consulting the heartbeat ref',async()=>{
 const f=fixture();f.config.target_automation_id='Automation_4eb2dd829aa88191b542d57f7008ebe3';
 const original=f.github.fetchCommit;let heartbeatReads=0;
 f.github.fetchCommit=async args=>{if(args.commit_sha==='codex/content-review-heartbeat')heartbeatReads++;return original(args);};
 await assert.rejects(call(f,'acquire'),/worker lease or heartbeat/);
 assert.equal(heartbeatReads,0);assert.equal(f.current(),null);
});
test('only a verified matching committed tree releases a committing fence',async()=>{
 const f=fixture();await call(f,'acquire');await call(f,'begin');
 await assert.rejects(call(f,'release'));assert.equal(f.current().phase,'committing');
 f.setReview(next);assert.equal((await call(f,'release')).status,'confirmed_and_released');assert.equal(f.current(),null);
});
test('unknown fields and arbitrary operations are rejected',async()=>{
 const f=fixture();await assert.rejects(call(f,'acquire',{extra:'unsafe'}),/Invalid fence request/);
 await assert.rejects(call(f,'commit'),/Invalid fence request/);assert.equal(f.current(),null);
});
