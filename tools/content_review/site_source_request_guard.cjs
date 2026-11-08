'use strict';

// Independently validate a bounded source reservation. The caller must obtain
// committed manifests and D1 itself, then recheck decisions under the fence.
// A reservation is not a source result, gate pass or publication authority.
const {fingerprint,sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const {validateSnapshot,complete}=require('./site_duplicate_semantics.cjs');
const sourceBackoff=require('./site_source_origin_backoff.cjs');
const {identity:reviewIdentity}=require('./site_review_identity.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const COLLECTIONS=new Set(['weekly','bellingcat','first','m3aawg','sans','soups','virusbulletin']);
const field=(o,k,d=null)=>Object.prototype.hasOwnProperty.call(o,k)?o[k]:d;
const truthy=x=>Array.isArray(x)?x.length>0:object(x)?Object.keys(x).length>0:!!x;
function pass(row,g){const c=row.preflight?.checks?.[g];return object(c)&&c.status==='passed'&&c.content_sha256===row.content_sha256&&
 truthy(c.checked_at)&&truthy(c.evidence)&&!truthy(c.stale);}
function safeUrl(value){
 if(typeof value!=='string'||!value||/[\r\n\t]/.test(value))return false;
 let u;try{u=new URL(value);}catch{return false;}
 const host=u.hostname.toLowerCase().replace(/\.$/,'');
 return ['http:','https:'].includes(u.protocol)&&!!host&&!u.username&&!u.password&&
  (!u.port||(u.protocol==='https:'?u.port==='443':u.port==='80'))&&
  host!=='openalex.org'&&!host.endsWith('.openalex.org')&&host!=='api.openai.com';
}
function validateSourceRequest({before,after,request,manifests,manifestHashes,ledger,snapshot,confirmed,owner,runId,now=Date.now()}){
 if(!object(before)||!object(after)||!object(request)||!object(manifests)||!object(manifestHashes)||!object(ledger)||!object(ledger.records)||
  !ID.test(owner||'')||!ID.test(runId||'')||!Number.isFinite(now)||!complete(snapshot)||!complete(confirmed)||
  fingerprint(snapshot)!==fingerprint(confirmed))throw Error('Complete source reservation inputs required');
 validateSnapshot(snapshot);validateSnapshot(confirmed);
 const keys=['schema_version','started_at','work_deadline','lease_owner','source_request_limit','records','coordinator_run_id','request_id'].sort();
 const noId=Object.fromEntries(Object.entries(request).filter(([k])=>k!=='request_id'));
 const started=Date.parse(request.started_at||''),deadline=Date.parse(request.work_deadline||''),run=before.current_run||{},lease=before.lease||{};
 const counts=run.request_counts,when=Date.parse(after.current_run?.pending_source_request?.prepared_at||'');
 if(!equal(Object.keys(request).sort(),keys)||request.schema_version!==1||!HASH.test(request.request_id||'')||
  sha256(pyJson(noId))!==request.request_id||request.lease_owner!==owner||request.coordinator_run_id!==runId||
  lease.owner!==owner||lease.run_id!==runId||run.run_id!==runId||run.application_status!=='running'||
  !Number.isFinite(Date.parse(lease.acquired_at||''))||Date.parse(lease.acquired_at)>when||
  !Number.isFinite(Date.parse(lease.expires_at||''))||Date.parse(lease.expires_at)-now<=120000||
  !Number.isFinite(started)||started!==Date.parse(run.started_at||'')||deadline-started!==600000||
  !Number.isFinite(when)||when>now||now-when>180000||when<started||when>=deadline||now>=deadline||
  !object(counts)||!Number.isSafeInteger(counts.source)||counts.source<0||counts.source>=30||
  !Number.isSafeInteger(counts.paid)||counts.paid<0||counts.paid>5||counts.openalex!==0||
  request.source_request_limit!==30-counts.source||run.pending_source_request!=null||
  !Array.isArray(request.records)||request.records.length<1||request.records.length>5)
  throw Error('Invalid source request or budget');
 const expected=structuredClone(before);
 expected.current_run.pending_source_request={request_id:request.request_id,origin_run_id:runId,
  reserved_limit:request.source_request_limit,prepared_at:after.current_run.pending_source_request.prepared_at};
 if(!equal(expected,after))throw Error('Source reservation changes unrelated worker state');
 const seen=new Set();
 for(const item of request.records){
  if(!object(item)||!equal(Object.keys(item).sort(),['candidate_id','collection','content_sha256','manifest_sha256','url'])||
   !COLLECTIONS.has(item.collection)||!ID.test(item.candidate_id||'')||!HASH.test(item.content_sha256||'')||
   !HASH.test(item.manifest_sha256||'')||item.manifest_sha256!==manifestHashes[item.collection]||!safeUrl(item.url))
   throw Error('Invalid source candidate');
  const identity=JSON.stringify([item.collection,item.candidate_id]);if(seen.has(identity))throw Error('Duplicate source candidate');seen.add(identity);
  const manifest=manifests[item.collection];if(!object(manifest)||!Array.isArray(manifest.records)||!Array.isArray(manifest.preflight_records??[]))
   throw Error('Source manifest unavailable');
  const rows=[...manifest.records,...(manifest.preflight_records??[])].filter(x=>x?.candidate_id===item.candidate_id);
  if(rows.length!==1)throw Error('Source candidate ambiguous');const row=rows[0],content={};
  for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])content[k]=field(row,k,'');
  if(row.content_sha256!==item.content_sha256||sha256(pyJson(content))!==item.content_sha256||row.source_url!==item.url||
   !['pending','unreviewed'].includes(field(row,'decision','pending'))||row.publication_status==='published_live_verified'||
   row.publication_approved===true||!pass(row,'duplicates')||
   (pass(row,'format')&&pass(row,'access'))||(row.source_processing?.content_sha256===item.content_sha256&&['retrieved','held'].includes(row.source_processing?.retrieval_status))||
   sourceBackoff.active(before.source_origin_backoff??{},item.url,when))
   throw Error('Source candidate is ineligible');
  const entry=ledger.records[item.collection+':'+item.candidate_id];
  if(!object(entry)||entry.state!=='awaiting_initial_checks'||!Array.isArray(entry.attempts)||
   entry.attempts.some(a=>!object(a)||a.outcome!=='success')||
   (entry.next_retry_at&&(!Number.isFinite(Date.parse(entry.next_retry_at))||Date.parse(entry.next_retry_at)>when)))
   throw Error('Source lifecycle is outside guarded scope');
  const {number,batch}=reviewIdentity(item.collection,row,manifest);
  if(snapshot.submissions.some(s=>s.collection===item.collection&&s.batch===batch)||
   snapshot.decisions.some(d=>d.collection===item.collection&&(d.candidate_id===item.candidate_id||d.review_number===number))||
   snapshot.jobs.some(j=>j.collection===item.collection&&j.candidate_id===item.candidate_id))throw Error('Source candidate has review state');
 }
 return {status:'valid',request_path:'config/content_review_source_requests/'+request.request_id+'.json',
  source_request_limit:request.source_request_limit,candidate_processing:false,publication_verified:false};
}
module.exports={validateSourceRequest};
