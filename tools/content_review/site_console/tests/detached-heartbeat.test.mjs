import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {verifyDetachedHeartbeat} from '../lib/detached-heartbeat.mjs';
import {readOperations} from '../lib/operations-source.mjs';

const now=Date.parse('2026-11-07T00:00:30Z'),head='a'.repeat(40),target='Automation_worker';
const fixture=()=>({
 checkpoint:{lease:{owner:'worker',run_id:'run',acquired_at:'2026-11-07T00:00:00Z',expires_at:'2026-11-07T00:30:00Z'},
  current_run:{run_id:'run',application_status:'running',started_at:'2026-11-07T00:00:00Z',scheduler:{id:target,last_run:{id:'run',recorded_status:'in_progress'}}}},
 record:{schema_version:1,review_head:head,owner:'worker',run_id:'run',scheduler_id:target,started_at:'2026-11-07T00:00:00Z',
  lease_acquired_at:'2026-11-07T00:00:00Z',lease_expires_at:'2026-11-07T00:30:00Z',observed_at:'2026-11-07T00:00:20Z'}});

test('accepts only a fresh heartbeat bound to the current review lease',()=>{
 const {record,checkpoint}=fixture();assert.equal(verifyDetachedHeartbeat(record,checkpoint,head,target,now).verified,true);
 for(const change of [{review_head:'b'.repeat(40)},{owner:'other'},{run_id:'other'},{scheduler_id:'Automation_old'},
                      {lease_expires_at:'2026-11-07T00:20:00Z'},{observed_at:'2026-11-06T23:59:00Z'}])
  assert.equal(verifyDetachedHeartbeat({...record,...change},checkpoint,head,target,now).verified,false);
 assert.equal(verifyDetachedHeartbeat(record,checkpoint,'',target,now).verified,false);
});

test('a terminal native run or expired lease cannot look active',()=>{
 const {record,checkpoint}=fixture();checkpoint.current_run.scheduler.last_run.recorded_status='completed';
 assert.equal(verifyDetachedHeartbeat(record,checkpoint,head,target,now).verified,false);
 assert.equal(verifyDetachedHeartbeat(record,checkpoint,head,target,now+31*60000).verified,false);
});

test('operations uses the pinned review head and marks a stale separate heartbeat degraded',async()=>{
 const id='1d1d1111-2222-3333-4444-555555555555',started='2026-11-07T00:00:00Z';
 const config={automation_id:'Automation_monitor',target_automation_id:target,heartbeat_ref:'codex/content-review-heartbeat',
  schedule:'BEGIN:VEVENT\nDTSTART:20261107T000000Z\nRRULE:FREQ=HOURLY\nEND:VEVENT'};
 const scheduler={id:target,observed_at:started,is_enabled:true,
  schedule:config.schedule,last_run:{id,recorded_status:'in_progress',started_at:started,scheduled_for:started}};
 const checkpoint={lease:{owner:'worker',run_id:id,acquired_at:started,expires_at:'2026-11-07T00:30:00Z'},
  current_run:{run_id:id,application_status:'running',started_at:started,observed_at:started,scheduler}};
 const record={schema_version:1,review_head:head,owner:'worker',run_id:id,scheduler_id:target,started_at:started,
  lease_acquired_at:started,lease_expires_at:checkpoint.lease.expires_at,observed_at:'2026-11-07T00:00:20Z'};
 const seen=[];let corrupt=false,moving=false,hbReads=0;
 const fetcher=async url=>{
  seen.push(url);if(url.includes('/commits/')){
   if(moving&&url.includes('content-review-heartbeat')&&++hbReads>1)return Response.json({sha:'b'.repeat(40)});
   return Response.json({sha:head});
  }
  let value;if(url.includes('content_review_monitor_config.json'))value=config;
  else if(url.includes('content_review_worker_status.json'))value=checkpoint;
  else if(url.includes('content_review_operations.json'))value={scheduler};
  else if(url.includes('content_review_independent_monitor.json'))value={};
  else if(url.includes('content_review_detached_heartbeat.json'))value=record;
  else if(url.includes('openalex_request_policy.json'))value={requests_enabled:false};
  else return Response.json({workflows:[]});
  const raw=JSON.stringify(value),sha=crypto.createHash('sha1').update(`blob ${Buffer.byteLength(raw)}\0`).update(raw).digest('hex');
  return Response.json({encoding:'base64',content:Buffer.from(raw).toString('base64'),sha:corrupt&&url.includes('content_review_detached_heartbeat.json')?'f'.repeat(40):sha});
 };
 const result=await readOperations({fetcher,now});
 assert.equal(result.heartbeat.verified,true);assert.equal(result.workers[0].status,'Running');
 assert.equal(result.workers[0].native_evidence_verified,false);
 assert.match(result.workers[0].issue,/not been independently verified/);
 assert.ok(seen.some(url=>url.includes('content_review_worker_status.json?ref='+head)));
 record.observed_at='2026-11-06T23:59:00Z';
 const stale=await readOperations({fetcher,now});
 assert.equal(stale.heartbeat.verified,false);assert.equal(stale.workers[0].status,'Degraded');
 record.observed_at='2026-11-07T00:00:20Z';corrupt=true;
 const altered=await readOperations({fetcher,now});
 assert.equal(altered.heartbeat.verified,false);assert.notEqual(altered.workers[0].status,'Operating normally');
 corrupt=false;moving=true;
 const changed=await readOperations({fetcher,now});
 assert.equal(changed.heartbeat.verified,false);
 assert.ok(changed.refresh_errors.some(error=>error.includes('head changed')));
});
