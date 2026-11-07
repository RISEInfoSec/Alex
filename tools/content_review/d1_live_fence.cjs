'use strict';

// A fail-closed final checkpoint fence. The caller injects independently
// authenticated native/GitHub observations and the complete Sites D1 reader.
// This module neither acquires a lease nor writes data. A full double read is
// not transactional; concurrent D1 changes after the check remain possible.
const WORKER='config/content_review_worker_status.json';
const H=/^[0-9a-f]{40}$/, H256=/^[0-9a-f]{64}$/;

function complete(snapshot){
  if(!snapshot||!snapshot.read_evidence)return false;
  return ['submissions','decisions','jobs'].every(k=>{
    const rows=snapshot[k],e=snapshot.read_evidence[k];
    return Array.isArray(rows)&&e&&e.complete===true&&e.rows_received===rows.length&&e.truncated_values===0&&e.omitted_columns===0;
  });
}

function createFence({proof,bundle,readSnapshot,readReviewHead,readMainHead,readNative,readHeartbeat,fingerprint,now=()=>Date.now()}){
  if(!proof||!bundle||!H.test(proof.expected_head||'')||!H.test(proof.expected_main||'')||
     !H256.test(proof.d1_fingerprint_private||'')||bundle.d1_fingerprint_private!==proof.d1_fingerprint_private||
     typeof proof.lease_owner!=='string'||!proof.lease_owner||typeof proof.run_id!=='string'||!proof.run_id||
     ![readSnapshot,readReviewHead,readMainHead,readNative,fingerprint,now].every(f=>typeof f==='function'))
    throw new Error('Guarded checkpoint and independent live readers are required');
  if(proof.heartbeat_head!=null&&(!H.test(proof.heartbeat_head)||typeof readHeartbeat!=='function'))
    throw new Error('Separate heartbeat reader is required');
  let state;
  try{state=JSON.parse(bundle.files[WORKER]);}catch{throw new Error('Guarded worker state is unavailable');}
  const lease=state.lease||{},run=state.current_run||{},scheduler=run.scheduler||{};
  if(lease.owner!==proof.lease_owner||lease.run_id!==proof.run_id||run.run_id!==proof.run_id||
     run.application_status!=='running'||typeof scheduler.id!=='string'||!scheduler.id)
    throw new Error('Guarded worker identity is inconsistent');
  return async function fence({expectedHead}){
    if(expectedHead!==proof.expected_head)throw new Error('Fence head differs from guarded checkpoint');
    const read=await readSnapshot();
    if(!read||!complete(read.snapshot)||!complete(read.confirmed_snapshot)||read.transactional_snapshot!==false)
      throw new Error('Complete non-transactional D1 reads are unavailable');
    const a=fingerprint(read.snapshot),b=fingerprint(read.confirmed_snapshot);
    if(a!==b||a!==proof.d1_fingerprint_private)throw new Error('D1 changed since checkpoint preparation');
    const [review,main,native,detached]=await Promise.all([readReviewHead(),readMainHead(),readNative(scheduler.id),
      proof.heartbeat_head!=null?readHeartbeat():Promise.resolve(null)]);
    const last=native?.run_details?.last_run, latest=native?.run_details?.latest_result;
    if(review!==proof.expected_head||main!==proof.expected_main)throw new Error('A source branch head changed');
    if(!native||native.id!==scheduler.id||native.is_enabled!==true||last?.id!==proof.run_id||
       last.recorded_status!=='in_progress'||Date.parse(last.started_at)!==Date.parse(run.started_at)||
       !Number.isFinite(Date.parse(last.scheduled_for))||Date.parse(last.scheduled_for)!==Date.parse(run.scheduled_for)||
       (latest?.run_id===proof.run_id&&latest?.requires_user_action===true))
      throw new Error('Native worker is not confirmed in progress');
    let heartbeat=run.observed_at;
    if(proof.heartbeat_head!=null){
      const r=detached?.record;
      if(!detached||detached.ref!=='codex/content-review-heartbeat'||!H.test(detached.head||'')||detached.verified_blob!==true||
         !r||r.schema_version!==1||r.review_head!==review||r.owner!==lease.owner||r.run_id!==run.run_id||
         r.scheduler_id!==scheduler.id||r.started_at!==run.started_at||r.lease_acquired_at!==lease.acquired_at||
         r.lease_expires_at!==lease.expires_at)
        throw new Error('Separate heartbeat is not verified against the current lease');
      heartbeat=r.observed_at;
    }
    const time=now(), observed=Date.parse(heartbeat), expiry=Date.parse(lease.expires_at), started=Date.parse(run.started_at);
    if(!Number.isFinite(time)||!Number.isFinite(observed)||observed>time||time-observed>40000||
       !Number.isFinite(expiry)||expiry-time<=120000||!Number.isFinite(started)||started>time||
       time-started>(proof.kind==='source_result'?720000:600000))
      throw new Error('Lease heartbeat or work budget expired during D1 read');
    return {verified:true,expectedHead:review,main_head:main,d1_fingerprint_private:a,
            lease_owner:lease.owner,run_id:run.run_id,heartbeat_at:heartbeat,
            lease_expires_at:lease.expires_at,started_at:run.started_at,checked_at:new Date(time).toISOString()};
  };
}
module.exports={createFence};
