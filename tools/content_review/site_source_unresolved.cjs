'use strict';
// Independently preserve unknown source outcomes without guessing provider use.
const {sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const {origin}=require('./site_source_origin_backoff.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/,REASON=/^[a-z_]{1,40}$/;
const matches=(pattern,value)=>typeof value==='string'&&pattern.test(value);
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const cmp=(a,b)=>a<b?-1:a>b?1:0;
function key(item){
 if(!object(item)||!matches(ID,item.collection)||!matches(ID,item.candidate_id)||!matches(HASH,item.content_sha256))
  throw Error('Unresolved source candidate is invalid');
 return {collection:item.collection,candidate_id:item.candidate_id,content_sha256:item.content_sha256};
}
function sortKeys(values){return values.sort((a,b)=>cmp(a.collection,b.collection)||cmp(a.candidate_id,b.candidate_id)||cmp(a.content_sha256,b.content_sha256));}
function fromFailure(request,pending,discovery){
 if(![request,pending,discovery].every(object))throw Error('Unresolved source evidence is incomplete');
 const rid=request.request_id,payload=Object.fromEntries(Object.entries(request).filter(([k])=>k!=='request_id'));
 const records=request.records,run=discovery.source_run_id,conclusion=discovery.conclusion;
 if(!matches(HASH,rid)||sha256(pyJson(payload))!==rid||pending.request_id!==rid||!matches(ID,pending.origin_run_id)||
  request.coordinator_run_id!==pending.origin_run_id||!Number.isSafeInteger(pending.reserved_limit)||pending.reserved_limit<1||pending.reserved_limit>30||
  request.source_request_limit!==pending.reserved_limit||discovery.status!=='source_run_failed'||!Number.isSafeInteger(run)||run<1||
  !matches(REASON,conclusion)||!Array.isArray(records)||records.length<1||records.length>5)throw Error('Unresolved source failure is invalid');
 const candidates=sortKeys(records.map(key));
 if(new Set(candidates.map(x=>JSON.stringify([x.collection,x.candidate_id]))).size!==candidates.length)
  throw Error('Unresolved source candidates are ambiguous');
 const hosts=[...new Set(records.map(x=>origin(x.url)))].sort();
 return {request_id:rid,origin_run_id:pending.origin_run_id,reserved_limit:pending.reserved_limit,source_run_id:run,
  conclusion,candidate_keys:candidates,origin_hosts:hosts,origin_provider_requests:null};
}
function validate(holds){
 if(!Array.isArray(holds)||holds.length>1000)throw Error('Unresolved source holds are invalid');
 const ids=new Set(),keys=new Set(),hosts=new Set(),fields=['request_id','origin_run_id','reserved_limit','source_run_id','conclusion',
  'candidate_keys','origin_hosts','origin_provider_requests'].sort();
 for(const hold of holds){
  if(!object(hold)||!equal(Object.keys(hold).sort(),fields)||!matches(HASH,hold.request_id)||ids.has(hold.request_id)||
   !matches(ID,hold.origin_run_id)||!Number.isSafeInteger(hold.reserved_limit)||hold.reserved_limit<1||hold.reserved_limit>30||
   !Number.isSafeInteger(hold.source_run_id)||hold.source_run_id<1||!matches(REASON,hold.conclusion)||hold.origin_provider_requests!==null)
   throw Error('Unresolved source hold is invalid');
  ids.add(hold.request_id);const candidates=hold.candidate_keys,origins=hold.origin_hosts;
  if(!Array.isArray(candidates)||candidates.length<1||candidates.length>5||!Array.isArray(origins)||origins.length<1||origins.length>5||
   candidates.some(x=>!object(x)||!equal(Object.keys(x).sort(),['candidate_id','collection','content_sha256'])))
   throw Error('Unresolved source hold inventory is invalid');
  const checked=candidates.map(key),sorted=sortKeys([...checked]);
  if(!equal(checked,sorted)||new Set(checked.map(x=>JSON.stringify([x.collection,x.candidate_id]))).size!==checked.length)
   throw Error('Unresolved source candidate inventory is invalid');
  if(origins.some(x=>typeof x!=='string'||origin('https://'+x)!==x)||!equal(origins,[...new Set(origins)].sort()))
   throw Error('Unresolved source origin inventory is invalid');
  for(const item of checked)keys.add(JSON.stringify([item.collection,item.candidate_id]));for(const host of origins)hosts.add(host);
 }
 return {keys,hosts};
}
module.exports={fromFailure,validate};
