// Finalize exactly one independently reconstructed duplicate checkpoint.
// This releases the lease but never claims native scheduler completion or
// publication. The route constructs all clients and D1 access itself.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {verifyCheckpoint} from './site_checkpoint_readback.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import verifier from './verified_git_blob.cjs';
import guard from './site_run_complete_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LIMIT=1024*1024,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};

export async function writeCompletion({db,github,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,
 verify=verifyWorkerContext,check=verifyCheckpoint,heartbeatFactory=makeHeartbeatKeeper}){
 if(!db||!github||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||typeof verify!=='function'||
  typeof check!=='function'||typeof heartbeatFactory!=='function'||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['checkpointCommits','expectedHead','expectedMain','files','owner','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  !input.files||typeof input.files!=='object'||Array.isArray(input.files)||!input.checkpointCommits||
  typeof input.checkpointCommits!=='object'||Array.isArray(input.checkpointCommits))throw Error('Invalid completion request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','streamBlob','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Completion GitHub operation unavailable');
 const receiptPath='config/content_review_run_receipts/'+input.runId+'.json',files=input.files,paths=Object.keys(files);
 if(paths.length!==2||!paths.includes(WORKER)||!paths.includes(receiptPath)||paths.some(p=>typeof files[p]!=='string')||
  paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)throw Error('Invalid completion file inventory');
 let after,receipt;try{after=JSON.parse(files[WORKER]);receipt=JSON.parse(files[receiptPath]);}catch{throw Error('Completion JSON invalid');}
 const action=Array.isArray(receipt?.completed_actions)&&receipt.completed_actions.length===1?receipt.completed_actions[0]:null;
 const checkpointPath=action?.path,keys=Object.keys(input.checkpointCommits);
 if(!action||keys.length!==1||keys[0]!==checkpointPath||!SHA.test(input.checkpointCommits[checkpointPath]||''))
  throw Error('Completion checkpoint inventory invalid');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Completion branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Completion source head changed');};
 await checkHeads();await verify({github,input,now});
 const before=await verifier.verifiedJson(await github.fetchFile({repository_full_name:REPO,path:WORKER,ref:input.expectedHead,require_content:true}),{limit:LIMIT});
 const prior=await github.fetchFile({repository_full_name:REPO,path:receiptPath,ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Completion receipt is not confirmed absent');
 const heartbeat=heartbeatFactory({github,input,now});
 const snapshots=await read({db,heartbeat:async()=>{await heartbeat();await verify({github,input,now});}});
 if(!snapshots||snapshots.transactional_snapshot!==false||
  fingerprints.fingerprint(snapshots.snapshot)!==fingerprints.fingerprint(snapshots.confirmed_snapshot))throw Error('Completion decision snapshot changed');
 const verifiedAction=await check({github,input,checkpointCommit:input.checkpointCommits[checkpointPath],path:checkpointPath,
  snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,heartbeat});
 await verify({github,input,now});
 guard.validateComplete({before,after,receipt,owner:input.owner,runId:input.runId,verifiedAction,now:now()});
 const privateFingerprint=fingerprints.fingerprint(snapshots.snapshot);
 const details=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:input.expectedHead}),'Completion base commit unavailable');
 if(details.sha!==input.expectedHead||!SHA.test(details.tree_sha||''))throw Error('Completion base tree unavailable');
 const additions=[];
 for(const path of paths.sort()){
  const expected=await verifier.blobIdentity(files[path],{limit:LIMIT});
  const blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Completion blob creation failed');
  if(blob.sha!==expected)throw Error('Completion blob mismatch');
  additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:details.tree_sha,tree_elements:additions}),'Completion tree creation failed');
 if(!SHA.test(tree.sha||''))throw Error('Completion tree identity invalid');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,expectedHead:input.expectedHead,
  expectedMain:input.expectedMain,expectedTree:tree.sha,receiptPath,receiptBlob:additions.find(x=>x.path===receiptPath).sha,d1Fingerprint:privateFingerprint};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Completion fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Completion fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Record verified review checkpoint and release lease'});}
  catch{throw Error('Completion commit outcome ambiguous');}
  const result=unwrap(update,'Completion commit rejected or ambiguous');
  if(result.success!==true||!SHA.test(result.sha||''))throw Error('Completion commit outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==result.sha)throw Error('Completion commit readback differs');
  return {status:'committed_and_read_back',commit_sha:result.sha,receipt_path:receiptPath,candidate_processing:true,
   native_completion_verified:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Completion fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Completion commit outcome ambiguous or unconfirmed; reconcile branch and fence');
  throw error;
 }
}
