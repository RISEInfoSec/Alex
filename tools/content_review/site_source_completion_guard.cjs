'use strict';

// Validate only an evidence-accounted source deferral and exact lease release.
// The caller independently fetches the GitHub run and archive and fences D1.
const {sha256,fingerprint}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const {complete,validateSnapshot}=require('./site_duplicate_semantics.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const HASH=/^[0-9a-f]{64}$/,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const time=x=>typeof x==='string'?Date.parse(x):NaN,positive=x=>Number.isSafeInteger(x)&&x>0;
function validateSourceCompletion({before,after,receipt,sourceReceipt,artifact,nativeRun,resultText,snapshot,confirmed,owner,runId,now=Date.now()}){
 if(![before,after,receipt,sourceReceipt,artifact,nativeRun].every(object)||typeof resultText!=='string'||!ID.test(owner||'')||!ID.test(runId||'')||
  !Number.isFinite(now)||!complete(snapshot)||!complete(confirmed)||fingerprint(snapshot)!==fingerprint(confirmed))throw Error('Source completion inputs incomplete');
 validateSnapshot(snapshot);validateSnapshot(confirmed);
 let result;try{result=JSON.parse(resultText)}catch{throw Error('Source completion artifact JSON invalid')}
 const lease=before.lease||{},run=before.current_run||{},accounts=run.accounted_source_requests,counts=run.request_counts||{};
 const stamp=time(receipt.completed_at),start=time(run.started_at),due=time(run.scheduled_for),expires=time(lease.expires_at),acquired=time(lease.acquired_at);
 if(lease.owner!==owner||lease.run_id!==runId||run.run_id!==runId||run.application_status!=='running'||run.pending_source_request!=null||
  !Number.isFinite(start)||!Number.isFinite(due)||!Number.isFinite(stamp)||!Number.isFinite(expires)||!Number.isFinite(acquired)||
  stamp<start||stamp<acquired||stamp>now||now-stamp>180000||expires<=now||now-start>720000||
  (lease.renewed_at!=null&&(!Number.isFinite(time(lease.renewed_at))||time(lease.renewed_at)>stamp))||
  !Array.isArray(accounts)||accounts.length!==1||!object(accounts[0])||
  !Number.isSafeInteger(counts.source)||counts.source<0||counts.source>30||counts.paid!==0||counts.openalex!==0)
  throw Error('Source completion lease or request accounting invalid');
 const entry=accounts[0],request=sourceReceipt.request,requestId=entry.request_id;
 if(!equal(Object.keys(entry).sort(),['request_id','artifact_id','artifact_sha256','native_run_id','requests','origin_run_id','charged_to_current_run'].sort())||
  !HASH.test(requestId||'')||!object(request)||request.request_id!==requestId||request.coordinator_run_id!==entry.origin_run_id||
  sha256(pyJson(Object.fromEntries(Object.entries(request).filter(([k])=>k!=='request_id'))))!==requestId||
  !positive(entry.artifact_id)||entry.artifact_id!==artifact.id||entry.native_run_id!==nativeRun.id||artifact.run_id!==nativeRun.id||
  !HASH.test(artifact.sha256||'')||!HASH.test(artifact.archive_sha256||'')||sha256(resultText)!==artifact.sha256||
  entry.artifact_sha256!==artifact.sha256||!Number.isSafeInteger(entry.requests)||entry.requests<0||entry.requests>30||
  (entry.charged_to_current_run===true?entry.origin_run_id!==runId||entry.requests!==counts.source:
   entry.charged_to_current_run!==false||entry.origin_run_id===runId||counts.source!==0))throw Error('Source completion artifact accounting differs');
 if(!positive(nativeRun.id)||!positive(nativeRun.run_attempt)||nativeRun.event!=='push'||nativeRun.head_branch!=='codex/soups-corpus-review'||
  nativeRun.path!=='.github/workflows/content_review_sources.yml'||nativeRun.status!=='completed'||nativeRun.conclusion!=='success'||!SHA.test(nativeRun.head_sha||''))
  throw Error('Source completion workflow unverified');
 const nativeFields=['id','event','head_branch','path','status','conclusion','head_sha','run_attempt'];
 const expectedSource={schema_version:1,independently_verified:true,request,native_run:Object.fromEntries(nativeFields.map(k=>[k,nativeRun[k]])),
  artifact_id:artifact.id,artifact_sha256:artifact.sha256,result};
 if(!equal(sourceReceipt,expectedSource)||!object(result)||result.schema_version!==1||result.status!=='complete'||result.read_only!==true||
  result.request_id!==requestId||!Array.isArray(result.request_log)||result.requests!==entry.requests||result.requests!==result.request_log.length||
  !Number.isSafeInteger(request.source_request_limit)||request.source_request_limit<1||request.source_request_limit>30||result.requests>request.source_request_limit||
  !Array.isArray(request.records)||request.records.length<1||request.records.length>5||!Array.isArray(result.records))throw Error('Source completion receipt differs');
 const proof=result.provenance||{},expectedProof={GITHUB_SHA:nativeRun.head_sha,GITHUB_RUN_ID:String(nativeRun.id),GITHUB_RUN_ATTEMPT:String(nativeRun.run_attempt),
  GITHUB_REF:'refs/heads/codex/soups-corpus-review',GITHUB_WORKFLOW_REF:'RISEInfoSec/Alex/.github/workflows/content_review_sources.yml@refs/heads/codex/soups-corpus-review'};
 if(Object.entries(expectedProof).some(([k,v])=>proof[k]!==v))throw Error('Source completion provenance differs');
 const key=x=>JSON.stringify([x?.collection,x?.candidate_id,x?.content_sha256]),requested=request.records.map(key),received=result.records.map(key);
 if(new Set(requested).size!==requested.length||new Set(received).size!==received.length||!equal([...requested].sort(),[...received].sort()))
  throw Error('Source completion candidate set differs');
 for(const row of result.records){if(!object(row)||!Array.isArray(row.evidence??[]))throw Error('Source completion evidence invalid');
  for(const e of row.evidence??[])if(!object(e)||typeof e.text!=='string'||!HASH.test(e.text_sha256||'')||sha256(e.text)!==e.text_sha256||
   !HASH.test(e.body_sha256||'')||!e.retrieved_at||e.http_status!==200)throw Error('Source completion evidence digest differs');}
 const fields=['schema_version','kind','run_id','trigger','scheduled_for','started_at','completed_at','status','receipt_path','source_request_id',
  'source_requests','source_workflow_verified','candidate_processing','gate_passed','native_completion_verified','publication_approved','scope_note'].sort();
 const path='config/content_review_run_receipts/'+runId+'.json';
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.kind!=='source_evidence_deferral'||receipt.run_id!==runId||
  receipt.trigger!=='schedule'||receipt.status!=='deferred'||receipt.receipt_path!==path||receipt.source_request_id!==requestId||
  receipt.source_requests!==counts.source||receipt.source_workflow_verified!==true||receipt.candidate_processing!==false||receipt.gate_passed!==false||
  receipt.native_completion_verified!==false||receipt.publication_approved!==false||time(receipt.started_at)!==start||time(receipt.scheduled_for)!==due||
  receipt.scope_note!=='Source retrieval was accounted; candidate gates, review readiness and publication are not established.')
  throw Error('Source completion receipt invalid');
 const expected=structuredClone(before);
 expected.lease_history??=[];if(!Array.isArray(expected.lease_history))throw Error('Source completion lease history invalid');
 expected.lease_history.push({...lease,status:'released',released_at:receipt.completed_at});expected.lease=null;
 expected.current_run.application_status='deferred';expected.current_run.application_completed_at=receipt.completed_at;expected.current_run.receipt=path;
 if(!equal(expected,after))throw Error('Source completion changes unrelated state');
 return {status:'valid',receipt_path:path,source_requests:counts.source,candidate_processing:false,native_completion_verified:false,publication_verified:false};
}
module.exports={validateSourceCompletion};
