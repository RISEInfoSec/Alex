import test from 'node:test';
import assert from 'node:assert/strict';
import {mechanicalReceipt} from '../lib/mechanical-receipt.mjs';
import {processingHealth} from '../lib/processing-health.mjs';
const start='2026-11-07T22:00:00Z',end='2026-11-07T22:01:00Z',id='run',target='Automation_new';
const action=()=>({path:'config/content_review_mechanical_checkpoints/'+'a'.repeat(64)+'.json',collection:'virusbulletin',candidate_id:'candidate',content_sha256:'b'.repeat(64),gate:'duplicates'});
const state=()=>({current_run:{run_id:id,scheduler:{id:target},application_status:'complete',receipt:'config/content_review_run_receipts/run.json',started_at:start,scheduled_for:start,application_completed_at:end}});
const receipt=()=>({schema_version:1,run_id:id,trigger:'schedule',status:'complete',receipt_path:'config/content_review_run_receipts/run.json',started_at:start,scheduled_for:start,completed_at:end,provider_requests:0,paid_requests:0,openalex_requests:0,publication_approved:false,native_completion_verified:false,completed_actions:[action()]});
test('a matching mechanical receipt reports the duplicate only and never native success',()=>{
 const value=mechanicalReceipt(state(),receipt(),target);
 assert.equal(value.duplicate_gate_passes,1);assert.equal(value.native_completion_verified,false);
 assert.equal(value.newly_review_ready,0);assert.equal(value.candidate_counts_verified,false);
 assert.match(processingHealth(value,Date.parse(end)).status,/Duplicate check reported/);
});
test('stale identity, no-work, forged native claims or unrelated activity cannot appear as processing',()=>{
 for(const change of ['identity','target','status','empty','native','cost','changed','badtime']){
  const s=state(),r=receipt();
  if(change==='identity')r.run_id='other';if(change==='target')s.current_run.scheduler.id='Automation_old';
  if(change==='status')r.status='no_work';if(change==='empty')r.completed_actions=[];
  if(change==='native')r.native_completion_verified=true;if(change==='cost')r.provider_requests=1;
  if(change==='changed')r.completed_actions[0].gate='schema';if(change==='badtime')r.completed_at='bad';
  assert.equal(mechanicalReceipt(s,r,target),null,change);
 }
});
test('a retained-source receipt reports its gate without claiming native success or readiness',()=>{
 const r=receipt();r.kind='source_gate_completion';r.candidate_processing=true;
 r.completed_actions[0].path='config/content_review_source_gate_checkpoints/'+'a'.repeat(64)+'.json';r.completed_actions[0].gate='access';
 const value=mechanicalReceipt(state(),r,target);
 assert.equal(value.source_gate_passes,1);assert.equal(value.duplicate_gate_passes,0);
 assert.equal(value.native_completion_verified,false);assert.equal(value.candidate_counts_verified,false);assert.equal(value.newly_review_ready,0);
 r.candidate_processing=false;assert.equal(mechanicalReceipt(state(),r,target),null);
});

import {createHash} from 'node:crypto';
import {readOperations} from '../lib/operations-source.mjs';
function encoded(value){const body=Buffer.from(JSON.stringify(value)),sha=createHash('sha1').update(`blob ${body.length}\0`).update(body).digest('hex');return Response.json({encoding:'base64',content:body.toString('base64'),sha});}
test('console reads the replacement receipt at an immutable head and labels it reported',async()=>{
 const now=Date.parse(end),head='c'.repeat(40);let headReads=0;
 const fetcher=async url=>{
  if(url.includes('/commits/codex%2Fsoups-corpus-review')){headReads++;return Response.json({sha:head})}
  if(url.includes('content_review_monitor_config.json'))return encoded({target_automation_id:target});
  if(url.includes('content_review_worker_status.json'))return encoded(state());
  if(url.includes('content_review_run_receipts/'))return encoded(receipt());
  if(url.includes('content_review_operations.json'))return encoded({scheduler:{id:target}});
  if(url.includes('content_review_processing_health.json'))return encoded({});
  if(url.includes('openalex_request_policy.json'))return encoded({requests_enabled:true});
  return Response.json({workflows:[]});
 };
 const result=await readOperations({fetcher,now});
 assert.ok(headReads>=2);assert.equal(result.processing.duplicate_gate_passes,1);
 assert.equal(result.processing.counts_independently_verified,false);assert.equal(result.processing.native_completion_verified,false);
 assert.notEqual(result.workers[0].status,'Operating normally');
});
test('a moving review head cannot promote a receipt into processing evidence',async()=>{
 const now=Date.parse(end);let reads=0;
 const fetcher=async url=>{
  if(url.includes('/commits/codex%2Fsoups-corpus-review'))return Response.json({sha:(++reads===1?'c':'d').repeat(40)});
  if(url.includes('content_review_monitor_config.json'))return encoded({target_automation_id:target});
  if(url.includes('content_review_worker_status.json'))return encoded(state());
  if(url.includes('content_review_run_receipts/'))return encoded(receipt());
  if(url.includes('content_review_operations.json'))return encoded({scheduler:{id:target}});
  if(url.includes('content_review_processing_health.json'))return encoded({});
  if(url.includes('openalex_request_policy.json'))return encoded({requests_enabled:true});
  return Response.json({workflows:[]});
 };
 const result=await readOperations({fetcher,now});
 assert.equal(result.processing.duplicate_gate_passes,undefined);
 assert.ok(result.refresh_errors.some(x=>x.includes('head or worker identity changed')));
});
