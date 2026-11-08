// Convert a pinned replacement receipt into reported counts. The console does
// not independently verify the checkpoint or the native scheduler completion.
const SHA=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const PATH=/^config\/content_review_mechanical_checkpoints\/[0-9a-f]{64}\.json$/;
const SOURCE_PATH=/^config\/content_review_source_gate_checkpoints\/[0-9a-f]{64}\.json$/;
const RETENTION_PATH=/^config\/content_review_source_checkpoints\/[0-9a-f]{64}\.json$/;
const time=x=>typeof x==='string'?Date.parse(x):NaN;
export function mechanicalReceipt(checkpoint,receipt,target){
 const run=checkpoint?.current_run,id=run?.run_id,actions=receipt?.completed_actions;
 if(!ID.test(id||'')||run?.scheduler?.id!==target||!['complete','deferred'].includes(run?.application_status)||
  run.receipt!=='config/content_review_run_receipts/'+id+'.json'||receipt?.receipt_path!==run.receipt||
  receipt?.schema_version!==1||receipt?.run_id!==id||receipt?.trigger!=='schedule'||receipt?.status!==run.application_status||
  receipt?.native_completion_verified!==false||receipt?.publication_approved!==false||
  receipt?.provider_requests!==0||receipt?.paid_requests!==0||receipt?.openalex_requests!==0||
  !Array.isArray(actions)||actions.length!==1||!Number.isFinite(time(receipt.started_at))||!Number.isFinite(time(receipt.completed_at))||
  time(receipt.started_at)!==time(run.started_at)||time(receipt.scheduled_for)!==time(run.scheduled_for)||
  time(receipt.completed_at)!==time(run.application_completed_at)||time(receipt.completed_at)<time(receipt.started_at))return null;
 const action=actions[0];
 if(!action||!ID.test(action.collection||'')||!ID.test(action.candidate_id||'')||
  !SHA.test(action.content_sha256||''))return null;
 const duplicate=receipt.status==='complete'&&action.gate==='duplicates'&&PATH.test(action.path||'');
 const source=receipt.status==='complete'&&receipt.kind==='source_gate_completion'&&receipt.candidate_processing===true&&['format','access','metadata'].includes(action.gate)&&SOURCE_PATH.test(action.path||'');
 const retained=receipt.status==='complete'&&receipt.kind==='source_retention_completion'&&receipt.candidate_processing===true&&action.action==='source_evidence_retained'&&RETENTION_PATH.test(action.path||'');
 const held=receipt.status==='deferred'&&receipt.kind==='source_retention_completion'&&receipt.candidate_processing===false&&action.action==='source_hold_retained'&&RETENTION_PATH.test(action.path||'');
 if(!duplicate&&!source&&!retained&&!held)return null;
 return {native_run_id:id,trigger:'schedule',observed_at:receipt.completed_at,local_candidates:1,duplicate_gate_passes:duplicate?1:0,
  source_requests:0,source_evidence_retained:retained?1:0,source_holds_retained:held?1:0,source_gate_passes:source?1:0,downstream_gate_passes:0,six_gate_completions:0,newly_review_ready:0,publications:0,
  scope_note:held?'A source hold was recorded. No gate pass or native scheduler completion is established.':
   retained?'A source evidence retention checkpoint was reported. No gate pass or native scheduler completion is established.':
   source?'A retained-source gate checkpoint was reported in the run receipt. Other gates and native scheduler completion remain unverified.':
   'A duplicate checkpoint was reported in the run receipt. Other gates and native scheduler completion remain unverified.',
  corrective_action:'Continue remaining checks; verify native completion separately.',receipt_source:'pinned_repository_receipt',
  candidate_counts_verified:false,native_completion_verified:false};
}
