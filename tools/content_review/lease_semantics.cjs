'use strict';

// Validate only state transitions. The caller must separately authenticate the
// native scheduler observation; a structurally valid observation is not proof
// that a native run actually occurred.
const RETIRED=new Set(['Automation_0ff7fb9b800481919b48ddb2593b8f88','Automation_4eb2dd829aa88191b542d57f7008ebe3',
 'Automation_88611f57231c81918d7ee01f7cd59c42','Automation_5bfb7f72636c819198bdbf0367081338']);
const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
const time=v=>typeof v==='string'?Date.parse(v):NaN;
const sameTime=(a,b)=>Number.isFinite(time(a))&&time(a)===time(b);
const required=(v,message)=>{if(!v)throw new Error(message);};
const keys=(o,allowed)=>object(o)&&equal(Object.keys(o).sort(),allowed.slice().sort());

function native(run,runId,now){
 const s=run?.scheduler,n=s?.last_run;
 required(keys(s,['id','observed_at','is_enabled','schedule','last_run'])&&
  typeof s.id==='string'&&/^Automation_[a-zA-Z0-9]+$/.test(s.id)&&!RETIRED.has(s.id)&&s.is_enabled===true&&
  keys(n,['id','recorded_status','scheduled_for','started_at','completed_at'])&&n.id===runId&&
  n.recorded_status==='in_progress'&&n.completed_at===null&&typeof s.schedule==='string'&&
  sameTime(n.started_at,run.started_at)&&sameTime(n.scheduled_for,run.scheduled_for)&&
  sameTime(s.observed_at,run.observed_at)&&Number.isFinite(time(run.observed_at))&&
  time(run.observed_at)<=now&&now-time(run.observed_at)<=40000&&
  Number.isFinite(time(run.started_at))&&time(run.started_at)<=now&&now-time(run.started_at)<600000&&
  Number.isFinite(time(run.scheduled_for))&&time(run.started_at)>=time(run.scheduled_for)-300000&&
  time(run.scheduled_for)<=now+300000,'Native observation shape or timing is invalid');
}

