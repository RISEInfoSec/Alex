// Site-only source gate writer. All private data and artifact provenance are
// obtained independently; HTTP input may provide only the proposed files.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {findLinearAncestor} from './site_linear_history.mjs';
import {readSourceArtifact} from './site_actions_artifact.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import verifier from './verified_git_blob.cjs';
import requestGuard from './site_source_request_guard.cjs';
import gateGuard from './site_source_gate_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const STATE='config/content_review_worker_status.json',LEDGER='config/content_review_candidate_lifecycle.json';
const STAGE='config/content_review_preflight_status.json',POLICY='config/content_review_lifecycle_policy.json',REGISTRY='config/review_console.json';
const LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const ok=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):obj(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));

export async function writeSourceGate({db,github,getToken,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,
 verify=verifyWorkerContext,artifactReader=readSourceArtifact,heartbeatFactory=makeHeartbeatKeeper,auditOnly=false}){
 if(!db||!github||typeof getToken!=='function'||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||
  typeof verify!=='function'||typeof artifactReader!=='function'||typeof heartbeatFactory!=='function'||typeof auditOnly!=='boolean'||!obj(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['expectedHead','expectedMain','files','owner','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||!obj(input.files))
  throw Error('Invalid source gate request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Source gate GitHub operation unavailable');
 const files=input.files,paths=Object.keys(files),receipts=paths.filter(p=>/^config\/content_review_source_gate_checkpoints\/[0-9a-f]{64}\.json$/.test(p));
 const manifests=paths.filter(p=>/^config\/[a-zA-Z0-9_-]+_review_manifest\.json$/.test(p));
 if(paths.length!==5||receipts.length!==1||manifests.length!==1||![LEDGER,STAGE,STATE].every(p=>paths.includes(p))||
  paths.some(p=>typeof files[p]!=='string')||paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)
  throw Error('Source gate file inventory invalid');
 let receipt,after;try{receipt=JSON.parse(files[receipts[0]]);after={manifest:JSON.parse(files[manifests[0]]),
  ledger:JSON.parse(files[LEDGER]),stage:JSON.parse(files[STAGE]),state:JSON.parse(files[STATE])};}catch{throw Error('Source gate JSON invalid');}
 if(receipt?.run_id!==input.runId||receipt.source_review_commit!==input.expectedHead||receipt.source_main_commit!==input.expectedMain||
  !ID.test(receipt.collection||'')||!ID.test(receipt.candidate_id||'')||!HASH.test(receipt.content_sha256||'')||
  !['format','access','metadata'].includes(receipt.gate)||!/^config\/content_review_source_receipts\/[0-9a-f]{64}\.json$/.test(receipt.source_receipt||''))
  throw Error('Source gate receipt identity invalid');
 const requestId=receipt.source_receipt.split('/').pop().slice(0,-5),requestPath='config/content_review_source_requests/'+requestId+'.json';
 const expectedReceipt='config/content_review_source_gate_checkpoints/'+fingerprints.sha256(input.runId+'\0'+receipt.collection+':'+receipt.candidate_id+'\0'+receipt.content_sha256+'\0'+receipt.gate)+'.json';
 if(receipts[0]!==expectedReceipt)throw Error('Source gate receipt path invalid');
 const head=async branch=>ok(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source gate branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source gate head changed');};
 const details=async sha=>{const x=ok(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:sha}),'Source gate history unavailable');
  if(x.sha!==sha||!SHA.test(x.tree_sha||'')||!Array.isArray(x.parents)||x.parents.some(p=>!SHA.test(p||'')))throw Error('Source gate history invalid');return x;};
 async function readJson(path,ref){const response=await github.fetchFile({repository_full_name:REPO,path,ref,require_content:true});
  const value=await verifier.verifiedJson(response,{limit:LIMIT}),raw=new TextEncoder().encode(response.structuredContent.content);
  return {value,sha:response.structuredContent.sha,hash:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),x=>x.toString(16).padStart(2,'0')).join('')};}
 await checkHeads();await verify({github,input,now});
 const registry=(await readJson(REGISTRY,input.expectedHead)).value,entries=Array.isArray(registry.collections)?registry.collections.filter(x=>x?.id===receipt.collection):[];
 if(entries.length!==1||!['soups','normalized'].includes(entries[0].adapter)||
  entries[0].manifest_url!=='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/'+manifests[0])throw Error('Source gate manifest differs from registry');
 const before={};for(const [key,path] of Object.entries({manifest:manifests[0],ledger:LEDGER,stage:STAGE,state:STATE,policy:POLICY}))
  before[key]=(await readJson(path,input.expectedHead)).value;
 const sourceReceipt=await readJson(receipt.source_receipt,input.expectedHead),sourceRequest=await readJson(requestPath,input.expectedHead);
 const prior=await github.fetchFile({repository_full_name:REPO,path:receipts[0],ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Source gate receipt already exists');
 const sourceRunId=sourceReceipt.value.native_run?.id,artifactId=sourceReceipt.value.artifact_id;
 if(!Number.isSafeInteger(sourceRunId)||sourceRunId<1||!Number.isSafeInteger(artifactId)||artifactId<1)throw Error('Source artifact identity unavailable');
 const heartbeat=heartbeatFactory({github,input,now});
 const snapshots=await read({db,heartbeat:async()=>{await heartbeat();await verify({github,input,now});}});
 if(!snapshots||snapshots.transactional_snapshot!==false||fingerprints.fingerprint(snapshots.snapshot)!==fingerprints.fingerprint(snapshots.confirmed_snapshot))
  throw Error('Source gate decision snapshot changed');
 const observed=await artifactReader({getToken,runId:sourceRunId,artifactId,heartbeat});
 const native=observed.native_run,artifact=observed.artifact,reservation=native?.head_sha;
 if(!SHA.test(reservation||'')||native?.id!==sourceRunId||native.event!=='push'||native.head_branch!==REVIEW||
  native.path!=='.github/workflows/content_review_sources.yml'||native.status!=='completed'||native.conclusion!=='success'||
  !Number.isSafeInteger(native.run_attempt)||native.run_attempt<1||artifact?.id!==artifactId||artifact.run_id!==sourceRunId||!HASH.test(artifact.sha256||'')||
  typeof observed.result_text!=='string'||fingerprints.sha256(observed.result_text)!==artifact.sha256)throw Error('Source gate artifact provenance invalid');
 let result;try{result=JSON.parse(observed.result_text);}catch{throw Error('Source gate artifact JSON invalid');}
 const request=sourceRequest.value,expectedSource={schema_version:1,independently_verified:true,request,
  native_run:Object.fromEntries(['id','event','head_branch','path','status','conclusion','head_sha','run_attempt'].map(k=>[k,native[k]])),
  artifact_id:artifact.id,artifact_sha256:artifact.sha256,result};
 if(!equal(sourceReceipt.value,expectedSource)||!obj(result)||result.schema_version!==1||result.status!=='complete'||result.read_only!==true||
  result.request_id!==requestId||!Array.isArray(request.records)||!Array.isArray(result.records)||!Array.isArray(result.request_log)||
  !Number.isSafeInteger(result.requests)||result.requests!==result.request_log.length||!Number.isSafeInteger(request.source_request_limit)||
  request.source_request_limit<1||request.source_request_limit>30||result.requests<0||result.requests>request.source_request_limit)
  throw Error('Source gate artifact receipt or budget differs');
 const provenance=result.provenance||{},expectedProvenance={GITHUB_SHA:reservation,GITHUB_RUN_ID:String(sourceRunId),GITHUB_RUN_ATTEMPT:String(native.run_attempt),
  GITHUB_REF:'refs/heads/'+REVIEW,GITHUB_WORKFLOW_REF:REPO+'/.github/workflows/content_review_sources.yml@refs/heads/'+REVIEW};
 if(Object.entries(expectedProvenance).some(([k,v])=>provenance[k]!==v))throw Error('Source gate artifact provenance differs');
 const key=x=>JSON.stringify([x?.collection,x?.candidate_id,x?.content_sha256]),requested=request.records.map(key),received=result.records.map(key);
 if(new Set(requested).size!==requested.length||new Set(received).size!==received.length||!equal([...requested].sort(),[...received].sort()))
  throw Error('Source gate artifact candidate set differs');
 for(const row of result.records){if(!obj(row)||!Array.isArray(row.evidence??[]))throw Error('Source gate evidence invalid');
  for(const e of row.evidence??[])if(!obj(e)||typeof e.text!=='string'||!HASH.test(e.text_sha256||'')||fingerprints.sha256(e.text)!==e.text_sha256||
   !HASH.test(e.body_sha256||'')||!e.retrieved_at||e.http_status!==200)throw Error('Source gate evidence digest differs');}
 const runs=[before.state.current_run,...(Array.isArray(before.state.run_history)?before.state.run_history:[])];
 const accounted=runs.flatMap(r=>Array.isArray(r?.accounted_source_requests)?r.accounted_source_requests:[]).filter(x=>x?.request_id===requestId);
 if(accounted.length!==1||accounted[0].artifact_id!==artifactId||accounted[0].artifact_sha256!==artifact.sha256||
  accounted[0].native_run_id!==sourceRunId||accounted[0].requests!==result.requests)throw Error('Source gate accounting differs');
 const reservationDetails=await findLinearAncestor({github,head:input.expectedHead,ancestor:reservation,heartbeat,details,
  linearError:'Source gate reservation outside linear history',boundedError:'Source gate reservation outside bounded history'});
 const parent=reservationDetails.parents[0],reservedRequest=await readJson(requestPath,reservation),reservedState=await readJson(STATE,reservation),
  oldState=await readJson(STATE,parent),oldLedger=await readJson(LEDGER,parent),oldRegistry=(await readJson(REGISTRY,parent)).value;
 if(reservedRequest.sha!==sourceRequest.sha||!equal(reservedRequest.value,request))throw Error('Source gate reservation changed');
 const sourceManifests={},manifestHashes={},root='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/config/';
 for(const collection of new Set(request.records.map(x=>x?.collection))){
  const e=Array.isArray(oldRegistry.collections)?oldRegistry.collections.filter(x=>x?.id===collection):[];
  if(e.length!==1||!['soups','normalized'].includes(e[0].adapter)||!e[0].manifest_url?.startsWith(root))throw Error('Source gate reservation manifest unavailable');
  const name=e[0].manifest_url.slice(root.length);if(!/^[a-zA-Z0-9_-]+_review_manifest\.json$/.test(name))throw Error('Source gate reservation manifest invalid');
  const m=await readJson('config/'+name,parent);sourceManifests[collection]=m.value;manifestHashes[collection]=m.hash;
 }
 requestGuard.validateSourceRequest({before:oldState.value,after:reservedState.value,request,manifests:sourceManifests,manifestHashes,
  ledger:oldLedger.value,snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,owner:request.lease_owner,
  runId:request.coordinator_run_id,now:Date.parse(reservedState.value.current_run?.pending_source_request?.prepared_at)});
 const parentDetails=await details(parent),reservationTree=ok(await github.createTree({repository_full_name:REPO,base_tree_sha:parentDetails.tree_sha,
  tree_elements:[{path:STATE,mode:'100644',type:'blob',sha:reservedState.sha},{path:requestPath,mode:'100644',type:'blob',sha:reservedRequest.sha}]}),
  'Source gate reservation tree unavailable');
 if(reservationTree.sha!==reservationDetails.tree_sha)throw Error('Source gate reservation contains unrelated changes');
 await verify({github,input,now});
 const validated=gateGuard.validateSourceGate({before,after,receipt,sourceReceipt:sourceReceipt.value,sourceReceiptBlob:sourceReceipt.sha,
  snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,now:now()});
 if(validated.receipt_path!==receipts[0])throw Error('Source gate validation differs');
 // Internal-only audit for a later run-receipt verifier; HTTP routes never
 // supply this option. The caller must separately verify the checkpoint tree.
 if(auditOnly)return {status:'validated',receipt_path:receipts[0],gate:receipt.gate,collection:receipt.collection,
  candidate_id:receipt.candidate_id,content_sha256:receipt.content_sha256,candidate_processing:true,publication_verified:false};
 const base=await details(input.expectedHead),additions=[];
 for(const path of paths.sort()){
  const sha=await verifier.blobIdentity(files[path],{limit:LIMIT}),blob=ok(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Source gate blob creation failed');
  if(blob.sha!==sha)throw Error('Source gate blob mismatch');additions.push({path,mode:'100644',type:'blob',sha});
 }
 const tree=ok(await github.createTree({repository_full_name:REPO,base_tree_sha:base.tree_sha,tree_elements:additions}),'Source gate tree unavailable');
 if(!SHA.test(tree.sha||''))throw Error('Source gate tree invalid');
 const checkedAt=Date.parse(receipt.checked_at||'');
 if(!Number.isFinite(checkedAt)||checkedAt>now()||now()-checkedAt>180000)throw Error('Source gate proposal expired before fence');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,expectedHead:input.expectedHead,expectedMain:input.expectedMain,
  expectedTree:tree.sha,receiptPath:receipts[0],receiptBlob:additions.find(x=>x.path===receipts[0]).sha,d1Fingerprint:fingerprints.fingerprint(snapshots.snapshot)};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Source gate fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Source gate fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Checkpoint retained source gate evidence'});}catch{throw Error('Source gate commit outcome ambiguous');}
  const committed=ok(update,'Source gate commit rejected or ambiguous');
  if(committed.success!==true||!SHA.test(committed.sha||''))throw Error('Source gate commit outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==committed.sha)throw Error('Source gate readback differs');
  return {status:'committed_and_read_back',commit_sha:committed.sha,receipt_path:receipts[0],gate:receipt.gate,
   candidate_processing:true,native_completion_verified:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Source gate fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Source gate commit outcome ambiguous or unconfirmed; reconcile branch and fence');throw error;
 }
}
