// Independent, read-only duplicate evidence for a candidate. A clear result
// is only one prerequisite for a checkpoint: it does not authorize a write,
// establish a lease, reconcile D1, or prove scheduler execution. A historical
// expectedReview is usable only after the caller independently verifies that
// it is an ancestor of currentReview; this audit does not prove ancestry.
import identity from './conservative_identity.cjs';
import blobs from './verified_git_blob.cjs';
import rows from './stream_csv.cjs';
import guard from './soups_intake_site_guard.cjs';
import hashes from './d1_fingerprint.cjs';
import apwg from './site_apwg_adapter.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const SHA=/^[0-9a-f]{40}$/,SHA256=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const ROOT='https://raw.githubusercontent.com/RISEInfoSec/Alex/';
const MAX_JSON=12*1024*1024,MAX_COLLECTIONS=30,MAX_ROWS=10000;
const object=x=>x&&typeof x==='object'&&!Array.isArray(x);

function manifestLocation(entry,review,main){
 if(!object(entry)||!ID.test(entry.id||'')||typeof entry.manifest_url!=='string')throw Error('Invalid registry entry');
 const reviewRoot=ROOT+REVIEW+'/config/',mainRoot=ROOT+MAIN+'/config/';
 const root=entry.manifest_url.startsWith(reviewRoot)?reviewRoot:entry.manifest_url.startsWith(mainRoot)?mainRoot:null;
 const name=root&&entry.manifest_url.slice(root.length);
 if(!root||!/^[a-zA-Z0-9_-]+\.json$/.test(name||''))throw Error('Invalid registry manifest');
 return {path:'config/'+name,ref:root===reviewRoot?review:main};
}

