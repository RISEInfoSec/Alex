// Retain one independently verified source result without passing a gate.
// No HTTP input supplies D1, the GitHub connection, or source-result evidence.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {readSourceArtifact} from './site_actions_artifact.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import verifier from './verified_git_blob.cjs';
import requestGuard from './site_source_request_guard.cjs';
import retentionGuard from './site_source_retention_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LEDGER='config/content_review_candidate_lifecycle.json',REGISTRY='config/review_console.json';
const POLICY='config/content_review_workflow.json',LIMIT=12*1024*1024;
const SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const ok=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};
const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));

export async function writeSourceRetention({db,github,getToken,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,
 verify=verifyWorkerContext,artifactReader=readSourceArtifact,heartbeatFactory=makeHeartbeatKeeper}){
 if(!db||!github||typeof getToken!=='function'||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||
  typeof verify!=='function'||typeof artifactReader!=='function'||typeof heartbeatFactory!=='function'||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['artifactId','expectedHead','expectedMain','files','owner','runId','sourceRunId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  !Number.isSafeInteger(input.sourceRunId)||input.sourceRunId<1||!Number.isSafeInteger(input.artifactId)||input.artifactId<1||
  !input.files||typeof input.files!=='object'||Array.isArray(input.files))throw Error('Invalid source retention request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Source retention GitHub operation unavailable');
 const files=input.files,paths=Object.keys(files),receipts=paths.filter(p=>/^config\/content_review_source_checkpoints\/[0-9a-f]{64}\.json$/.test(p));
 const manifests=paths.filter(p=>/^config\/[a-zA-Z0-9_-]+_review_manifest\.json$/.test(p));
 if(paths.length!==3||receipts.length!==1||manifests.length!==1||!paths.includes(WORKER)||paths.some(p=>typeof files[p]!=='string')||
  paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)throw Error('Invalid source retention file inventory');
 let receipt,after,afterState;try{receipt=JSON.parse(files[receipts[0]]);after=JSON.parse(files[manifests[0]]);afterState=JSON.parse(files[WORKER]);}
 catch{throw Error('Source retention JSON invalid');}
 if(!HASH.test(receipt.request_id||'')||!ID.test(receipt.collection||'')||!ID.test(receipt.candidate_id||'')||
  receipt.run_id!==input.runId||receipt.source_review_commit!==input.expectedHead||receipt.source_main_commit!==input.expectedMain)
  throw Error('Source retention receipt identity invalid');
 const requestPath='config/content_review_source_requests/'+receipt.request_id+'.json';
 const sourceReceiptPath='config/content_review_source_receipts/'+receipt.request_id+'.json';
 const head=async branch=>ok(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source retention branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source retention head changed');};
 const details=async sha=>{const r=ok(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:sha}),'Source retention history unavailable');
  if(r.sha!==sha||!SHA.test(r.tree_sha||'')||!Array.isArray(r.parents)||r.parents.some(x=>!SHA.test(x||'')))throw Error('Source retention history invalid');return r;};
 async function readJson(path,ref){const response=await github.fetchFile({repository_full_name:REPO,path,ref,require_content:true});
  const value=await verifier.verifiedJson(response,{limit:LIMIT}),raw=new TextEncoder().encode(response.structuredContent.content);
  return {value,sha:response.structuredContent.sha,hash:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),x=>x.toString(16).padStart(2,'0')).join('')};}
 await checkHeads();await verify({github,input,now});
 const registry=(await readJson(REGISTRY,input.expectedHead)).value,entry=Array.isArray(registry.collections)?registry.collections.filter(x=>x?.id===receipt.collection):[];
 if(entry.length!==1||!['soups','normalized'].includes(entry[0].adapter)||
  entry[0].manifest_url!=='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/'+manifests[0])throw Error('Source retention manifest differs from registry');
 const before=(await readJson(manifests[0],input.expectedHead)).value,state=(await readJson(WORKER,input.expectedHead)).value;
 const policy=(await readJson(POLICY,input.expectedHead)).value?.bounded_processing_pilot||{},started=Date.parse(state.current_run?.started_at||''),expiry=Date.parse(state.lease?.expires_at||'');
 const checkWindow=()=>{const instant=now();
  if(!Number.isSafeInteger(policy.total_runtime_seconds)||!Number.isSafeInteger(policy.checkpoint_reserve_seconds)||policy.total_runtime_seconds>720||
   policy.checkpoint_reserve_seconds<120||policy.total_runtime_seconds<=policy.checkpoint_reserve_seconds||!Number.isFinite(started)||!Number.isFinite(expiry)||
   !Number.isFinite(instant)||instant<started||instant-started+20000>=(policy.total_runtime_seconds-policy.checkpoint_reserve_seconds)*1000||
   expiry-instant<=(policy.checkpoint_reserve_seconds+20)*1000)throw Error('Source retention has no checkpoint reserve');};
 checkWindow();
 const sourceRequest=await readJson(requestPath,input.expectedHead),sourceReceipt=(await readJson(sourceReceiptPath,input.expectedHead)).value;
 const prior=await github.fetchFile({repository_full_name:REPO,path:receipts[0],ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Source retention receipt already exists');
 const snapshots=await read({db,heartbeat:()=>verify({github,input,now})});
 if(!snapshots||snapshots.transactional_snapshot!==false||fingerprints.fingerprint(snapshots.snapshot)!==fingerprints.fingerprint(snapshots.confirmed_snapshot))
  throw Error('Source retention decision snapshot changed');
 const heartbeat=heartbeatFactory({github,input,now});
 const observed=await artifactReader({getToken,runId:input.sourceRunId,artifactId:input.artifactId,heartbeat});
 const reservation=observed.native_run?.head_sha;if(!SHA.test(reservation||''))throw Error('Source retention reservation unavailable');
 let cursor=input.expectedHead,reservationDetails=null;
 for(let i=0;i<20;i++){await heartbeat();const item=await details(cursor);if(cursor===reservation){reservationDetails=item;break;}
  if(item.parents.length!==1)throw Error('Source retention reservation outside linear history');cursor=item.parents[0];}
 if(!reservationDetails||reservationDetails.parents.length!==1)throw Error('Source retention reservation outside bounded history');
 const parent=reservationDetails.parents[0],reservedRequest=await readJson(requestPath,reservation),reservedState=await readJson(WORKER,reservation),
  oldState=await readJson(WORKER,parent),oldLedger=await readJson(LEDGER,parent),oldRegistry=(await readJson(REGISTRY,parent)).value;
 if(reservedRequest.sha!==sourceRequest.sha||!equal(reservedRequest.value,sourceRequest.value)||reservedRequest.value.request_id!==receipt.request_id)
  throw Error('Source retention reservation changed');
 const sourceManifests={},manifestHashes={},root='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/config/';
 if(!Array.isArray(reservedRequest.value.records))throw Error('Source reservation candidates unavailable');
 for(const collection of new Set(reservedRequest.value.records.map(x=>x?.collection))){
  const e=Array.isArray(oldRegistry.collections)?oldRegistry.collections.filter(x=>x?.id===collection):[];
  if(e.length!==1||!['soups','normalized'].includes(e[0].adapter)||!e[0].manifest_url?.startsWith(root))throw Error('Source reservation manifest unavailable');
  const name=e[0].manifest_url.slice(root.length);if(!/^[a-zA-Z0-9_-]+_review_manifest\.json$/.test(name))throw Error('Source reservation manifest invalid');
  const m=await readJson('config/'+name,parent);sourceManifests[collection]=m.value;manifestHashes[collection]=m.hash;
 }
 requestGuard.validateSourceRequest({before:oldState.value,after:reservedState.value,request:reservedRequest.value,manifests:sourceManifests,manifestHashes,
  ledger:oldLedger.value,snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,owner:reservedRequest.value.lease_owner,
  runId:reservedRequest.value.coordinator_run_id,now:Date.parse(reservedState.value.current_run?.pending_source_request?.prepared_at)});
 const parentDetails=await details(parent),reservationTree=ok(await github.createTree({repository_full_name:REPO,base_tree_sha:parentDetails.tree_sha,
  tree_elements:[{path:WORKER,mode:'100644',type:'blob',sha:reservedState.sha},{path:requestPath,mode:'100644',type:'blob',sha:reservedRequest.sha}]}),
  'Source reservation tree reconstruction unavailable');
 if(reservationTree.sha!==reservationDetails.tree_sha)throw Error('Source reservation contains unrelated changes');
 await verify({github,input,now});
 const checked=retentionGuard.validateSourceRetention({before,after,state,afterState,request:sourceRequest.value,sourceReceipt,receipt,
  nativeRun:observed.native_run,artifact:observed.artifact,resultText:observed.result_text,snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,
  owner:input.owner,runId:input.runId,now:now()});
 if(checked.receipt_path!==receipts[0])throw Error('Source retention receipt verification differs');
 const currentDetails=await details(input.expectedHead),additions=[];
 for(const path of paths.sort()){
  const expected=await verifier.blobIdentity(files[path],{limit:LIMIT}),blob=ok(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Source retention blob failed');
  if(blob.sha!==expected)throw Error('Source retention blob mismatch');additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const tree=ok(await github.createTree({repository_full_name:REPO,base_tree_sha:currentDetails.tree_sha,tree_elements:additions}),'Source retention tree unavailable');
 if(!SHA.test(tree.sha||''))throw Error('Source retention tree invalid');
 checkWindow();
 const checkedAt=Date.parse(receipt.checked_at||'');
 if(!Number.isFinite(checkedAt)||checkedAt>now()||now()-checkedAt>40000)throw Error('Source retention proposal expired before fence');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,expectedHead:input.expectedHead,expectedMain:input.expectedMain,
  expectedTree:tree.sha,receiptPath:receipts[0],receiptBlob:additions.find(x=>x.path===receipts[0]).sha,d1Fingerprint:fingerprints.fingerprint(snapshots.snapshot)};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Source retention fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Source retention fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Retain verified content review source evidence'});}
  catch{throw Error('Source retention commit outcome ambiguous');}
  const committed=ok(update,'Source retention commit rejected or ambiguous');
  if(committed.success!==true||!SHA.test(committed.sha||''))throw Error('Source retention commit outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==committed.sha)throw Error('Source retention commit readback differs');
  return {status:'committed_and_read_back',commit_sha:committed.sha,receipt_path:receipts[0],gate_passed:false,candidate_processing:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Source retention fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Source retention commit outcome ambiguous or unconfirmed; reconcile branch and fence');
  throw error;
 }
}
