'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createFence}=require('../tools/content_review/d1_live_fence.cjs');
const {fingerprint}=require('../tools/content_review/d1_fingerprint.cjs');

const head='a'.repeat(40),main='b'.repeat(40),clock=Date.parse('2026-11-06T23:50:20Z');
function snapshot(){return {submissions:[{id:'s',decision:'stored'}],decisions:[],jobs:[],
 read_evidence:{submissions:{complete:true,rows_received:1,truncated_values:0,omitted_columns:0},
                decisions:{complete:true,rows_received:0,truncated_values:0,omitted_columns:0},
                jobs:{complete:true,rows_received:0,truncated_values:0,omitted_columns:0}}};}
function fixture(){
 const initial=snapshot(),digest=fingerprint(initial);
 const state={lease:{owner:'worker',run_id:'run',expires_at:'2026-11-07T00:20:00Z'},
  current_run:{run_id:'run',application_status:'running',started_at:'2026-11-06T23:50:01Z',scheduled_for:'2026-11-06T23:50:00Z',observed_at:'2026-11-06T23:50:10Z',
               scheduler:{id:'Automation_worker123'}}};
 const native={id:'Automation_worker123',is_enabled:true,run_details:{last_run:{id:'run',recorded_status:'in_progress',started_at:'2026-11-06T23:50:01Z',scheduled_for:'2026-11-06T23:50:00Z'}}};
 return {proof:{expected_head:head,expected_main:main,d1_fingerprint_private:digest,lease_owner:'worker',run_id:'run'},
  bundle:{d1_fingerprint_private:digest,files:{'config/content_review_worker_status.json':JSON.stringify(state)}},
  readSnapshot:async()=>({snapshot:snapshot(),confirmed_snapshot:snapshot(),transactional_snapshot:false}),
  readReviewHead:async()=>head,readMainHead:async()=>main,readNative:async()=>native,fingerprint,now:()=>clock,native};
}
test('full current D1, native worker, heads and lease produce a private fence',async()=>{
 const f=fixture(),result=await createFence(f)({expectedHead:head});
 assert.equal(result.verified,true);assert.equal(result.d1_fingerprint_private,f.proof.d1_fingerprint_private);
 assert.equal(result.run_id,'run');assert.equal(result.main_head,main);
});
test('D1 changes, pagination omissions, or a changed head stop the fence',async()=>{
 for(const mode of ['changed','omitted','review','main']){
  const f=fixture();
  if(mode==='changed')f.readSnapshot=async()=>{const a=snapshot();a.submissions[0].decision='changed';return {snapshot:a,confirmed_snapshot:a,transactional_snapshot:false};};
  if(mode==='omitted')f.readSnapshot=async()=>{const a=snapshot();a.read_evidence.submissions.omitted_columns=1;return {snapshot:a,confirmed_snapshot:a,transactional_snapshot:false};};
  if(mode==='review')f.readReviewHead=async()=>'c'.repeat(40);
  if(mode==='main')f.readMainHead=async()=>'c'.repeat(40);
  await assert.rejects(createFence(f)({expectedHead:head}));
 }
});
test('late heartbeat, wrong native run or user action blocks checkpoint',async()=>{
 for(const mode of ['stale','native','approval']){
  const f=fixture();if(mode==='stale')f.now=()=>clock+41000;
  if(mode==='native')f.native.run_details.last_run.id='other';
  if(mode==='approval')f.native.run_details.latest_result={run_id:'run',requires_user_action:true};
  await assert.rejects(createFence(f)({expectedHead:head}));
 }
});
test('separate fresh heartbeat permits a long read without moving the review head',async()=>{
 const f=fixture(),state=JSON.parse(f.bundle.files['config/content_review_worker_status.json']);
 state.lease.acquired_at='2026-11-06T23:50:00Z';
 f.bundle.files['config/content_review_worker_status.json']=JSON.stringify(state);
 f.proof.heartbeat_head='c'.repeat(40);
 f.now=()=>clock+120000;
 const record={schema_version:1,review_head:head,owner:'worker',run_id:'run',scheduler_id:'Automation_worker123',
  started_at:state.current_run.started_at,lease_acquired_at:state.lease.acquired_at,lease_expires_at:state.lease.expires_at,
  observed_at:new Date(clock+119000).toISOString()};
 f.readHeartbeat=async()=>({ref:'codex/content-review-heartbeat',head:'d'.repeat(40),verified_blob:true,record});
 const result=await createFence(f)({expectedHead:head});assert.equal(result.heartbeat_at,record.observed_at);
 record.review_head='e'.repeat(40);await assert.rejects(createFence(f)({expectedHead:head}),/not verified/);
});
test('completion fences the owned pre-release state during the final reserve',async()=>{
 const f=fixture(),state=JSON.parse(f.bundle.files['config/content_review_worker_status.json']);
 state.current_run.started_at='2026-11-06T23:39:20Z';state.current_run.observed_at='2026-11-06T23:50:10Z';
 state.lease.expires_at='2026-11-06T23:51:00Z';
 f.native.run_details.last_run.started_at=state.current_run.started_at;
 f.proof.kind='run_completion';f.proof.fence_state=state;
 f.bundle.files['config/content_review_worker_status.json']=JSON.stringify({lease:null,current_run:{application_status:'complete'}});
 assert.equal((await createFence(f)({expectedHead:head})).verified,true);
 f.now=()=>Date.parse('2026-11-06T23:51:01Z');
 await assert.rejects(createFence(f)({expectedHead:head}),/expired/);
});
