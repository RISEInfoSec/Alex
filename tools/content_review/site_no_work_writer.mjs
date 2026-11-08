// Release a worker lease with a strictly validated no-work receipt. Only the
// private Site route may construct the GitHub client. No action here claims
// useful processing, native terminal success or publication.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import jsonVerifier from './verified_git_blob.cjs';
import guard from './run_no_work_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LIMIT=1024*1024,SHA=/^[0-9a-f]{40}$/;
const ID=/^[a-zA-Z0-9-]{1,100}$/;
const unwrap=(r,msg)=>{if(!r||r.isError||!r.structuredContent)throw Error(msg);return r.structuredContent;};

export async function writeNoWork({db,github,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,verify=verifyWorkerContext,heartbeatFactory=makeHeartbeatKeeper}){
 if(!db||!github||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||typeof verify!=='function'||typeof heartbeatFactory!=='function'||
  !input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['expectedHead','expectedMain','files','owner','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  !input.files||typeof input.files!=='object'||Array.isArray(input.files))throw Error('Invalid no-work request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('No-work GitHub operation unavailable');
 const receiptPath='config/content_review_run_receipts/'+input.runId+'.json',files=input.files,paths=Object.keys(files);
 if(paths.length!==2||!paths.includes(WORKER)||!paths.includes(receiptPath)||paths.some(p=>typeof files[p]!=='string')||
  paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)throw Error('Invalid no-work file inventory');
 let after,receipt;try{after=JSON.parse(files[WORKER]);receipt=JSON.parse(files[receiptPath]);}catch{throw Error('No-work JSON invalid');}
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'No-work branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('No-work source head changed');};
 await checkHeads();await verify({github,input,now,manualScope:'duplicate_only'});
 const heartbeat=heartbeatFactory({github,input,now});
 const alive=async()=>{await heartbeat();await verify({github,input,now,manualScope:'duplicate_only'});};
 await alive();
 const baseFile=await github.fetchFile({repository_full_name:REPO,path:WORKER,ref:input.expectedHead,require_content:true});
 const before=await jsonVerifier.verifiedJson(baseFile,{limit:LIMIT});
 guard.validateNoWork({before,after,receipt,owner:input.owner,runId:input.runId,now:now()});
 const prior=await github.fetchFile({repository_full_name:REPO,path:receiptPath,ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('No-work receipt is not confirmed absent');
 const snapshots=await read({db,heartbeat:async()=>{await alive();await checkHeads();}});
 if(!snapshots||snapshots.transactional_snapshot!==false||
  fingerprints.fingerprint(snapshots.snapshot)!==fingerprints.fingerprint(snapshots.confirmed_snapshot))throw Error('No-work decision snapshot changed');
 const privateFingerprint=fingerprints.fingerprint(snapshots.snapshot);
 const details=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:input.expectedHead}),'No-work base commit unavailable');
 if(details.sha!==input.expectedHead||!SHA.test(details.tree_sha||''))throw Error('No-work base tree unavailable');
 const additions=[];
 for(const path of paths.sort()){
  await alive();
  const expected=await jsonVerifier.blobIdentity(files[path],{limit:LIMIT});
  const blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'No-work blob creation failed');
  if(blob.sha!==expected)throw Error('No-work blob mismatch');
  additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:details.tree_sha,tree_elements:additions}),'No-work tree creation failed');
 if(!SHA.test(tree.sha||''))throw Error('No-work tree identity invalid');
 await alive();
 if(now()-Date.parse(receipt.completed_at)>180000)throw Error('No-work proposal expired before fence');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,
  expectedHead:input.expectedHead,expectedMain:input.expectedMain,expectedTree:tree.sha,receiptPath,
  receiptBlob:additions.find(x=>x.path===receiptPath).sha,d1Fingerprint:privateFingerprint};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;
  if((await control({db,github,input:fence,now,manualScope:'duplicate_only'})).status!=='acquired')throw Error('No-work fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now,manualScope:'duplicate_only'})).status!=='committing')throw Error('No-work fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
    additions:paths.map(path=>({path,content:files[path]})),message:'Record no-work outcome and release review lease'});}
  catch{throw Error('No-work commit outcome ambiguous');}
  const result=unwrap(update,'No-work commit rejected or ambiguous');
  if(result.success!==true||!SHA.test(result.sha||''))throw Error('No-work commit outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now,manualScope:'duplicate_only'});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==result.sha)throw Error('No-work commit readback differs');
  return {status:'committed_and_read_back',commit_sha:result.sha,receipt_path:receiptPath,
   candidate_processing:false,native_completion_verified:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){
   let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now,manualScope:'duplicate_only'})).status==='aborted';}catch{}
   if(!aborted)throw Error('No-work fence state unconfirmed; inspect fence');
  }
  if(commitAttempted)throw Error('No-work commit outcome ambiguous or unconfirmed; reconcile branch and fence');
  throw error;
 }
}
