'use strict';

// Verify the narrow no-work lease-release transition independently. This is
// never candidate processing, scheduled success or publication evidence.
const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):obj(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const time=x=>typeof x==='string'?Date.parse(x):NaN;
function validateNoWork({before,after,receipt,owner,runId,now=Date.now()}){
 if(!obj(before)||!obj(after)||!obj(receipt)||typeof owner!=='string'||!owner||typeof runId!=='string'||
  !/^[a-zA-Z0-9-]{1,100}$/.test(runId)||!Number.isFinite(now))throw Error('Invalid no-work completion inputs');
 const lease=before.lease,run=before.current_run,stamp=receipt.completed_at;
 const fields=['schema_version','run_id','trigger','scheduled_for','started_at','completed_at','status','completed_actions',
  'receipt_path','provider_requests','paid_requests','openalex_requests','publication_approved','native_completion_verified','scope_note','pilot'].sort();
 const pilot={attempted_candidate_ids:[],newly_passed_checks:{duplicates:[]},requests:{source:0,paid:0,openalex:0},
  manual_admitted:[],all_six_completed:[],actual_publications:[],integrity_passed:null,checkpoint_failures:null,
  resolvable_gate_count:null,all_candidates_legitimately_held:null,
  remaining_blockers:['Subsequent gates and source work were not executed in this mechanical pass.']};
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.run_id!==runId||receipt.trigger!=='schedule'||
  receipt.status!=='no_work'||!equal(receipt.completed_actions,[])||receipt.receipt_path!=='config/content_review_run_receipts/'+runId+'.json'||
  receipt.provider_requests!==0||receipt.paid_requests!==0||receipt.openalex_requests!==0||receipt.publication_approved!==false||
  receipt.native_completion_verified!==false||receipt.scope_note!=='Mechanical duplicate checks only; review readiness and publication are not established.'||
  !equal(receipt.pilot,pilot)||!obj(lease)||lease.owner!==owner||lease.run_id!==runId||!obj(run)||run.run_id!==runId||
  run.application_status!=='running'||!equal(run.request_counts,{source:0,paid:0,openalex:0})||run.pending_source_request!=null||
  !Number.isFinite(time(stamp))||time(stamp)>now||now-time(stamp)>40000||
  !Number.isFinite(time(run.started_at))||time(run.started_at)>time(stamp)||time(receipt.started_at)!==time(run.started_at)||
  !Number.isFinite(time(run.scheduled_for))||time(receipt.scheduled_for)!==time(run.scheduled_for)||
  !Number.isFinite(time(lease.acquired_at))||time(lease.acquired_at)>time(stamp)||
  !Number.isFinite(time(lease.expires_at))||time(lease.expires_at)<=now||
  (lease.renewed_at!=null&&(!Number.isFinite(time(lease.renewed_at))||time(lease.renewed_at)>time(stamp))))
  throw Error('No-work completion evidence invalid');
 const expected=structuredClone(before);
 if(expected.lease_history===undefined)expected.lease_history=[];
 if(!Array.isArray(expected.lease_history))throw Error('Lease history invalid');
 expected.lease_history.push({...lease,status:'released',released_at:stamp});expected.lease=null;
 expected.current_run.application_status='deferred';expected.current_run.application_completed_at=stamp;
 expected.current_run.receipt=receipt.receipt_path;
 if(!equal(expected,after))throw Error('No-work completion changes unrelated state');
 return {status:'valid',candidate_processing:false,native_completion_verified:false};
}
module.exports={validateNoWork};
