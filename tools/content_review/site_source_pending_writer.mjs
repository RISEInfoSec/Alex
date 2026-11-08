// Release a source-pending lease after independently rechecking GitHub status.
// This preserves the request and never claims a gate or native completion.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {discoverSourceWorkflow} from './site_source_discovery_service.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import verifier from './verified_git_blob.cjs';
import guard from './site_source_pending_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};
export async function writeSourcePending({db,github,getToken,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,
 verify=verifyWorkerContext,discover=discoverSourceWorkflow,heartbeatFactory=makeHeartbeatKeeper}){
 if(!db||!github||typeof getToken!=='function'||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||
  typeof verify!=='function'||typeof discover!=='function'||typeof heartbeatFactory!=='function'||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['expectedHead','expectedMain','files','owner','reservationHead','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!SHA.test(input.reservationHead||'')||
  !ID.test(input.owner||'')||!ID.test(input.runId||'')||!input.files||typeof input.files!=='object'||Array.isArray(input.files))
  throw Error('Invalid source pending request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Source pending GitHub operation unavailable');
 const files=input.files,paths=Object.keys(files),receiptPath='config/content_review_run_receipts/'+input.runId+'.json';
 if(paths.length!==2||!paths.includes(WORKER)||!paths.includes(receiptPath)||paths.some(p=>typeof files[p]!=='string')||
  paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)throw Error('Invalid source pending file inventory');
 let after,receipt;try{after=JSON.parse(files[WORKER]);receipt=JSON.parse(files[receiptPath]);}catch{throw Error('Source pending JSON invalid');}
 if(!HASH.test(receipt.source_request_id||'')||receipt.run_id!==input.runId||receipt.reservation_head!==input.reservationHead)
  throw Error('Source pending receipt identity invalid');
 const requestPath='config/content_review_source_requests/'+receipt.source_request_id+'.json';
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source pending branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source pending head changed');};
 const readJson=async path=>verifier.verifiedJson(await github.fetchFile({repository_full_name:REPO,path,ref:input.expectedHead,require_content:true}),{limit:LIMIT});
 await checkHeads();await verify({github,input,now});
 const heartbeat=heartbeatFactory({github,input,now});
 const alive=async()=>{await heartbeat();await verify({github,input,now});};
 await alive();
 const before=await readJson(WORKER),request=await readJson(requestPath);
 const prior=await github.fetchFile({repository_full_name:REPO,path:receiptPath,ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Source pending receipt already exists');
 const snapshots=await read({db,heartbeat:async()=>{await alive();await checkHeads();}});
 if(!snapshots||snapshots.transactional_snapshot!==false||fingerprints.fingerprint(snapshots.snapshot)!==fingerprints.fingerprint(snapshots.confirmed_snapshot))
  throw Error('Source pending decision snapshot changed');
 await alive();
 const observed=await discover({github,getToken,input:{expectedHead:input.expectedHead,expectedMain:input.expectedMain,owner:input.owner,
  runId:input.runId,reservationHead:input.reservationHead},now,verify});
 const checked=guard.validateSourcePending({before,after,receipt,request,discovery:observed,snapshot:snapshots.snapshot,
  confirmed:snapshots.confirmed_snapshot,owner:input.owner,runId:input.runId,now:now()});
 if(checked.receipt_path!==receiptPath)throw Error('Source pending receipt verification differs');
 const details=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:input.expectedHead}),'Source pending base commit unavailable');
 if(details.sha!==input.expectedHead||!SHA.test(details.tree_sha||''))throw Error('Source pending base tree invalid');
 const additions=[];for(const path of paths.sort()){
  await alive();
  const expected=await verifier.blobIdentity(files[path],{limit:LIMIT});
  const blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Source pending blob failed');
  if(blob.sha!==expected)throw Error('Source pending blob mismatch');additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:details.tree_sha,tree_elements:additions}),'Source pending tree unavailable');
 if(!SHA.test(tree.sha||''))throw Error('Source pending tree invalid');
 await alive();
 const completed=Date.parse(receipt.completed_at||''),started=Date.parse(before.current_run?.started_at||''),expires=Date.parse(before.lease?.expires_at||'');
 if(!Number.isFinite(completed)||!Number.isFinite(started)||!Number.isFinite(expires)||completed>now()||now()-completed>180000||now()-started>720000||expires<=now())
  throw Error('Source pending proposal expired before fence');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,expectedHead:input.expectedHead,expectedMain:input.expectedMain,
  expectedTree:tree.sha,receiptPath,receiptBlob:additions.find(x=>x.path===receiptPath).sha,d1Fingerprint:fingerprints.fingerprint(snapshots.snapshot)};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Source pending fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Source pending fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Defer pending source request and release review lease'});}
  catch{throw Error('Source pending commit outcome ambiguous');}
  const committed=unwrap(update,'Source pending commit rejected or ambiguous');
  if(committed.success!==true||!SHA.test(committed.sha||''))throw Error('Source pending commit outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==committed.sha)throw Error('Source pending commit readback differs');
  return {status:'committed_and_read_back',commit_sha:committed.sha,receipt_path:receiptPath,source_status:observed.status,
          candidate_processing:false,native_completion_verified:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Source pending fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Source pending commit outcome ambiguous or unconfirmed; reconcile branch and fence');
  throw error;
 }
}
