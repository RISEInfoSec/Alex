'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {commitMonitor}=require('../tools/content_review/github_atomic_monitor.cjs');
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});
const review='a'.repeat(40),monitor='b'.repeat(40),tree='c'.repeat(40),newTree='d'.repeat(40),commit='e'.repeat(40);
const path='config/content_review_independent_monitor.json',configPath='config/content_review_monitor_config.json',workerPath='config/content_review_worker_status.json';
function fixture(){
 const at=Date.parse('2026-11-06T23:35:00Z'),schedule='BEGIN:VEVENT\nDTSTART:20261106T233200Z\nRRULE:FREQ=HOURLY\nEND:VEVENT';
 const self={automation_id:'Automation_monitor1',run_id:'monitor-run',scheduled_for:'2026-11-06T23:32:00Z',started_at:'2026-11-06T23:32:01Z',trigger:'schedule',is_enabled:true,schedule,native_status:'in_progress'};
 const workerRun={id:'worker-run',recorded_status:'failed',scheduled_for:'2026-11-06T22:45:00Z',started_at:'2026-11-06T22:45:01Z',completed_at:'2026-11-06T22:46:00Z'};
 const workerSchedule='BEGIN:VEVENT\nDTSTART:20261106T224500Z\nRRULE:FREQ=HOURLY\nEND:VEVENT';
 const config=JSON.stringify({automation_id:self.automation_id,target_automation_id:'Automation_worker1'}),worker='{}';
 const record={schema_version:1,observed_at:'2026-11-06T23:35:00Z',observer:self,source_review_commit:review,
  source_config_blob_sha:hash(config),source_worker_blob_sha:hash(worker),source_receipt_blob_sha:null,previous_monitor_blob_sha:null,
  scheduler:{id:'Automation_worker1',is_enabled:true,schedule:workerSchedule,last_run:workerRun,requires_user_action:true,result_is_failure_message:false},access_error:null};
 const content=JSON.stringify(record)+'\n';let mon=monitor,writes=0,treeEntries;
 const nativeObserver={id:self.automation_id,is_enabled:true,schedule,run_details:{last_run:{id:self.run_id,recorded_status:'in_progress',scheduled_for:self.scheduled_for,started_at:self.started_at}}};
 const nativeWorker={id:'Automation_worker1',is_enabled:true,schedule:workerSchedule,run_details:{last_run:workerRun,latest_result:{run_id:workerRun.id,requires_user_action:true,is_failure_message:false}}};
 const api={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='codex/soups-corpus-review'?review:mon}}),
  fetchFile:async({path:p,ref})=>p===configPath?ok({sha:hash(config),content:config}):p===workerPath?ok({sha:hash(worker),content:worker}):
    ref===commit&&p===path?ok({sha:hash(content),content}):({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
  createBlob:async({content:s})=>ok({sha:hash(s)}),createTree:async({base_tree_sha,tree_elements})=>{assert.equal(base_tree_sha,tree);treeEntries=tree_elements;return ok({sha:newTree});},
  createCommit:async({parent_sha,tree_sha})=>{assert.equal(parent_sha,monitor);assert.equal(tree_sha,newTree);assert.equal(treeEntries.length,1);return ok({sha:commit});},
  updateRef:async({branch_name,expected_sha,sha,force})=>{writes++;assert.equal(branch_name,'codex/content-review-monitor');assert.equal(expected_sha,monitor);assert.equal(force,false);mon=sha;return ok({success:true});}};
 return {api,linkId:'account',proposal:{path,review_head:review,monitor_head:monitor,base_tree_sha:tree,base_blob:null,content,blob_sha:hash(content),observer_id:self.automation_id,run_id:self.run_id,writes:0,requires_expected_head_and_readback:true},
  readNativeObserver:async()=>nativeObserver,readNativeWorker:async()=>nativeWorker,now:()=>at,writes:()=>writes,nativeObserver,nativeWorker,setMonitor:v=>{mon=v;}};
}
test('monitor commits only to its separate ref with native evidence and readback',async()=>{
 const f=fixture(),r=await commitMonitor(f);assert.equal(r.status,'committed_and_read_back');assert.equal(f.writes(),1);
});
test('changed native worker, finished observer or competing monitor stops the write',async()=>{
 for(const change of ['worker','observer','head']){const f=fixture();
  if(change==='worker')f.nativeWorker.run_details.latest_result.requires_user_action=false;
  if(change==='observer')f.nativeObserver.run_details.last_run.recorded_status='completed';
  if(change==='head')f.setMonitor('f'.repeat(40));
  await assert.rejects(commitMonitor(f));assert.equal(f.writes(),0);
 }
});
test('an ambiguous monitor ref update is not retried',async()=>{
 const f=fixture();let calls=0;f.api.updateRef=async()=>{calls++;throw Error('lost connection');};
 await assert.rejects(commitMonitor(f),/ambiguous; reconcile/);assert.equal(calls,1);
});
