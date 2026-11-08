// Release a source-gate run only after reconstructing and independently
// re-auditing the exact checkpoint, then rechecking D1 under its fence.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {verifySourceGateCheckpoint} from './site_source_gate_readback.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import verifier from './verified_git_blob.cjs';
import guard from './site_source_gate_completion_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LIMIT=1024*1024,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};

export async function writeSourceGateCompletion({db,github,getToken,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,
 verify=verifyWorkerContext,check=verifySourceGateCheckpoint,heartbeatFactory=makeHeartbeatKeeper}){
 if(!db||!github||typeof getToken!=='function'||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||typeof verify!=='function'||
  typeof check!=='function'||typeof heartbeatFactory!=='function'||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['checkpointCommit','expectedHead','expectedMain','files','owner','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||input.checkpointCommit!==input.expectedHead||
  !ID.test(input.owner||'')||!ID.test(input.runId||'')||!input.files||typeof input.files!=='object'||Array.isArray(input.files))
  throw Error('Invalid source gate completion request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Source gate completion GitHub operation unavailable');
 const receiptPath='config/content_review_run_receipts/'+input.runId+'.json',files=input.files,paths=Object.keys(files);
 if(paths.length!==2||!paths.includes(WORKER)||!paths.includes(receiptPath)||paths.some(p=>typeof files[p]!=='string')||
  paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)throw Error('Source gate completion files invalid');
 let after,receipt;try{after=JSON.parse(files[WORKER]);receipt=JSON.parse(files[receiptPath]);}catch{throw Error('Source gate completion JSON invalid');}
 const action=Array.isArray(receipt?.completed_actions)&&receipt.completed_actions.length===1?receipt.completed_actions[0]:null;
 if(!action||!/^config\/content_review_source_gate_checkpoints\/[0-9a-f]{64}\.json$/.test(action.path||''))
  throw Error('Source gate completion action invalid');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source gate completion branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source gate completion head changed');};
 await checkHeads();await verify({github,input,now});
 const before=await verifier.verifiedJson(await github.fetchFile({repository_full_name:REPO,path:WORKER,ref:input.expectedHead,require_content:true}),{limit:LIMIT});
 const prior=await github.fetchFile({repository_full_name:REPO,path:receiptPath,ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Source gate completion receipt already exists');
 const snapshots=await read({db,heartbeat:()=>verify({github,input,now})});
 if(!snapshots||snapshots.transactional_snapshot!==false||fingerprints.fingerprint(snapshots.snapshot)!==fingerprints.fingerprint(snapshots.confirmed_snapshot))
  throw Error('Source gate completion decision snapshot changed');
 const heartbeat=heartbeatFactory({github,input,now});
 const verifiedAction=await check({github,getToken,input,checkpointCommit:input.checkpointCommit,path:action.path,
  snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,heartbeat,verify:async()=>{await checkHeads();await verify({github,input,now});},now});
 await checkHeads();await verify({github,input,now});
 guard.validateSourceGateCompletion({before,after,receipt,owner:input.owner,runId:input.runId,verifiedAction,now:now()});
 const details=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:input.expectedHead}),'Source gate completion base unavailable');
 if(details.sha!==input.expectedHead||!SHA.test(details.tree_sha||''))throw Error('Source gate completion base tree invalid');
 const additions=[];
 for(const path of paths.sort()){
  const sha=await verifier.blobIdentity(files[path],{limit:LIMIT}),blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Source gate completion blob failed');
  if(blob.sha!==sha)throw Error('Source gate completion blob mismatch');additions.push({path,mode:'100644',type:'blob',sha});
 }
 const tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:details.tree_sha,tree_elements:additions}),'Source gate completion tree unavailable');
 if(!SHA.test(tree.sha||''))throw Error('Source gate completion tree invalid');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,expectedHead:input.expectedHead,
  expectedMain:input.expectedMain,expectedTree:tree.sha,receiptPath,receiptBlob:additions.find(x=>x.path===receiptPath).sha,
  d1Fingerprint:fingerprints.fingerprint(snapshots.snapshot)};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Source gate completion fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Source gate completion fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Record source gate completion and release lease'});}catch{throw Error('Source gate completion outcome ambiguous');}
  const result=unwrap(update,'Source gate completion rejected or ambiguous');
  if(result.success!==true||!SHA.test(result.sha||''))throw Error('Source gate completion outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==result.sha)throw Error('Source gate completion readback differs');
  return {status:'committed_and_read_back',commit_sha:result.sha,receipt_path:receiptPath,candidate_processing:true,
   native_completion_verified:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Source gate completion fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Source gate completion outcome ambiguous or unconfirmed; reconcile branch and fence');throw error;
 }
}
