'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {validateTransition}=require('../tools/content_review/lease_semantics.cjs');
const now=Date.parse('2026-11-07T12:00:00Z'), stamp='2026-11-07T12:00:00Z';
const owner='worker',runId='run-1';
function fixture(){
 const before={lease:null,source_attempts:{weekly:{at:'yesterday'}},last_error:'old',run_history:[],lease_history:[]};
 const scheduler={id:'Automation_replacement',observed_at:stamp,is_enabled:true,schedule:'hourly',
  last_run:{id:runId,recorded_status:'in_progress',scheduled_for:stamp,started_at:stamp,completed_at:null}};
 const after={...structuredClone(before),lease:{owner,run_id:runId,acquired_at:stamp,expires_at:'2026-11-07T12:30:00Z'},
  current_run:{run_id:runId,application_status:'running',started_at:stamp,scheduled_for:stamp,observed_at:stamp,
   scheduler,request_counts:{source:0,paid:0,openalex:0}},last_started_at:stamp,last_heartbeat_at:stamp};
 return {before,after,ctx:{owner,runId,now}};
}
test('valid acquisition preserves committed history and counters',()=>{
 const {before,after,ctx}=fixture();assert.deepEqual(validateTransition(before,after,'start',ctx),
  {status:'valid',native_observation_authenticated:false});
});
test('acquisition rejects unrelated changes, active leases and reused runs',()=>{
 for(const kind of ['counter','history','active','reused','retired','long']){
  const {before,after,ctx}=fixture();
  if(kind==='counter')after.source_attempts.weekly.at='fabricated';
  if(kind==='history')after.run_history.push({run_id:'lost'});
  if(kind==='active')before.lease={owner:'other',run_id:'other',expires_at:'2026-11-07T12:10:00Z'};
  if(kind==='reused')before.lease_history.push({run_id:ctx.runId});
  if(kind==='retired')after.current_run.scheduler.id='Automation_4eb2dd829aa88191b542d57f7008ebe3';
  if(kind==='long')after.lease.expires_at='2026-11-07T13:00:00Z';
  assert.throws(()=>validateTransition(before,after,'start',ctx));
 }
});
test('heartbeat may update only observation and scheduler evidence',()=>{
 const f=fixture(),before=structuredClone(f.after),after=structuredClone(f.after);
 const later='2026-11-07T12:00:10Z';after.current_run.observed_at=later;after.current_run.scheduler.observed_at=later;after.last_heartbeat_at=later;
 assert.equal(validateTransition(before,after,'heartbeat',{...f.ctx,now:now+10000}).status,'valid');
 after.lease.expires_at='2026-11-07T14:00:00Z';
 assert.throws(()=>validateTransition(before,after,'heartbeat',{...f.ctx,now:now+10000}),/unrelated state/);
});
test('abort preserves lease history and other state exactly',()=>{
 const f=fixture(),before=structuredClone(f.after),after=structuredClone(f.after);
 after.lease_history.push({...before.lease,status:'released',released_at:stamp});after.lease=null;
 after.current_run.application_status='failed';after.current_run.application_completed_at=stamp;
 after.current_run.failure_code='checkpoint_failure';after.last_error='checkpoint_failure';
 assert.equal(validateTransition(before,after,'abort',f.ctx).status,'valid');
 after.lease_history[0].owner='someone-else';
 assert.throws(()=>validateTransition(before,after,'abort',f.ctx),/unrelated state/);
});
