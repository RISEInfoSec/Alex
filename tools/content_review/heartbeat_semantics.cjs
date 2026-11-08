'use strict';

const RETIRED=new Set(['Automation_0ff7fb9b800481919b48ddb2593b8f88','Automation_4eb2dd829aa88191b542d57f7008ebe3',
 'Automation_88611f57231c81918d7ee01f7cd59c42','Automation_5bfb7f72636c819198bdbf0367081338']);
const time=v=>typeof v==='string'?Date.parse(v):NaN;
const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
const keys=['schema_version','review_head','owner','run_id','scheduler_id','started_at','lease_acquired_at','lease_expires_at','observed_at'].sort();
const {authorized:manualAuthorized}=require('./manual_authorization.cjs');

function validateHeartbeat({state,config,record,previous,reviewHead,owner,runId,now}){
 const lease=state?.lease,run=state?.current_run,scheduler=run?.scheduler,target=config?.target_automation_id;
 if(!object(state)||!object(config)||!object(lease)||!object(run)||!object(scheduler)||!object(record)||
    JSON.stringify(Object.keys(record).sort())!==JSON.stringify(keys)||!Number.isFinite(now)||
    typeof owner!=='string'||!owner||typeof runId!=='string'||!/^[a-zA-Z0-9-]+$/.test(runId)||
    !/^[0-9a-f]{40}$/.test(reviewHead||'')||typeof target!=='string'||!/^Automation_[a-zA-Z0-9]+$/.test(target)||RETIRED.has(target)||
    lease.owner!==owner||lease.run_id!==runId||run.run_id!==runId||run.application_status!=='running'||
    scheduler.id!==target||!(manualAuthorized(config,run,owner,runId,now)||
     (scheduler.kind!=='manual'&&scheduler.last_run?.id===runId&&scheduler.last_run?.recorded_status==='in_progress'))||
    record.schema_version!==1||record.review_head!==reviewHead||record.owner!==owner||record.run_id!==runId||
    record.scheduler_id!==target||record.started_at!==run.started_at||record.lease_acquired_at!==lease.acquired_at||
    record.lease_expires_at!==lease.expires_at||!Number.isFinite(time(record.observed_at))||time(record.observed_at)>now||
    now-time(record.observed_at)>40000||!Number.isFinite(time(run.started_at))||time(run.started_at)>time(record.observed_at)||
    !Number.isFinite(time(lease.acquired_at))||time(lease.acquired_at)>time(record.observed_at)||
    !Number.isFinite(time(lease.expires_at))||time(lease.expires_at)<=now||now-time(run.started_at)>=720000)
  throw new Error('Heartbeat does not match the committed worker and lease');
 if(previous!==null){
  if(!object(previous)||!Number.isFinite(time(previous.observed_at))||time(previous.observed_at)>time(record.observed_at)||
     (previous.run_id===runId&&(previous.owner!==owner||previous.lease_acquired_at!==lease.acquired_at)))
   throw new Error('Previous heartbeat conflicts with current lease');
 }
 return {status:'valid',native_observation_authenticated:false};
}
module.exports={validateHeartbeat};
