import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {writeNoWork} from '../tools/content_review/site_no_work_writer.mjs';
import {verifyWorkerContext} from '../tools/content_review/d1_fence_service.mjs';

const start=Date.parse('2026-11-08T20:28:09.847Z');
const review='a'.repeat(40),main='b'.repeat(40),hb='c'.repeat(40),next='d'.repeat(40);
const worker='config/content_review_worker_status.json',receiptPath='config/content_review_run_receipts/run-1.json';
const ok=structuredContent=>({structuredContent});
const blob=content=>createHash('sha1').update(`blob ${Buffer.byteLength(content)}\0`).update(content).digest('hex');
function fixture(minutes=11){
 const at=start+minutes*60000,stamp=new Date(at).toISOString(),started=new Date(start).toISOString();
 const lease={owner:'worker',run_id:'run-1',acquired_at:started,expires_at:new Date(start+1800000).toISOString()};
 const run={run_id:'run-1',application_status:'running',started_at:started,scheduled_for:started,
  request_counts:{source:0,paid:0,openalex:0},scheduler:{id:'Automation_worker1',is_enabled:true,observed_at:started,
   last_run:{id:'run-1',recorded_status:'in_progress',started_at:started,scheduled_for:started}}};
 const before={lease,current_run:run,lease_history:[],preserved:{decision:'hold'}};
 const config={target_automation_id:'Automation_worker1',heartbeat_ref:'codex/content-review-heartbeat'};
 const heartbeat={schema_version:1,review_head:review,owner:'worker',run_id:'run-1',scheduler_id:'Automation_worker1',
  started_at:started,lease_acquired_at:started,lease_expires_at:lease.expires_at,observed_at:stamp};
 const receipt={schema_version:1,run_id:'run-1',trigger:'schedule',scheduled_for:started,started_at:started,completed_at:stamp,
  status:'no_work',completed_actions:[],receipt_path:receiptPath,provider_requests:0,paid_requests:0,openalex_requests:0,
  publication_approved:false,native_completion_verified:false,
  scope_note:'Mechanical duplicate checks only; review readiness and publication are not established.',
  pilot:{attempted_candidate_ids:[],newly_passed_checks:{duplicates:[]},requests:{source:0,paid:0,openalex:0},
   manual_admitted:[],all_six_completed:[],actual_publications:[],integrity_passed:null,checkpoint_failures:null,
   resolvable_gate_count:null,all_candidates_legitimately_held:null,
   remaining_blockers:['Subsequent gates and source work were not executed in this mechanical pass.']}};
 const after=structuredClone(before);after.lease=null;after.lease_history.push({...lease,status:'released',released_at:stamp});
 Object.assign(after.current_run,{application_status:'deferred',application_completed_at:stamp,receipt:receiptPath});
 const input={expectedHead:review,expectedMain:main,owner:'worker',runId:'run-1',
  files:{[worker]:JSON.stringify(after),[receiptPath]:JSON.stringify(receipt)}};
 let commits=0;const phases=[];
 const github={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?main:commit_sha==='codex/content-review-heartbeat'?hb:review}}),
  fetchCommitDetails:async()=>ok({sha:review,tree_sha:'e'.repeat(40)}),
  fetchFile:async({path})=>{if(path===receiptPath)return {isError:true,structuredContent:{error_code:'NOT_FOUND'}};
   const value=path===worker?before:path.endsWith('monitor_config.json')?config:heartbeat;
   const content=JSON.stringify(value);return ok({content,sha:blob(content)});},
  createBlob:async({content})=>ok({sha:blob(content)}),createTree:async()=>ok({sha:'f'.repeat(40)}),
  commitOnBranch:async()=>{commits++;return ok({success:true,sha:next});}};
 const snapshots={snapshot:{submissions:[],decisions:[],jobs:[],read_evidence:{}},transactional_snapshot:false};
 snapshots.confirmed_snapshot=structuredClone(snapshots.snapshot);
 return {input,github,heartbeat,before,after,receipt,commits:()=>commits,phases,options:{db:{},github,input,now:()=>at,
  heartbeatFactory:()=>async()=>{},read:async({heartbeat:pulse})=>{await pulse();return snapshots;},
  control:async args=>{assert.equal(args.completionOnly,true);phases.push(args.input.action);
   if(['acquire','begin'].includes(args.input.action))await verifyWorkerContext(args);
   return {status:{acquire:'acquired',begin:'committing',release:'confirmed_and_released',abort:'aborted'}[args.input.action],commit_sha:next};}}};
}
test('the observed eleven-minute no-work path completes and releases through the fence',async()=>{
 const f=fixture();const result=await writeNoWork(f.options);
 assert.equal(result.status,'committed_and_read_back');assert.equal(result.candidate_processing,false);
 assert.equal(result.native_completion_verified,false);assert.equal(result.publication_verified,false);
 assert.equal(f.commits(),1);assert.deepEqual(f.phases,['acquire','begin','release']);
});
test('no-work preparation still rejects runs beyond twelve minutes',async()=>{
 const f=fixture(12.01);await assert.rejects(writeNoWork(f.options),/No-work completion evidence invalid/);assert.equal(f.commits(),0);
});
test('completion grace retains heartbeat, owner and no-mutation checks',async()=>{
 for(const mode of ['stale','owner','mutation','processing','publication']){
  const f=fixture();
  if(mode==='stale')f.heartbeat.observed_at=new Date(start).toISOString();
  if(mode==='owner')f.input.owner='other';
  if(mode==='mutation'){f.after.preserved.decision='include';f.input.files[worker]=JSON.stringify(f.after);}
  if(mode==='processing'){f.receipt.completed_actions=['fabricated'];f.input.files[receiptPath]=JSON.stringify(f.receipt);}
  if(mode==='publication'){f.receipt.publication_approved=true;f.input.files[receiptPath]=JSON.stringify(f.receipt);}
  await assert.rejects(writeNoWork(f.options));assert.equal(f.commits(),0,mode);
 }
});
