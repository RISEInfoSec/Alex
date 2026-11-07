'use strict';

// This checks the precise source-retention transition, not its provenance.
// The future writer must independently load and verify the source artifact,
// request, accounting receipt and immutable Git inputs, and fence D1 on commit.
const {fingerprint,sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const {validateSnapshot,complete}=require('./site_duplicate_semantics.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const HASH=/^[0-9a-f]{64}$/,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const clone=x=>JSON.parse(JSON.stringify(x));
const field=(o,k,d='')=>Object.prototype.hasOwnProperty.call(o,k)?o[k]:d;
function validateSourceRetention({before,after,state,afterState,request,sourceReceipt,receipt,nativeRun,artifact,resultText,snapshot,confirmed,owner,runId,now=Date.now()}){
 if(![before,after,state,afterState,request,sourceReceipt,receipt,nativeRun,artifact].every(object)||typeof resultText!=='string'||
  !ID.test(owner||'')||!ID.test(runId||'')||!Number.isFinite(now)||!complete(snapshot)||!complete(confirmed)||
  fingerprint(snapshot)!==fingerprint(confirmed))throw Error('Complete source retention inputs required');
 validateSnapshot(snapshot);validateSnapshot(confirmed);
 let result;try{result=JSON.parse(resultText)}catch{throw Error('Source result JSON invalid')}
 const rid=request.request_id,when=Date.parse(receipt.checked_at||'');
 if(!HASH.test(rid||'')||sha256(pyJson(Object.fromEntries(Object.entries(request).filter(([k])=>k!=='request_id'))))!==rid||
  !HASH.test(artifact.sha256||'')||sha256(resultText)!==artifact.sha256||artifact.id!==sourceReceipt.artifact_id||
  artifact.run_id!==nativeRun.id||!Number.isSafeInteger(artifact.id)||artifact.id<1||
  !object(result)||result.schema_version!==1||result.status!=='complete'||result.read_only!==true||result.request_id!==rid||
  nativeRun.event!=='push'||nativeRun.head_branch!=='codex/soups-corpus-review'||
  nativeRun.path!=='.github/workflows/content_review_sources.yml'||nativeRun.status!=='completed'||nativeRun.conclusion!=='success'||
  !Number.isSafeInteger(nativeRun.id)||nativeRun.id<1||!Number.isSafeInteger(nativeRun.run_attempt)||nativeRun.run_attempt<1||!SHA.test(nativeRun.head_sha||''))
  throw Error('Source artifact is not verified');
 const proof=result.provenance||{},expected={GITHUB_SHA:nativeRun.head_sha,GITHUB_RUN_ID:String(nativeRun.id),
  GITHUB_RUN_ATTEMPT:String(nativeRun.run_attempt),GITHUB_REF:'refs/heads/codex/soups-corpus-review',
  GITHUB_WORKFLOW_REF:'RISEInfoSec/Alex/.github/workflows/content_review_sources.yml@refs/heads/codex/soups-corpus-review'};
 if(Object.entries(expected).some(([k,v])=>proof[k]!==v)||!Array.isArray(request.records)||!Array.isArray(result.records)||
  !Array.isArray(result.request_log)||!Number.isSafeInteger(result.requests)||result.requests!==result.request_log.length||
  !Number.isSafeInteger(request.source_request_limit)||request.source_request_limit<1||request.source_request_limit>30||
  result.requests<0||result.requests>request.source_request_limit)throw Error('Source provenance or budget differs');
 const key=x=>JSON.stringify([x?.collection,x?.candidate_id,x?.content_sha256]),requested=request.records.map(key),received=result.records.map(key);
 if(new Set(requested).size!==requested.length||new Set(received).size!==received.length||!equal([...requested].sort(),[...received].sort()))
  throw Error('Source result candidate set differs');
 for(const row of result.records){if(!object(row)||!Array.isArray(row.evidence??[]))throw Error('Source evidence invalid');
  for(const e of row.evidence??[])if(!object(e)||typeof e.text!=='string'||!HASH.test(e.text_sha256||'')||sha256(e.text)!==e.text_sha256||
   !HASH.test(e.body_sha256||'')||!e.retrieved_at||e.http_status!==200)throw Error('Source evidence digest differs');}
 const nativeFields=['id','event','head_branch','path','status','conclusion','head_sha','run_attempt'];
 if(!equal(sourceReceipt,{schema_version:1,independently_verified:true,request,
  native_run:Object.fromEntries(nativeFields.map(k=>[k,nativeRun[k]])),artifact_id:artifact.id,artifact_sha256:artifact.sha256,result}))
  throw Error('Source receipt differs');
 const entries=[state.current_run,...(Array.isArray(state.run_history)?state.run_history:[])].flatMap(r=>Array.isArray(r?.accounted_source_requests)?r.accounted_source_requests:[])
  .filter(x=>x?.request_id===rid);
 if(entries.length!==1||entries[0].artifact_id!==artifact.id||entries[0].artifact_sha256!==artifact.sha256||
  entries[0].native_run_id!==nativeRun.id||entries[0].requests!==result.requests||!equal(state,afterState))throw Error('Source accounting or worker state differs');
 const fields=['schema_version','kind','request_id','collection','candidate_id','content_sha256','result_status','artifact_sha256','run_id','checked_at',
  'source_review_commit','source_main_commit','provider_requests','openalex_requests','paid_requests','publication_approved'].sort();
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.kind!=='source_retention'||receipt.request_id!==rid||
  receipt.run_id!==runId||!ID.test(receipt.collection||'')||!ID.test(receipt.candidate_id||'')||!HASH.test(receipt.content_sha256||'')||
  receipt.artifact_sha256!==artifact.sha256||!SHA.test(receipt.source_review_commit||'')||!SHA.test(receipt.source_main_commit||'')||
  !Number.isFinite(when)||when>now||now-when>40000||receipt.provider_requests!==0||receipt.openalex_requests!==0||receipt.paid_requests!==0||
  receipt.publication_approved!==false||state.lease?.owner!==owner||state.lease?.run_id!==runId||!Number.isFinite(Date.parse(state.lease?.expires_at||''))||Date.parse(state.lease.expires_at)<=now||
  state.current_run?.run_id!==runId||state.current_run?.application_status!=='running')throw Error('Retention receipt or lease invalid');
 const matches=result.records.filter(x=>x.collection===receipt.collection&&x.candidate_id===receipt.candidate_id&&x.content_sha256===receipt.content_sha256);
 if(matches.length!==1||!['retrieved','held'].includes(matches[0].status)||matches[0].status!==receipt.result_status||
  typeof matches[0].next_action!=='string'||!matches[0].next_action||!Array.isArray(matches[0].evidence)||
  (matches[0].status==='retrieved'&&!matches[0].evidence.length))throw Error('Source candidate result invalid');
 const item=matches[0],copy=clone(before),old=[];
 for(const section of ['records','preflight_records']){
  const rows=copy[section]??[];if(!Array.isArray(rows))throw Error('Manifest inventory invalid');
  for(const row of rows)if(row?.candidate_id===receipt.candidate_id)old.push(row);
 }
 if(old.length!==1)throw Error('Candidate missing or ambiguous');
 const row=old[0],content={};for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])content[k]=field(row,k);
 if(!['pending','unreviewed'].includes(field(row,'decision','pending'))||row.content_sha256!==receipt.content_sha256||
  sha256(pyJson(content))!==row.content_sha256||!Number.isSafeInteger(row.review_number)||row.review_number<1||
  row.publication_status==='published_live_verified'||row.publication_approved===true)throw Error('Candidate changed or is not pending');
 const batch=row.review_batch??row.batch??(receipt.collection==='soups'?(row.review_number<=100?Math.ceil(row.review_number/20):
  row.review_number<=118?6:7+Math.floor((row.review_number-119)/20)):Math.ceil(row.review_number/20));
 if(!Number.isSafeInteger(batch)||batch<1||snapshot.decisions.some(d=>d.collection===receipt.collection&&(d.candidate_id===receipt.candidate_id||d.review_number===row.review_number))||
  snapshot.submissions.some(s=>s.collection===receipt.collection&&s.batch===batch)||snapshot.jobs.some(j=>j.collection===receipt.collection&&j.candidate_id===receipt.candidate_id))
  throw Error('Candidate has review state');
 const receiptPath='config/content_review_source_receipts/'+rid+'.json';
 if(row.source_processing?.receipt===receiptPath||!Array.isArray(row.source_processing_history??[]))throw Error('Source evidence already retained or history invalid');
 row.source_processing_history??=[];row.source_processing_history.push(clone(row.source_processing??{}));
 row.source_processing={content_sha256:row.content_sha256,retrieval_status:item.status,receipt:receiptPath,
  reason:item.reason??null,next_action:item.next_action,evidence_sha256:item.evidence.map(e=>e.body_sha256)};
 if(!equal(copy,after))throw Error('Source retention changed unrelated candidate data');
 const path='config/content_review_source_checkpoints/'+sha256(rid+'\0'+receipt.collection+'\0'+receipt.candidate_id+'\0'+receipt.content_sha256)+'.json';
 return {status:'valid',receipt_path:path,gate_passed:false,publication_authorized:false};
}
module.exports={validateSourceRetention};
