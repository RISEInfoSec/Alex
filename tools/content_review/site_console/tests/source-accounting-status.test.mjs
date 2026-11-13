import test from 'node:test';
import assert from 'node:assert/strict';
import {sourceAccountingStatus} from '../lib/source-accounting-status.mjs';
import {createHash} from 'node:crypto';
import {readOperations} from '../lib/operations-source.mjs';

function fixture(){
 const id='a'.repeat(64),digest='b'.repeat(64),entry={request_id:id,artifact_id:17,native_run_id:23,artifact_sha256:digest,requests:2};
 const state={current_run:{run_id:'run',accounted_source_requests:[entry]},run_history:[]};
 const receipt={schema_version:1,independently_verified:true,artifact_id:17,artifact_sha256:digest,native_run:{id:23},
  request:{request_id:id},result:{request_id:id,status:'complete',read_only:true,requests:2,
   records:[{collection:'first',evidence:[{},{}]},{collection:'m3aawg',evidence:[{}]}]}};
 return {id,state,receipt};
}
test('accounted source evidence is reported without claiming processing or readiness',()=>{
 const {id,state,receipt}=fixture();const out=sourceAccountingStatus(state,receipt,id);
 assert.deepEqual(out,{status:'source_accounting_recorded',source_requests:2,records:2,collections:2,evidence_items:3,
  candidate_processing_verified:false,publication_authorized:false});
});
test('historical accounting survives when a later worker starts',()=>{
 const {id,state,receipt}=fixture();state.run_history.push(state.current_run);state.current_run={run_id:'later'};
 assert.equal(sourceAccountingStatus(state,receipt,id).records,2);
});
test('mismatched or ambiguous accounting never appears as verified evidence',()=>{
 for(const change of ['request','artifact','requests','status','duplicate','source','run']){
  const {id,state,receipt}=fixture();
  if(change==='request')receipt.result.request_id='c'.repeat(64);
  if(change==='artifact')receipt.artifact_sha256='c'.repeat(64);
  if(change==='requests')receipt.result.requests=3;
  if(change==='status')receipt.result.status='partial';
  if(change==='duplicate')state.run_history.push(structuredClone(state.current_run));
  if(change==='source')receipt.result.records[0].evidence=null;
  if(change==='run')receipt.native_run.id=24;
  assert.equal(sourceAccountingStatus(state,receipt,id),null,change);
 }
});

test('operations binds recorded source counts to an unchanged review head',async()=>{
 const {id,state,receipt}=fixture(),target='Automation_new',head='c'.repeat(40);
 state.current_run.scheduler={id:target};
 const encoded=value=>{const body=Buffer.from(JSON.stringify(value)),sha=createHash('sha1').update(`blob ${body.length}\0`).update(body).digest('hex');
  return Response.json({encoding:'base64',content:body.toString('base64'),sha});};
 for(const changed of [false,true]){
  let heads=0;
  const fetcher=async url=>{
   if(url.includes('/commits/codex%2Fsoups-corpus-review'))return Response.json({sha:changed&&++heads>1?'d'.repeat(40):head});
   if(url.includes('content_review_source_receipts/'+id+'.json'))return encoded(receipt);
   if(url.includes('content_review_monitor_config.json'))return encoded({target_automation_id:target});
   if(url.includes('content_review_worker_status.json'))return encoded(state);
   if(url.includes('content_review_operations.json'))return encoded({scheduler:{id:target}});
   if(url.includes('content_review_processing_health.json'))return encoded({});
   if(url.includes('openalex_request_policy.json'))return encoded({requests_enabled:true});
   if(url.includes('/actions/workflows?'))return Response.json({workflows:[]});
   return new Response('',{status:404});
  };
  const result=await readOperations({fetcher,now:Date.parse('2026-11-08T14:00:00Z'),cache:false});
  assert.equal(result.source_accounting?.records??null,changed?null:2);
  if(!changed)assert.equal(result.source_accounting.candidate_processing_verified,false);
 }
});
