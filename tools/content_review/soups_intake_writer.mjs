// Site-only bounded SOUPS intake writer. The Site route must construct github
// from the existing Site credential; never accept API objects, callbacks,
// private snapshots or a claimed proof from an HTTP caller.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import jsonVerifier from './verified_git_blob.cjs';
import validator from './soups_intake_site_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const MANIFEST='config/soups_review_manifest.json',LEDGER='config/content_review_candidate_lifecycle.json';
const STAGE='config/content_review_preflight_status.json',POLICY='config/content_review_lifecycle_policy.json';
const LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw new Error(msg);return x.structuredContent;};

export async function writeIntake({db,github,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,verify=verifyWorkerContext}){
 if(!db||!github||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||typeof verify!=='function'||
    !input||typeof input!=='object'||Array.isArray(input)||
    JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['expectedHead','expectedMain','files','owner','runId'])||
    !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
    !input.files||typeof input.files!=='object'||Array.isArray(input.files))throw new Error('Invalid intake request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw new Error('Intake GitHub operation unavailable');
 const files=input.files,paths=Object.keys(files),receipts=paths.filter(x=>/^config\/content_review_intake_receipts\/[0-9a-f]{64}\.json$/.test(x));
 if(paths.length!==4||receipts.length!==1||![MANIFEST,LEDGER,STAGE].every(p=>paths.includes(p))||
    paths.some(p=>typeof files[p]!=='string'))throw new Error('Invalid intake file inventory');
 let total=0;for(const path of paths){total+=new TextEncoder().encode(files[path]).length;if(total>LIMIT)throw new Error('Intake file limit exceeded');}
 let receipt,after;
 try{receipt=JSON.parse(files[receipts[0]]);after={manifest:JSON.parse(files[MANIFEST]),ledger:JSON.parse(files[LEDGER]),stage:JSON.parse(files[STAGE])};}
 catch{throw new Error('Intake JSON invalid');}
 if(receipt?.run_id!==input.runId||receipt.source_review_commit!==input.expectedHead||receipt.source_main_commit!==input.expectedMain||
    !Array.isArray(receipt.selected))throw new Error('Intake receipt identity invalid');
 const expectedReceipt='config/content_review_intake_receipts/'+fingerprints.sha256(input.runId+'\0'+input.expectedHead+'\0'+receipt.selected.join('\0'))+'.json';
 if(receipts[0]!==expectedReceipt)throw new Error('Intake receipt path invalid');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Intake branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw new Error('Intake source head changed');};
 await checkHeads();
 await verify({github,input,now});
 const before={};
 for(const [key,path] of Object.entries({manifest:MANIFEST,ledger:LEDGER,stage:STAGE,policy:POLICY})){
  const result=await github.fetchFile({repository_full_name:REPO,path,ref:input.expectedHead,require_content:true});
  before[key]=await jsonVerifier.verifiedJson(result,{limit:LIMIT});
 }
 const priorReceipt=await github.fetchFile({repository_full_name:REPO,path:receipts[0],ref:input.expectedHead});
 if(!priorReceipt?.isError||priorReceipt.structuredContent?.error_code!=='NOT_FOUND')throw new Error('Intake receipt is not confirmed absent');
 // This initial read is a preparation check, not evidence of a live lease.
 // controlFence independently checks the actual lease/heartbeat and repeats
 // the private snapshot while the decision fence is held.
 const snapshots=await read({db,heartbeat:checkHeads});
 validator.validateIntake({before,after,snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,receipt,now:now()});
 const privateFingerprint=fingerprints.fingerprint(snapshots.snapshot);
 const details=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:input.expectedHead}),'Intake base commit unavailable');
 if(details.sha!==input.expectedHead||!SHA.test(details.tree_sha||''))throw new Error('Intake base tree unavailable');
 const additions=[];
 for(const path of paths.sort()){
  const expected=await jsonVerifier.blobIdentity(files[path],{limit:LIMIT});
  const blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Intake blob creation failed');
  if(blob.sha!==expected)throw new Error('Intake blob mismatch');
  additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:details.tree_sha,tree_elements:additions}),'Intake tree creation failed');
 if(!SHA.test(tree.sha||''))throw new Error('Intake tree identity invalid');
 if(now()-Date.parse(receipt.prepared_at)>40000)throw new Error('Intake proposal expired before fence');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,
  expectedHead:input.expectedHead,expectedMain:input.expectedMain,expectedTree:tree.sha,receiptPath:receipts[0],
  receiptBlob:additions.find(x=>x.path===receipts[0]).sha,d1Fingerprint:privateFingerprint};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;
  if((await control({db,github,input:fence,now})).status!=='acquired')throw new Error('Intake fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw new Error('Intake fence did not enter commit');
  commitAttempted=true;
  let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
       additions:paths.map(path=>({path,content:files[path]})),message:'Reserve bounded SOUPS intake'});}
  catch{throw new Error('Intake commit outcome ambiguous; fence remains held');}
  const result=unwrap(update,'Intake commit rejected or ambiguous; fence remains held');
  if(result.success!==true||!SHA.test(result.sha||''))throw new Error('Intake commit outcome ambiguous; fence remains held');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==result.sha)
   throw new Error('Intake commit readback differs; reconcile fence');
  return {status:'committed_and_read_back',commit_sha:result.sha,receipt_path:receipts[0],
   candidate_count:receipt.selected.length,candidate_processing:false,publication_verified:false};
 }catch(error){
  // Only the preparing phase can be aborted. Once a GitHub update may have
  // started, an ambiguous outcome must retain the fence for reconciliation.
  if(mayHaveFence&&!commitAttempted){try{await control({db,github,input:{...fence,action:'abort'},now});}catch{}}
  throw error;
 }
}
