import test from 'node:test';
import assert from 'node:assert/strict';
import {readOperations} from '../lib/operations-source.mjs';

test('retired monitor cannot claim worker completion or affect status refresh',async()=>{
 const now=Date.parse('2026-11-07T18:00:00Z'),seen=[];
 const scheduler={id:'Automation_worker',observed_at:new Date(now).toISOString(),is_enabled:true,
  last_run:{id:'run',recorded_status:'completed',started_at:new Date(now-1000).toISOString()},
  last_verified_scheduled_success:{run_id:'run',evidence_verified:true,trigger:'schedule',receipt:'old'}};
 const fetcher=async url=>{
  seen.push(url);let value;
  if(url.includes('content_review_operations.json'))value={scheduler};
  else if(url.includes('content_review_worker_status.json'))value={};
  else if(url.includes('content_review_monitor_config.json'))value={target_automation_id:'Automation_worker',monitor_ref:'codex/content-review-monitor'};
  else if(url.includes('openalex_request_policy.json'))value={requests_enabled:false};
  else return Response.json({workflows:[]});
  return Response.json({encoding:'base64',content:Buffer.from(JSON.stringify(value)).toString('base64')});
 };
 const result=await readOperations({fetcher,now});
 assert.notEqual(result.workers[0].status,'Operating normally');
 assert.equal(result.workers.some(w=>w.id==='independent-monitor'),false);
 assert.equal(result.monitor,undefined);
 assert.equal(seen.some(url=>url.includes('content_review_independent_monitor.json')||url.includes('content-review-monitor')),false);
});

test('retired worker history is not presented as replacement activity',async()=>{
 const now=Date.parse('2026-11-07T18:00:00Z'),legacy='Automation_4eb2dd829aa88191b542d57f7008ebe3';
 const fetcher=async url=>{
  let value;
  if(url.includes('content_review_operations.json'))value={scheduler:{id:legacy,is_enabled:false,last_run:{id:'old-run',started_at:'2026-11-06T00:00:00Z'}},source_discovery:{last_success_at:'2026-11-06T00:00:00Z'}};
  else if(url.includes('content_review_worker_status.json'))value={current_run:{run_id:'old-run',scheduler:{id:legacy}},lease:{run_id:'old-run'}};
  else if(url.includes('content_review_monitor_config.json'))value={target_automation_id:legacy};
  else if(url.includes('content_review_processing_health.json'))value={native_run_id:'old-run',local_candidates:99,scope_note:'old context'};
  else if(url.includes('openalex_request_policy.json'))value={requests_enabled:true};
  else return Response.json({workflows:[]});
  return Response.json({encoding:'base64',content:Buffer.from(JSON.stringify(value)).toString('base64')});
 };
 const result=await readOperations({fetcher,now});
 assert.equal(result.replacement_configured,false);
 assert.equal(result.workers[0].name,'Content Review replacement');
 assert.equal(result.workers[0].status,'Not configured');
 assert.equal(result.workers[0].last_attempt_at,null);
 assert.equal(result.workers.some(w=>w.id==='source-discovery'),false);
 assert.equal(result.processing.local_candidates,undefined);
 assert.equal(result.processing.scope_note,undefined);
 assert.ok(result.summary.problems>0);
});

test('new target cannot inherit an old worker snapshot or processing report',async()=>{
 const now=Date.parse('2026-11-07T18:00:00Z'),old='Automation_4eb2dd829aa88191b542d57f7008ebe3';
 const encode=value=>Response.json({encoding:'base64',content:Buffer.from(JSON.stringify(value)).toString('base64')});
 const fetcher=async url=>{
  if(url.includes('content_review_monitor_config.json'))return encode({target_automation_id:'Automation_new'});
  if(url.includes('content_review_operations.json'))return encode({scheduler:{id:old,is_enabled:true,observed_at:new Date(now).toISOString(),last_run:{id:'old-run',recorded_status:'in_progress',started_at:new Date(now).toISOString()}}});
  if(url.includes('content_review_worker_status.json'))return encode({current_run:{run_id:'old-run',scheduler:{id:old}},lease:{run_id:'old-run'}});
  if(url.includes('content_review_processing_health.json'))return encode({native_run_id:'old-run',local_candidates:99});
  if(url.includes('openalex_request_policy.json'))return encode({requests_enabled:true});
  return Response.json({workflows:[]});
 };
 const result=await readOperations({fetcher,now});
 assert.equal(result.replacement_configured,true);
 assert.equal(result.workers[0].status,'Status unknown');
 assert.equal(result.workers[0].last_attempt_at,null);
 assert.equal(result.processing.local_candidates,undefined);
});

test('matching replacement activity is reported without claiming verification',async()=>{
 const now=Date.parse('2026-11-07T18:00:00Z'),at=new Date(now).toISOString(),target='Automation_new';
 const encode=value=>Response.json({encoding:'base64',content:Buffer.from(JSON.stringify(value)).toString('base64')});
 const fetcher=async url=>{
  if(url.includes('content_review_monitor_config.json'))return encode({target_automation_id:target,target_scope:'One controlled duplicate-only retry; full worker is not deployed.'});
  if(url.includes('content_review_operations.json'))return encode({scheduler:{id:target,is_enabled:true,observed_at:at,last_run:{id:'new-run',recorded_status:'completed',started_at:at}},source_discovery:{observed_at:at,last_success_at:at,note:'legacy source activity'}});
  if(url.includes('content_review_worker_status.json'))return encode({current_run:{run_id:'new-run',scheduler:{id:target}}});
  if(url.includes('content_review_processing_health.json'))return encode({native_run_id:'new-run',observed_at:at,local_candidates:2});
  if(url.includes('openalex_request_policy.json'))return encode({requests_enabled:true});
  return Response.json({workflows:[]});
 };
 const result=await readOperations({fetcher,now});
 assert.equal(result.replacement_configured,true);
 assert.equal(result.worker_scope,'One controlled duplicate-only retry; full worker is not deployed.');
 assert.equal(result.processing.local_candidates,2);
 assert.equal(result.processing.counts_independently_verified,false);
 assert.notEqual(result.workers[0].status,'Operating normally');
 assert.equal(result.workers.some(w=>w.id==='source-discovery'),false);
});
