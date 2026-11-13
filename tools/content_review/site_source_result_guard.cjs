'use strict';

// Independent source-result accounting. The caller must read the GitHub run,
// archive and request itself and recheck D1 under the live fence. This does
// not apply candidate evidence or claim a preflight pass.
const {fingerprint,sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const {validateSnapshot,complete}=require('./site_duplicate_semantics.cjs');
const sourceBackoff=require('./site_source_origin_backoff.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const HASH=/^[0-9a-f]{64}$/,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const positive=x=>Number.isSafeInteger(x)&&x>0,time=x=>typeof x==='string'?Date.parse(x):NaN;

function validateSourceResult({before,after,request,receipt,nativeRun,artifact,resultText,snapshot,confirmed,owner,runId,now=Date.now()}){
 if(!object(before)||!object(after)||!object(request)||!object(receipt)||!object(nativeRun)||!object(artifact)||typeof resultText!=='string'||
  !ID.test(owner||'')||!ID.test(runId||'')||!Number.isFinite(now)||!complete(snapshot)||!complete(confirmed)||
  fingerprint(snapshot)!==fingerprint(confirmed))throw Error('Complete source result inputs required');
 validateSnapshot(snapshot);validateSnapshot(confirmed);
 let result;try{result=JSON.parse(resultText);}catch{throw Error('Source result JSON invalid');}
 if(!object(result)||result.schema_version!==1||result.status!=='complete'||result.read_only!==true||
  !HASH.test(request.request_id||'')||sha256(pyJson(Object.fromEntries(Object.entries(request).filter(([k])=>k!=='request_id'))))!==request.request_id||
  !positive(artifact.id)||artifact.run_id!==nativeRun.id||!HASH.test(artifact.sha256||'')||!HASH.test(artifact.archive_sha256||'')||
  sha256(resultText)!==artifact.sha256)throw Error('Source artifact identity invalid');
 if(!positive(nativeRun.id)||nativeRun.event!=='push'||nativeRun.head_branch!=='codex/soups-corpus-review'||
  nativeRun.path!=='.github/workflows/content_review_sources.yml'||nativeRun.status!=='completed'||nativeRun.conclusion!=='success'||
  !SHA.test(nativeRun.head_sha||'')||!positive(nativeRun.run_attempt))throw Error('Source workflow is not verified');
 const provenance=result.provenance||{},expectedProvenance={GITHUB_SHA:nativeRun.head_sha,GITHUB_RUN_ID:String(nativeRun.id),
  GITHUB_RUN_ATTEMPT:String(nativeRun.run_attempt),GITHUB_REF:'refs/heads/codex/soups-corpus-review',
  GITHUB_WORKFLOW_REF:'RISEInfoSec/Alex/.github/workflows/content_review_sources.yml@refs/heads/codex/soups-corpus-review'};
 if(result.request_id!==request.request_id||Object.entries(expectedProvenance).some(([k,v])=>provenance[k]!==v)||
  !Array.isArray(request.records)||!Array.isArray(result.records)||!Array.isArray(result.request_log)||
  !Number.isSafeInteger(result.requests)||result.requests!==result.request_log.length||result.requests<0||
  !Number.isSafeInteger(request.source_request_limit)||request.source_request_limit<1||request.source_request_limit>30||
  result.requests>request.source_request_limit)throw Error('Source result provenance or budget invalid');
 const key=x=>JSON.stringify([x?.collection,x?.candidate_id,x?.content_sha256]);
 const expectedCandidates=request.records.map(key),actual=result.records.map(key);
 if(new Set(expectedCandidates).size!==expectedCandidates.length||new Set(actual).size!==actual.length||!equal([...expectedCandidates].sort(),[...actual].sort()))
  throw Error('Source result candidate set differs');
 for(const row of result.records){
  if(!object(row)||!Array.isArray(row.evidence??[]))throw Error('Source result evidence invalid');
  for(const e of row.evidence??[]){
   if(!object(e)||typeof e.text!=='string'||!HASH.test(e.text_sha256||'')||sha256(e.text)!==e.text_sha256||
    !HASH.test(e.body_sha256||'')||!e.retrieved_at||e.http_status!==200)throw Error('Source evidence digest invalid');
  }
 }
 const lease=before.lease||{},current=before.current_run||{},started=time(current.started_at),requestStarted=time(request.started_at),deadline=time(request.work_deadline);
 const counts=current.request_counts,pending=current.pending_source_request||{},origin=request.coordinator_run_id;
 if(lease.owner!==owner||lease.run_id!==runId||!Number.isFinite(time(lease.expires_at))||time(lease.expires_at)<=now||
  current.run_id!==runId||current.application_status!=='running'||!Number.isFinite(started)||now<started||now-started>720000||
  !Number.isFinite(requestStarted)||!Number.isFinite(deadline)||deadline<=requestStarted||deadline-requestStarted>600000||
  !object(counts)||!Number.isSafeInteger(counts.source)||counts.source<0||counts.source>30||
  !Number.isSafeInteger(counts.paid)||counts.paid<0||counts.paid>5||counts.openalex!==0||!ID.test(origin||'')||
  pending.origin_run_id!==origin||pending.request_id!==request.request_id||pending.reserved_limit!==request.source_request_limit)
  throw Error('Source result lacks live matching reservation');
 const history=current.accounted_source_requests??[];
 if(!Array.isArray(history)||history.some(x=>!object(x))||history.some(x=>x.request_id===request.request_id))throw Error('Source result already accounted');
 const sameRun=origin===runId;let original=current;
 if(sameRun){if(request.lease_owner!==owner)throw Error('Source result lease owner differs');}
 else{
  const runs=before.run_history,leases=before.lease_history,matches=Array.isArray(runs)?runs.filter(x=>x?.run_id===origin):[];
  if(matches.length!==1||!Array.isArray(leases)||!leases.some(x=>x?.run_id===origin&&x.owner===request.lease_owner&&['released','expired'].includes(x.status))||
   !equal(matches[0].pending_source_request,pending))throw Error('Original source reservation unavailable');
  original=matches[0];
 }
 const originalCounts=original.request_counts||{};
 if(time(original.started_at)!==requestStarted||!Number.isSafeInteger(originalCounts.source)||originalCounts.source<0||originalCounts.source>=30||
  request.source_request_limit!==30-originalCounts.source||(sameRun&&result.requests>30-counts.source))throw Error('Source accounting budget differs');
 const entry={request_id:request.request_id,artifact_id:artifact.id,artifact_sha256:artifact.sha256,native_run_id:nativeRun.id,
  requests:result.requests,origin_run_id:origin,charged_to_current_run:sameRun};
 const expected=structuredClone(before);
 if(sameRun)expected.current_run.request_counts.source+=result.requests;
 const cooldowns=sourceBackoff.merge(before.source_origin_backoff??{},result,request.request_id);
 if(Object.keys(cooldowns).length||Object.prototype.hasOwnProperty.call(expected,'source_origin_backoff'))expected.source_origin_backoff=cooldowns;
 expected.current_run.accounted_source_requests??=[];expected.current_run.accounted_source_requests.push(entry);expected.current_run.pending_source_request=null;
 const nativeFields=['id','event','head_branch','path','status','conclusion','head_sha','run_attempt'];
 const expectedReceipt={schema_version:1,independently_verified:true,request,native_run:Object.fromEntries(nativeFields.map(k=>[k,nativeRun[k]])),
  artifact_id:artifact.id,artifact_sha256:artifact.sha256,result};
 if(!equal(expected,after)||!equal(expectedReceipt,receipt))throw Error('Source accounting changes unrelated state or evidence');
 return {status:'valid',receipt_path:'config/content_review_source_receipts/'+request.request_id+'.json',
  source_requests:result.requests,candidate_processing:false,publication_verified:false};
}
module.exports={validateSourceResult};