function validateTransition(before,after,phase,{owner,runId,now,detachedHeartbeat=null,reviewHead=null}){
 required(object(before)&&object(after)&&typeof owner==='string'&&owner&&typeof runId==='string'&&
  /^[a-zA-Z0-9-]+$/.test(runId)&&Number.isFinite(now),'Lease state or identity invalid');
 const current=before.current_run,lease=before.lease,run=after.current_run,expected=structuredClone(before);
 const oldHistory=before.lease_history===undefined?[]:before.lease_history;
 required(Array.isArray(oldHistory)&&oldHistory.every(object),'Lease history invalid');
 if(phase==='start'){
  required((lease===null||lease===undefined||object(lease))&&(!lease||
   (typeof lease.owner==='string'&&lease.owner&&typeof lease.run_id==='string'&&lease.run_id!==runId&&
    Number.isFinite(time(lease.expires_at))&&time(lease.expires_at)<=now))&&
   !oldHistory.some(x=>x.run_id===runId),'Existing lease is active, invalid or reused');
  const fresh=after.lease;
  required(keys(fresh,['owner','run_id','acquired_at','expires_at'])&&fresh.owner===owner&&fresh.run_id===runId&&
   Number.isFinite(time(fresh.acquired_at))&&time(fresh.acquired_at)<=now&&now-time(fresh.acquired_at)<=40000&&
   time(fresh.expires_at)-time(fresh.acquired_at)===1800000,'Acquired lease is invalid');
  if(lease){expected.lease_history??=[];expected.lease_history.push({...lease,status:'expired',expiry_observed_at:fresh.acquired_at});}
  else expected.lease_history??=[];
  const history=before.run_history===undefined?[]:before.run_history;
  required(Array.isArray(history)&&history.every(x=>object(x)&&typeof x.run_id==='string'&&x.run_id)&&
   !history.some(x=>x.run_id===runId),'Run history invalid or reused');
  if(current!==null&&current!==undefined){
   required(object(current)&&current.run_id&&current.run_id!==runId&&['complete','failed','deferred','running'].includes(current.application_status),
    'Previous run invalid or reused');
   if(current.application_status==='running')required((expected.lease_history||[]).some(x=>x.run_id===current.run_id&&x.status==='expired'),
    'Previous running run lacks expired lease evidence');
   const matches=history.filter(x=>x.run_id===current.run_id);
   required(matches.length<=1&&(!matches.length||equal(matches[0],current)),'Previous run history conflicts');
   if(!matches.length){expected.run_history??=[];expected.run_history.push(structuredClone(current));}
  }
  const pending=current?.pending_source_request;
  if(pending!==undefined&&pending!==null)required(object(pending)&&typeof pending.origin_run_id==='string'&&
   /^[0-9a-f]{64}$/.test(pending.request_id||'')&&
   (pending.origin_run_id===current.run_id||history.some(x=>x.run_id===pending.origin_run_id&&equal(x.pending_source_request,pending))),
   'Pending source request cannot be preserved');
  const runKeys=['run_id','application_status','started_at','scheduled_for','observed_at','request_counts','scheduler'];
  if(pending!==undefined&&pending!==null)runKeys.push('pending_source_request');
  required(keys(run,runKeys)&&run.run_id===runId&&run.application_status==='running'&&
   equal(run.request_counts,{source:0,paid:0,openalex:0})&&
   (pending===undefined||pending===null||equal(run.pending_source_request,pending)), 'New run state invalid');
  native(run,runId,now);
  required(sameTime(run.observed_at,fresh.acquired_at),'Lease and run timestamps differ');
  expected.lease=structuredClone(fresh);expected.current_run=structuredClone(run);
  expected.last_started_at=run.scheduler.last_run.started_at;expected.last_heartbeat_at=run.observed_at;
 }else if(phase==='heartbeat'){
  const h=detachedHeartbeat,priorFresh=Number.isFinite(time(current?.observed_at))&&time(current.observed_at)<=now&&now-time(current.observed_at)<=40000;
  const detachedFresh=object(h)&&/^[0-9a-f]{40}$/.test(reviewHead||'')&&h.schema_version===1&&h.review_head===reviewHead&&
   h.owner===owner&&h.run_id===runId&&h.scheduler_id===current?.scheduler?.id&&h.started_at===current?.started_at&&
   h.lease_acquired_at===lease?.acquired_at&&h.lease_expires_at===lease?.expires_at&&
   Number.isFinite(time(h.observed_at))&&time(h.observed_at)<=now&&now-time(h.observed_at)<=40000&&
   time(h.observed_at)>=time(current?.observed_at)&&time(h.observed_at)>=time(lease?.acquired_at)&&time(h.observed_at)>=time(current?.started_at);
  required(object(lease)&&lease.owner===owner&&lease.run_id===runId&&time(lease.expires_at)>now&&
   object(current)&&current.run_id===runId&&current.application_status==='running'&&
   Number.isFinite(time(current.observed_at))&&time(current.observed_at)<=now&&(priorFresh||detachedFresh)&&
   time(run?.observed_at)>=time(current.observed_at),'Heartbeat lease or previous observation invalid');
  native(run,runId,now);
  expected.current_run.observed_at=run.observed_at;expected.current_run.scheduler=structuredClone(run.scheduler);
  expected.last_heartbeat_at=run.observed_at;
 }else if(phase==='abort'){
  const failed=run?.failure_code,done=run?.application_completed_at;
  required(object(lease)&&lease.owner===owner&&lease.run_id===runId&&time(lease.expires_at)>now&&
   Number.isFinite(time(lease.acquired_at))&&time(lease.acquired_at)<=time(done)&&
   (!lease.renewed_at||time(lease.renewed_at)<=time(done))&&object(current)&&current.run_id===runId&&
   current.application_status==='running'&&['access_unavailable','checkpoint_failure','deadline','reconciliation_hold','heartbeat_stale'].includes(failed)&&
   Number.isFinite(time(done))&&time(done)<=now&&now-time(done)<=40000,'Lease abort invalid');
  expected.lease_history??=[];expected.lease_history.push({...lease,status:'released',released_at:done});
  expected.lease=null;expected.current_run.application_status='failed';expected.current_run.application_completed_at=done;
  expected.current_run.failure_code=failed;expected.last_error=failed;
 }else if(phase==='expire'){
  const done=run?.application_completed_at;
  required(object(lease)&&lease.owner===owner&&lease.run_id===runId&&Number.isFinite(time(lease.acquired_at))&&
   Number.isFinite(time(lease.expires_at))&&time(lease.acquired_at)<time(lease.expires_at)&&time(lease.expires_at)<=now&&
   object(current)&&current.run_id===runId&&current.application_status==='running'&&run?.failure_code==='reconciliation_hold'&&
   Number.isFinite(time(done))&&time(done)<=now&&now-time(done)<=40000&&!oldHistory.some(x=>x.run_id===runId),
   'Expired lease reconciliation invalid');
  expected.lease_history??=[];expected.lease_history.push({...lease,status:'expired',expiry_observed_at:done});
  expected.lease=null;expected.current_run.application_status='failed';expected.current_run.application_completed_at=done;
  expected.current_run.failure_code='reconciliation_hold';expected.last_error='reconciliation_hold';
 }else throw new Error('Unknown lease transition');
 required(equal(expected,after),'Lease transition changes unrelated state or loses history');
 return {status:'valid',native_observation_authenticated:false};
}

module.exports={validateTransition};
