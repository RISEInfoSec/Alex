'use strict';

// A pending/failed source run is not work completion. This validates only an
// exact, history-preserving lease release; the caller independently checks the
// GitHub run and fences the current private review snapshot.
const {fingerprint,sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const {complete,validateSnapshot}=require('./site_duplicate_semantics.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const HASH=/^[0-9a-f]{64}$/,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const time=x=>typeof x==='string'?Date.parse(x):NaN;
function validateSourcePending({before,after,receipt,request,discovery,snapshot,confirmed,owner,runId,now=Date.now()}){
 if(![before,after,receipt,request,discovery].every(object)||!ID.test(owner||'')||!ID.test(runId||'')||!Number.isFinite(now)||
  !complete(snapshot)||!complete(confirmed)||fingerprint(snapshot)!==fingerprint(confirmed))throw Error('Source pending inputs incomplete');
 validateSnapshot(snapshot);validateSnapshot(confirmed);
 const lease=before.lease||{},run=before.current_run||{},pending=run.pending_source_request||{},counts=run.request_counts||{};
 const stamp=time(receipt.completed_at),start=time(run.started_at),due=time(run.scheduled_for),expires=time(lease.expires_at),acquired=time(lease.acquired_at);
 if(lease.owner!==owner||lease.run_id!==runId||run.run_id!==runId||run.application_status!=='running'||
  !HASH.test(pending.request_id||'')||!ID.test(pending.origin_run_id||'')||!Number.isSafeInteger(pending.reserved_limit)||pending.reserved_limit<1||pending.reserved_limit>30||
  request.request_id!==pending.request_id||request.coordinator_run_id!==pending.origin_run_id||request.source_request_limit!==pending.reserved_limit||
  sha256(pyJson(Object.fromEntries(Object.entries(request).filter(([k])=>k!=='request_id'))))!==pending.request_id||
  !Number.isFinite(start)||!Number.isFinite(due)||!Number.isFinite(stamp)||!Number.isFinite(expires)||!Number.isFinite(acquired)||
  stamp<start||stamp<acquired||stamp>now||now-stamp>180000||expires<=now||now-start>720000||
  (lease.renewed_at!=null&&(!Number.isFinite(time(lease.renewed_at))||time(lease.renewed_at)>stamp))||
  counts.source!==0||counts.paid!==0||counts.openalex!==0||!Array.isArray(run.accounted_source_requests??[])||(run.accounted_source_requests??[]).length!==0)
  throw Error('Source pending lease or accounting invalid');
 if(pending.origin_run_id===runId){
  if(request.lease_owner!==owner||time(request.started_at)!==start)throw Error('Source pending original run unavailable');
 }else{
  const history=Array.isArray(before.run_history)?before.run_history.filter(r=>r?.run_id===pending.origin_run_id):[];
  if(history.length!==1||!equal(history[0].pending_source_request,pending)||!Array.isArray(before.lease_history)||
   !before.lease_history.some(l=>l?.run_id===pending.origin_run_id&&l.owner===request.lease_owner&&['released','expired'].includes(l.status))||
   time(history[0].started_at)!==time(request.started_at))
   throw Error('Source pending original run unavailable');
 }
 if(!['source_run_pending','source_artifact_pending','source_run_failed'].includes(discovery.status)||
  !SHA.test(discovery.reservation_head||'')||discovery.candidate_processing!==false||discovery.source_workflow_verified!==false||discovery.publication_verified!==false)
  throw Error('Source pending discovery invalid');
 const sourceRunId=discovery.source_run_id??null,conclusion=discovery.conclusion??null;
 if(sourceRunId!==null&&(!Number.isSafeInteger(sourceRunId)||sourceRunId<1)||
  discovery.status!=='source_run_pending'&&sourceRunId===null||
  discovery.status==='source_run_failed'&&(typeof conclusion!=='string'||!/^[a-z_]{1,40}$/.test(conclusion))||
  discovery.status!=='source_run_failed'&&conclusion!==null)throw Error('Source pending run status invalid');
 const fields=['schema_version','kind','run_id','trigger','scheduled_for','started_at','completed_at','status','receipt_path','source_request_id',
  'origin_run_id','reservation_head','source_status','source_run_id','source_conclusion','source_requests','candidate_processing','gate_passed',
  'native_completion_verified','publication_approved','scope_note'].sort(),path='config/content_review_run_receipts/'+runId+'.json';
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.kind!=='source_pending_deferral'||receipt.run_id!==runId||
  receipt.trigger!=='schedule'||receipt.status!=='deferred'||receipt.receipt_path!==path||receipt.source_request_id!==pending.request_id||
  receipt.origin_run_id!==pending.origin_run_id||receipt.reservation_head!==discovery.reservation_head||receipt.source_status!==discovery.status||
  receipt.source_run_id!==sourceRunId||receipt.source_conclusion!==conclusion||receipt.source_requests!==0||receipt.candidate_processing!==false||
  receipt.gate_passed!==false||receipt.native_completion_verified!==false||receipt.publication_approved!==false||
  time(receipt.started_at)!==start||time(receipt.scheduled_for)!==due||
  receipt.scope_note!=='The source request remains pending; no candidate gate or publication is established.')throw Error('Source pending receipt invalid');
 const expected=structuredClone(before);expected.lease_history??=[];if(!Array.isArray(expected.lease_history))throw Error('Source pending lease history invalid');
 expected.lease_history.push({...lease,status:'released',released_at:receipt.completed_at});expected.lease=null;
 expected.current_run.application_status='deferred';expected.current_run.application_completed_at=receipt.completed_at;expected.current_run.receipt=path;
 if(!equal(expected,after))throw Error('Source pending changes unrelated state');
 return {status:'valid',receipt_path:path,candidate_processing:false,native_completion_verified:false,publication_verified:false};
}
module.exports={validateSourcePending};