export async function auditDuplicateInputs({github,expectedReview,expectedMain,collection,candidateId,heartbeat=async()=>({renewed:false}),
 currentReview=expectedReview}){
 if(!github||!SHA.test(expectedReview||'')||!SHA.test(expectedMain||'')||!ID.test(collection||'')||!ID.test(candidateId||'')||
    !SHA.test(currentReview||'')||typeof heartbeat!=='function'||['fetchCommit','fetchFile','streamBlob'].some(method=>typeof github[method]!=='function'))throw Error('Invalid audit request');
 const proofs=new Map();let heartbeatUpdates=0,heartbeatFailure=null;
 async function pulse(){try{const result=await heartbeat();if(result?.renewed===true)heartbeatUpdates++;}
  catch(error){heartbeatFailure=error;throw error;}}
 async function heads(){
  await pulse();
  const [a,b]=await Promise.all([github.fetchCommit({repo_full_name:REPO,commit_sha:REVIEW}),github.fetchCommit({repo_full_name:REPO,commit_sha:MAIN})]);
  if(a?.isError||b?.isError||a?.structuredContent?.commit?.sha!==currentReview||b?.structuredContent?.commit?.sha!==expectedMain)
   throw Error('Audit source heads changed');
 }
 async function json(path,ref,allowArray=false){
  await pulse();
  const result=await github.fetchFile({repository_full_name:REPO,path,ref,require_content:true}),v=!result?.isError&&result?.structuredContent;
  if(!v||!SHA.test(v.sha||'')||typeof v.content!=='string'||await blobs.blobIdentity(v.content,{limit:MAX_JSON})!==v.sha)
   throw Error('Audit immutable source unavailable');
  const bytes=new TextEncoder().encode(v.content),digest=await crypto.subtle.digest('SHA-256',bytes);
  const contentHash=Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
  proofs.set(ref+':'+path,{commit:ref,path,blob_sha:v.sha,size:bytes.length,sha256:contentHash});
  let value;try{value=JSON.parse(v.content);}catch{throw Error('Audit JSON invalid');}
  if(!object(value)&&!(allowArray&&Array.isArray(value)))throw Error('Audit JSON shape invalid');
  return {value,sha:v.sha};
 }
 await heads();
 const registry=(await json('config/review_console.json',expectedReview)).value.collections;
 if(!Array.isArray(registry)||!registry.length||registry.length>MAX_COLLECTIONS)throw Error('Audit registry unavailable');
 const locations=new Map();
 for(const entry of registry){const location=manifestLocation(entry,expectedReview,expectedMain);
  if(locations.has(entry.id))throw Error('Audit registry ambiguous');locations.set(entry.id,location);}
 const initialPaths=['config/review_console.json','config/content_review_candidate_lifecycle.json','config/content_review_lifecycle_policy.json',
  'config/content_review_preflight_status.json','config/content_review_worker_status.json','config/content_review_defects.json',
  'config/content_review_workflow.json','config/content_review_material_policy.json'];
 for(const path of initialPaths.slice(1))await json(path,expectedReview);
 if(!locations.has(collection))throw Error('Candidate collection unavailable');
 const source=locations.get(collection),manifest=(await json(source.path,source.ref)).value;
 const sourceRows=[...(manifest.records||[]),...(manifest.preflight_records||[])];
 if(!Array.isArray(manifest.records)||!Array.isArray(manifest.preflight_records||[])||sourceRows.length>MAX_ROWS)
  throw Error('Audit candidate manifest unavailable');
 const selected=sourceRows.filter(x=>object(x)&&x.candidate_id===candidateId);
 if(selected.length!==1||!SHA256.test(selected[0].content_sha256||''))throw Error('Audit candidate ambiguous');
 const candidate=selected[0],content={};
 for(const key of ['title','authors','year','doi','source_url','abstract','document_type'])
  content[key]=Object.prototype.hasOwnProperty.call(candidate,key)?candidate[key]:'';
 if(hashes.sha256(guard.pyJson(content))!==candidate.content_sha256)throw Error('Audit candidate content changed');
 const profile=identity.profile(candidate);let matches=0,scanned=0;
 function check(item){if(!object(item))throw Error('Audit row invalid');scanned++;if(identity.possiblyMatches(profile,item))matches++;}
 const publicRows=(await json('data/papers.json',expectedMain,true)).value;
 if(!Array.isArray(publicRows)||!publicRows.length||publicRows.length>MAX_ROWS)throw Error('Audit public corpus unavailable');
 for(const row of publicRows)check(row);
 let apwgPending=null;
 for(const [name,location] of locations){
  const m=name===collection?manifest:(await json(location.path,location.ref)).value;
  if(!Array.isArray(m.records)||!Array.isArray(m.preflight_records||[]))throw Error('Audit collection unavailable');
  if(name==='apwg')apwgPending=apwg.normalize(m).records.length;
  const all=[...m.records,...(m.preflight_records||[])];if(all.length>MAX_ROWS)throw Error('Audit collection exceeds bound');
  for(const row of all){if(name===collection&&(row?.candidate_id===candidateId||row?.discovery_identity===candidateId))continue;check(row);}
 }
 const exclusions=(await json('config/corpus_exclusions.json',expectedMain)).value;
 if(exclusions.schema_version!==1||!Array.isArray(exclusions.records)||exclusions.records.length>MAX_ROWS)throw Error('Audit exclusions unavailable');
 for(const row of exclusions.records){
  if(!object(row)||row.decision!=='rejected'||!row.submission_id||!SHA256.test(row.reviewed_content_sha256||''))throw Error('Audit exclusion invalid');
  const text=x=>typeof x==='string'&&x.trim().length>0;
  const url=x=>text(x)&&/^https?:\/\/[^/?#\s]+/i.test(x.trim());
  if(!text(row.title)&&!text(row.doi)&&!url(row.source_url)&&!url(row.link))throw Error('Audit exclusion identity unavailable');
  check(row);
 }
 const inventory=(await json('config/weekly_source_inventory.json',expectedReview)).value;
 if(!SHA.test(inventory.source_blob_sha||'')||!SHA256.test(inventory.source_sha256||'')||!Array.isArray(inventory.records)||
    inventory.records.length!==inventory.raw_records||inventory.raw_records>50000)throw Error('Audit retained inventory unavailable');
 const retained=new rows.CsvRows((row,index)=>{const entry=inventory.records[index];
  if(!entry||entry.row!==index||entry.upstream_id!==String(row.candidate_id)||!SHA256.test(entry.content_sha256||''))throw Error('Audit retained row mismatch');
  check(row);
 });
 const old=await github.streamBlob({repository_full_name:REPO,sha:inventory.source_blob_sha,onProgress:pulse,onChunk:async chunk=>{await pulse();retained.update(chunk);}});
 if(heartbeatFailure)throw heartbeatFailure;
 if(old?.isError||old?.structuredContent?.sha!==inventory.source_blob_sha||old?.structuredContent?.sha256!==inventory.source_sha256||
    retained.finish().rows!==inventory.raw_records)throw Error('Audit retained inventory incomplete');
 const meta=await github.fetchFile({repository_full_name:REPO,path:'data/review_queue.csv',ref:expectedMain});
 if(meta?.isError||!SHA.test(meta?.structuredContent?.sha||''))throw Error('Audit current queue unavailable');
 const current=new rows.CsvRows(row=>check(row));
 const recent=await github.streamBlob({repository_full_name:REPO,sha:meta.structuredContent.sha,onProgress:pulse,onChunk:async chunk=>{await pulse();current.update(chunk);}});
 if(heartbeatFailure)throw heartbeatFailure;
 if(recent?.isError||recent?.structuredContent?.sha!==meta.structuredContent.sha||!Number.isSafeInteger(recent.structuredContent.size)||
  !SHA256.test(recent.structuredContent.sha256||''))throw Error('Audit current queue incomplete');
 proofs.set(expectedMain+':data/review_queue.csv',{commit:expectedMain,path:'data/review_queue.csv',blob_sha:recent.structuredContent.sha,
  size:recent.structuredContent.size,sha256:recent.structuredContent.sha256});
 const currentCount=current.finish().rows;
 await heads();
 if(!Number.isSafeInteger(old.structuredContent.size))throw Error('Audit retained size unavailable');
 const ordered=[...initialPaths.map(path=>expectedReview+':'+path),...[...locations.values()].map(x=>x.ref+':'+x.path),
  expectedMain+':data/papers.json',expectedMain+':config/corpus_exclusions.json',expectedMain+':data/review_queue.csv',
  expectedReview+':config/weekly_source_inventory.json'];
 const inputBlobs=[];for(const key of new Set(ordered)){const proof=proofs.get(key);if(!proof)throw Error('Audit provenance unavailable');inputBlobs.push(proof);}
 inputBlobs.push({blob_sha:inventory.source_blob_sha,size:old.structuredContent.size,sha256:old.structuredContent.sha256});
 return {status:matches?'held':'clear',candidate_key_sha256:hashes.sha256(collection+'\0'+candidateId+'\0'+candidate.content_sha256),
  possible_matches:matches,records_examined:scanned,collections_examined:locations.size,
  retained_rows:inventory.raw_records,current_rows:currentCount,review_commit:expectedReview,main_commit:expectedMain,
  input_blobs:inputBlobs,apwg_pending:apwgPending,candidate_processing:false,candidate_writes:0,heartbeat_updates:heartbeatUpdates};
}
