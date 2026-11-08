'use strict';

// Narrow run completion: one independently verified duplicate checkpoint.
// The caller must derive the action from Git history and current D1, not from
// the proposed receipt. Native terminal success and publication remain false.
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const time=x=>typeof x==='string'?Date.parse(x):NaN;
const HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
function validateComplete({before,after,receipt,owner,runId,verifiedAction,now=Date.now()}){
 if(!object(before)||!object(after)||!object(receipt)||!object(verifiedAction)||!ID.test(owner||'')||!ID.test(runId||'')||!Number.isFinite(now))
  throw Error('Invalid run completion inputs');
 const lease=before.lease,run=before.current_run,stamp=receipt.completed_at;
 const fields=['schema_version','run_id','trigger','scheduled_for','started_at','completed_at','status','completed_actions',
  'receipt_path','provider_requests','paid_requests','openalex_requests','publication_approved','native_completion_verified','scope_note','pilot'].sort();
 const actionFields=['path','collection','candidate_id','content_sha256','gate'].sort();
 if(!equal(Object.keys(verifiedAction).sort(),actionFields)||!ID.test(verifiedAction.collection||'')||!ID.test(verifiedAction.candidate_id||'')||
  !HASH.test(verifiedAction.content_sha256||'')||verifiedAction.gate!=='duplicates'||
  !/^config\/content_review_mechanical_checkpoints\/[0-9a-f]{64}\.json$/.test(verifiedAction.path||''))
  throw Error('Invalid verified checkpoint action');
 const pilot={attempted_candidate_ids:[verifiedAction.candidate_id],newly_passed_checks:{duplicates:[verifiedAction.candidate_id]},
  requests:{source:0,paid:0,openalex:0},manual_admitted:[],all_six_completed:[],actual_publications:[],integrity_passed:null,
  checkpoint_failures:null,resolvable_gate_count:null,all_candidates_legitimately_held:null,
  remaining_blockers:['Subsequent gates and source work were not executed in this mechanical pass.']};
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.run_id!==runId||receipt.trigger!=='schedule'||
  receipt.status!=='complete'||!equal(receipt.completed_actions,[verifiedAction])||receipt.receipt_path!=='config/content_review_run_receipts/'+runId+'.json'||
  receipt.provider_requests!==0||receipt.paid_requests!==0||receipt.openalex_requests!==0||receipt.publication_approved!==false||
  receipt.native_completion_verified!==false||receipt.scope_note!=='Mechanical duplicate checks only; review readiness and publication are not established.'||
  !equal(receipt.pilot,pilot)||!object(lease)||lease.owner!==owner||lease.run_id!==runId||!object(run)||run.run_id!==runId||
  run.application_status!=='running'||!equal(run.request_counts,{source:0,paid:0,openalex:0})||
  !Number.isFinite(time(stamp))||time(stamp)>now||now-time(stamp)>300000||
  !Number.isFinite(time(run.started_at))||time(run.started_at)>time(stamp)||time(receipt.started_at)!==time(run.started_at)||
  !Number.isFinite(time(run.scheduled_for))||time(receipt.scheduled_for)!==time(run.scheduled_for)||
  !Number.isFinite(time(lease.acquired_at))||time(lease.acquired_at)>time(stamp)||
  !Number.isFinite(time(lease.expires_at))||time(lease.expires_at)<=now||
  (lease.renewed_at!=null&&(!Number.isFinite(time(lease.renewed_at))||time(lease.renewed_at)>time(stamp))))
  throw Error('Run completion evidence invalid');
 const pending=run.pending_source_request;
 if(pending!=null){
  const history=Array.isArray(before.run_history)?before.run_history.filter(x=>x?.run_id===pending?.origin_run_id):[];
  if(!object(pending)||!HASH.test(pending.request_id||'')||!ID.test(pending.origin_run_id||'')||
   !Number.isSafeInteger(pending.reserved_limit)||pending.reserved_limit<1||pending.reserved_limit>30||
   !Number.isFinite(time(pending.prepared_at))||history.length!==1||!equal(history[0].pending_source_request,pending))
   throw Error('Pending source reservation cannot be preserved');
 }
 const expected=structuredClone(before);
 if(expected.lease_history===undefined)expected.lease_history=[];
 if(!Array.isArray(expected.lease_history))throw Error('Lease history invalid');
 expected.lease_history.push({...lease,status:'released',released_at:stamp});expected.lease=null;
 expected.current_run.application_status='complete';expected.current_run.application_completed_at=stamp;expected.current_run.receipt=receipt.receipt_path;
 if(!equal(expected,after))throw Error('Run completion changes unrelated state');
 return {status:'valid',candidate_processing:true,native_completion_verified:false,publication_verified:false};
}
module.exports={validateComplete};
