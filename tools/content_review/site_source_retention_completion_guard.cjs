'use strict';

// Validate a run release only after an independently re-audited source retention.
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const time=x=>typeof x==='string'?Date.parse(x):NaN;
const HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
function validateSourceRetentionCompletion({before,after,receipt,owner,runId,verifiedAction,now=Date.now()}){
 if(!object(before)||!object(after)||!object(receipt)||!object(verifiedAction)||!ID.test(owner||'')||!ID.test(runId||'')||!Number.isFinite(now))
  throw Error('Invalid source retention completion inputs');
 const lease=before.lease,run=before.current_run,stamp=receipt.completed_at,held=verifiedAction.action==='source_hold_retained';
 const status=held?'deferred':'complete',manual=run?.scheduler?.kind==='manual';
 const fields=['schema_version','kind','run_id','trigger','scheduled_for','started_at','completed_at','status','receipt_path','completed_actions',
  'provider_requests','paid_requests','openalex_requests','candidate_processing','native_completion_verified','publication_approved','scope_note'].sort();
 const actionFields=['path','collection','candidate_id','content_sha256','action'].sort();
 if(!equal(Object.keys(verifiedAction).sort(),actionFields)||!ID.test(verifiedAction.collection||'')||!ID.test(verifiedAction.candidate_id||'')||
  !HASH.test(verifiedAction.content_sha256||'')||!['source_evidence_retained','source_hold_retained'].includes(verifiedAction.action)||
  !/^config\/content_review_source_checkpoints\/[0-9a-f]{64}\.json$/.test(verifiedAction.path||''))
  throw Error('Invalid verified source retention action');
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.kind!=='source_retention_completion'||receipt.run_id!==runId||
  receipt.trigger!==(manual?'manual':'schedule')||receipt.status!==status||!equal(receipt.completed_actions,[verifiedAction])||
  receipt.receipt_path!=='config/content_review_run_receipts/'+runId+'.json'||receipt.provider_requests!==0||receipt.paid_requests!==0||
  receipt.openalex_requests!==0||receipt.candidate_processing!==!held||receipt.native_completion_verified!==false||receipt.publication_approved!==false||
  receipt.scope_note!==(held?'One source hold retained; no gate pass, review readiness or publication is established.':
   'One source evidence result retained; no gate pass, review readiness or publication is established.')||
  !object(lease)||lease.owner!==owner||lease.run_id!==runId||!object(run)||run.run_id!==runId||run.application_status!=='running'||
  !equal(run.request_counts,{source:0,paid:0,openalex:0})||
  !Number.isFinite(time(stamp))||time(stamp)>now||now-time(stamp)>300000||
  !Number.isFinite(time(run.started_at))||time(run.started_at)>time(stamp)||time(receipt.started_at)!==time(run.started_at)||
  (manual?(run.scheduled_for!==null||receipt.scheduled_for!==null):(!Number.isFinite(time(run.scheduled_for))||time(receipt.scheduled_for)!==time(run.scheduled_for)))||
  !Number.isFinite(time(lease.acquired_at))||time(lease.acquired_at)>time(stamp)||
  !Number.isFinite(time(lease.expires_at))||time(lease.expires_at)<=now||
  (lease.renewed_at!=null&&(!Number.isFinite(time(lease.renewed_at))||time(lease.renewed_at)>time(stamp))))
  throw Error('Source retention completion evidence invalid');
 const pending=run.pending_source_request;
 if(pending!=null){
  const history=Array.isArray(before.run_history)?before.run_history.filter(x=>x?.run_id===pending?.origin_run_id):[];
  if(!object(pending)||!HASH.test(pending.request_id||'')||!ID.test(pending.origin_run_id||'')||
   !Number.isSafeInteger(pending.reserved_limit)||pending.reserved_limit<1||pending.reserved_limit>30||
   !Number.isFinite(time(pending.prepared_at))||history.length!==1||!equal(history[0].pending_source_request,pending))
   throw Error('Pending source reservation cannot be preserved');
 }
 const expected=structuredClone(before);expected.lease_history??=[];
 if(!Array.isArray(expected.lease_history))throw Error('Lease history invalid');
 expected.lease_history.push({...lease,status:'released',released_at:stamp});expected.lease=null;
 expected.current_run.application_status=status;expected.current_run.application_completed_at=stamp;expected.current_run.receipt=receipt.receipt_path;
 if(!equal(expected,after))throw Error('Source retention completion changes unrelated state');
 return {status:'valid',candidate_processing:!held,native_completion_verified:false,publication_verified:false};
}
module.exports={validateSourceRetentionCompletion};
