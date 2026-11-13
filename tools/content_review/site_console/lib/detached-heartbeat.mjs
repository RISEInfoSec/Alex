const time=value=>{const n=Date.parse(value||'');return Number.isFinite(n)?n:null;};

// A heartbeat is liveness evidence only. It cannot acquire a lease, establish
// processing, or validate a receipt. The review head must come from GitHub.
export function verifyDetachedHeartbeat(record,checkpoint,reviewHead,target,now=Date.now()){
 const fail=reason=>({verified:false,reason,observed_at:null});
 if(!/^[0-9a-f]{40}$/.test(reviewHead||'')||!target)return fail('Current review head or worker identity is unavailable.');
 const lease=checkpoint?.lease||{},run=checkpoint?.current_run||{},scheduler=run.scheduler||{};
 if(!record||record.schema_version!==1||record.review_head!==reviewHead||record.owner!==lease.owner||
    record.run_id!==lease.run_id||record.run_id!==run.run_id||record.scheduler_id!==target||scheduler.id!==target||
    scheduler.last_run?.id!==record.run_id||scheduler.last_run?.recorded_status!=='in_progress'||run.application_status!=='running'||
    record.started_at!==run.started_at||record.lease_acquired_at!==lease.acquired_at||record.lease_expires_at!==lease.expires_at)
  return fail('Heartbeat does not match the current review head and worker lease.');
 const observed=time(record.observed_at),started=time(run.started_at),acquired=time(lease.acquired_at),expires=time(lease.expires_at);
 if(observed===null||started===null||acquired===null||expires===null||observed<started||observed<acquired||
    observed>now||now-observed>40000||expires<=now)
  return fail('Heartbeat is stale or its lease is unavailable.');
 return {verified:true,reason:'Current lease-bound heartbeat was read from the separate ref.',observed_at:record.observed_at};
}
