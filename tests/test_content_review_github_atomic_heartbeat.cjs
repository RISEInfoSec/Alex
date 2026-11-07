'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const crypto=require('node:crypto');
const {commitHeartbeat}=require('../tools/content_review/github_atomic_heartbeat.cjs');
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});
const review='a'.repeat(40),old='b'.repeat(40),tree='c'.repeat(40),newTree='d'.repeat(40),next='e'.repeat(40);
const path='config/content_review_detached_heartbeat.json',clock=Date.parse('2026-11-07T00:00:30Z');
function fixture(){
 let reviewHead=review,hbHead=old,content='',updates=0;
 const record={schema_version:1,review_head:review,owner:'worker',run_id:'run',scheduler_id:'Automation_worker',
  started_at:'2026-11-07T00:00:00Z',lease_acquired_at:'2026-11-07T00:00:00Z',lease_expires_at:'2026-11-07T00:30:00Z',observed_at:'2026-11-07T00:00:30Z'};
 const text=JSON.stringify(record)+'\n';
 const worker={lease:{owner:'worker',run_id:'run',acquired_at:record.lease_acquired_at,expires_at:record.lease_expires_at},
  current_run:{run_id:'run',application_status:'running',started_at:record.started_at,
   scheduler:{id:'Automation_worker',last_run:{id:'run',recorded_status:'in_progress'}}}};
 const config={target_automation_id:'Automation_worker'};
 const api={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='codex/soups-corpus-review'?reviewHead:hbHead}}),
  fetchFile:async({ref,path:requested})=>{if(requested==='config/content_review_worker_status.json'||requested==='config/content_review_monitor_config.json'){
   const content=JSON.stringify(requested.includes('worker_status')?worker:config);return ok({sha:hash(content),content});}
   return ref===old?{isError:true,structuredContent:{error_code:'NOT_FOUND'}}:ok({sha:hash(content),content});},
  createBlob:async({content:c})=>{content=c;return ok({sha:hash(c)});},
  createTree:async({base_tree_sha,tree_elements})=>{assert.equal(base_tree_sha,tree);assert.equal(tree_elements[0].path,path);return ok({sha:newTree});},
  createCommit:async({parent_sha})=>{assert.equal(parent_sha,old);return ok({sha:next});},
  updateRef:async({branch_name,expected_sha,sha,force})=>{updates++;assert.equal(branch_name,'codex/content-review-heartbeat');assert.equal(force,false);
   if(expected_sha!==hbHead)return {isError:true};hbHead=sha;return ok({success:true});}};
 return {api,linkId:'account',now:()=>clock,proposal:{path,review_head:review,heartbeat_head:old,base_tree_sha:tree,
  base_blob:null,content:text,blob_sha:hash(text),owner:'worker',run_id:'run',writes:0,requires_expected_head_and_readback:true},
  updates:()=>updates,setReview:v=>{reviewHead=v;},setHeartbeat:v=>{hbHead=v;},worker,config};
}
test('heartbeat advances only the independent ref and verifies readback',async()=>{
 const f=fixture(),r=await commitHeartbeat(f);assert.equal(r.heartbeat_head,next);assert.equal(r.review_head,review);assert.equal(f.updates(),1);
});
test('Site-backed heartbeat targets only the heartbeat ref with expected head',async()=>{
 const f=fixture();let calls=0;
 f.api.commitOnBranch=async({branch_name,expected_sha,additions})=>{
  calls++;assert.equal(branch_name,'codex/content-review-heartbeat');assert.equal(expected_sha,old);
  assert.deepEqual(additions,[{path,content:f.proposal.content}]);f.setHeartbeat(next);return ok({success:true,sha:next});
 };
 const result=await commitHeartbeat(f);assert.equal(result.heartbeat_head,next);assert.equal(calls,1);
});
test('ambiguous Site heartbeat is not retried',async()=>{
 const f=fixture();let calls=0;f.api.commitOnBranch=async()=>{calls++;throw Error('disconnected');};
 await assert.rejects(commitHeartbeat(f),/ambiguous; reconcile heartbeat branch/);assert.equal(calls,1);
});
test('stale records, changed review heads and competing heartbeats stop before write',async()=>{
 for(const kind of ['stale','review','heartbeat']){
  const f=fixture();if(kind==='stale')f.now=()=>clock+41000;if(kind==='review')f.setReview('f'.repeat(40));if(kind==='heartbeat')f.setHeartbeat('f'.repeat(40));
  await assert.rejects(commitHeartbeat(f));assert.equal(f.updates(),0);
 }
});
test('ambiguous heartbeat updates are never retried automatically',async()=>{
 const f=fixture();let calls=0;f.api.updateRef=async()=>{calls++;throw new Error('disconnected');};
 await assert.rejects(commitHeartbeat(f),/outcome is ambiguous; reconcile/);assert.equal(calls,1);
});
test('a forged lease or unrelated configured worker is rejected before any GitHub blob write',async()=>{
 for(const kind of ['lease','configuration','unrelated']){
  const f=fixture();
  if(kind==='lease')f.worker.lease.owner='other';
  if(kind==='configuration')f.config.target_automation_id='Automation_another';
  if(kind==='unrelated'){const record=JSON.parse(f.proposal.content);record.unrelated=true;f.proposal.content=JSON.stringify(record);f.proposal.blob_sha=hash(f.proposal.content);}
  let blobs=0;f.api.createBlob=async()=>{blobs++;throw Error('unexpected');};
  await assert.rejects(commitHeartbeat(f),/does not match the committed worker and lease/);
  assert.equal(blobs,0);assert.equal(f.updates(),0);
 }
});
