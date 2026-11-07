// Independently account for one completed source artifact. The caller supplies
// only GitHub IDs; the Site fetches the run, ZIP, request and D1 itself.
// This never applies candidate evidence or authorizes publication.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {readSourceArtifact} from './site_actions_artifact.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import verifier from './verified_git_blob.cjs';
import requestGuard from './site_source_request_guard.cjs';
import resultGuard from './site_source_result_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LEDGER='config/content_review_candidate_lifecycle.json',REGISTRY='config/review_console.json';
const LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const positive=x=>Number.isSafeInteger(x)&&x>0;
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};
const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));

export async function writeSourceResult({db,github,getToken,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,
 verify=verifyWorkerContext,artifactReader=readSourceArtifact,heartbeatFactory=makeHeartbeatKeeper}){
 if(!db||!github||typeof getToken!=='function'||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||
  typeof verify!=='function'||typeof artifactReader!=='function'||typeof heartbeatFactory!=='function'||
  !input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['artifactId','expectedHead','expectedMain','files','owner','runId','sourceRunId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  !positive(input.sourceRunId)||!positive(input.artifactId)||!input.files||typeof input.files!=='object'||Array.isArray(input.files))
  throw Error('Invalid source result request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Source result GitHub operation unavailable');
 const files=input.files,paths=Object.keys(files),receipts=paths.filter(p=>/^config\/content_review_source_receipts\/[0-9a-f]{64}\.json$/.test(p));
 if(paths.length!==2||receipts.length!==1||!paths.includes(WORKER)||paths.some(p=>typeof files[p]!=='string')||
  paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)throw Error('Invalid source result file inventory');
 let after,receipt;try{after=JSON.parse(files[WORKER]);receipt=JSON.parse(files[receipts[0]]);}catch{throw Error('Source result JSON invalid');}
 const requestId=receipts[0].slice(receipts[0].lastIndexOf('/')+1,-5),requestPath='config/content_review_source_requests/'+requestId+'.json';
 if(!HASH.test(requestId||''))throw Error('Source result identity invalid');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source result branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source result head changed');};
 const details=async sha=>{const r=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:sha}),'Source result history unavailable');
  if(r.sha!==sha||!SHA.test(r.tree_sha||'')||!Array.isArray(r.parents)||r.parents.some(x=>!SHA.test(x||'')))throw Error('Source result history invalid');return r;};
 async function readJson(path,ref){const response=await github.fetchFile({repository_full_name:REPO,path,ref,require_content:true});
  const value=await verifier.verifiedJson(response,{limit:LIMIT}),content=response.structuredContent.content,raw=new TextEncoder().encode(content);
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),x=>x.toString(16).padStart(2,'0')).join('');
  return {value,sha:response.structuredContent.sha,hash};}
 await checkHeads();await verify({github,input,now});
 const before=(await readJson(WORKER,input.expectedHead)).value,currentRequest=await readJson(requestPath,input.expectedHead);
 const prior=await github.fetchFile({repository_full_name:REPO,path:receipts[0],ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Source result receipt already exists');
 const snapshots=await read({db,heartbeat:()=>verify({github,input,now})});
 if(!snapshots||snapshots.transactional_snapshot!==false||
  fingerprints.fingerprint(snapshots.snapshot)!==fingerprints.fingerprint(snapshots.confirmed_snapshot))throw Error('Source result decision snapshot changed');
 const heartbeat=heartbeatFactory({github,input,now});
 const observed=await artifactReader({getToken,runId:input.sourceRunId,artifactId:input.artifactId,heartbeat});
 const reservation=observed.native_run?.head_sha;if(!SHA.test(reservation||''))throw Error('Source result reservation unavailable');
 let cursor=input.expectedHead,reservationDetails=null;
 for(let i=0;i<20;i++){
  await heartbeat();const item=await details(cursor);if(cursor===reservation){reservationDetails=item;break;}
  if(item.parents.length!==1)throw Error('Source reservation outside linear history');cursor=item.parents[0];
 }
 if(!reservationDetails||reservationDetails.parents.length!==1)throw Error('Source reservation outside bounded history');
 const parent=reservationDetails.parents[0],reservedRequest=await readJson(requestPath,reservation),reservedState=await readJson(WORKER,reservation),
  oldState=await readJson(WORKER,parent),oldLedger=await readJson(LEDGER,parent),registry=(await readJson(REGISTRY,parent)).value;
 if(reservedRequest.sha!==currentRequest.sha||!equal(reservedRequest.value,currentRequest.value)||reservedRequest.value.request_id!==requestId)
  throw Error('Source reservation request changed');
 const manifests={},manifestHashes={},root='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/config/';
 if(!Array.isArray(reservedRequest.value.records))throw Error('Source reservation candidates unavailable');
 for(const collection of new Set(reservedRequest.value.records.map(x=>x?.collection))){
  const entries=Array.isArray(registry.collections)?registry.collections.filter(x=>x?.id===collection):[];
  if(entries.length!==1||!['soups','normalized'].includes(entries[0].adapter)||!entries[0].manifest_url?.startsWith(root))
   throw Error('Source reservation manifest unavailable');
  const name=entries[0].manifest_url.slice(root.length);if(!/^[a-zA-Z0-9_-]+_review_manifest\.json$/.test(name))throw Error('Source reservation manifest invalid');
  const m=await readJson('config/'+name,parent);manifests[collection]=m.value;manifestHashes[collection]=m.hash;
 }
 requestGuard.validateSourceRequest({before:oldState.value,after:reservedState.value,request:reservedRequest.value,manifests,manifestHashes,
  ledger:oldLedger.value,snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,owner:reservedRequest.value.lease_owner,
  runId:reservedRequest.value.coordinator_run_id,now:Date.parse(reservedState.value.current_run?.pending_source_request?.prepared_at)});
 const parentDetails=await details(parent),tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:parentDetails.tree_sha,
  tree_elements:[{path:WORKER,mode:'100644',type:'blob',sha:reservedState.sha},{path:requestPath,mode:'100644',type:'blob',sha:reservedRequest.sha}]}),
  'Source reservation tree reconstruction unavailable');
 if(tree.sha!==reservationDetails.tree_sha)throw Error('Source reservation contains unrelated changes');
 await verify({github,input,now});
 const checked=resultGuard.validateSourceResult({before,after,request:currentRequest.value,receipt,nativeRun:observed.native_run,
  artifact:observed.artifact,resultText:observed.result_text,snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,
  owner:input.owner,runId:input.runId,now:now()});
 if(checked.receipt_path!==receipts[0])throw Error('Source result receipt identity differs');
 const privateFingerprint=fingerprints.fingerprint(snapshots.snapshot),currentDetails=await details(input.expectedHead),additions=[];
 for(const path of paths.sort()){
  const expected=await verifier.blobIdentity(files[path],{limit:LIMIT});
  const blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Source result blob failed');
  if(blob.sha!==expected)throw Error('Source result blob mismatch');additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const proposedTree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:currentDetails.tree_sha,tree_elements:additions}),
  'Source result tree unavailable');
 if(!SHA.test(proposedTree.sha||''))throw Error('Source result tree invalid');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,expectedHead:input.expectedHead,
  expectedMain:input.expectedMain,expectedTree:proposedTree.sha,receiptPath:receipts[0],
  receiptBlob:additions.find(x=>x.path===receipts[0]).sha,d1Fingerprint:privateFingerprint};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Source result fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Source result fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Record verified source evidence accounting'});}
  catch{throw Error('Source result commit outcome ambiguous');}
  const committed=unwrap(update,'Source result commit rejected or ambiguous');
  if(committed.success!==true||!SHA.test(committed.sha||''))throw Error('Source result commit outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==committed.sha)throw Error('Source result commit readback differs');
  return {status:'committed_and_read_back',commit_sha:committed.sha,receipt_path:receipts[0],source_requests:checked.source_requests,
   source_workflow_verified:true,candidate_processing:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Source result fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Source result commit outcome ambiguous or unconfirmed; reconcile branch and fence');
  throw error;
 }
}
