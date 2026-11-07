// Site-only duplicate writer. The route constructs github from the existing
// Site credential; proposals cannot supply snapshots, audit results, proofs,
// callbacks or connector objects. The independent audit and semantic guard
// run before any Git object is created, and D1 is rechecked under its fence.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import {auditDuplicateInputs} from './site_duplicate_audit.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import jsonVerifier from './verified_git_blob.cjs';
import validator from './site_duplicate_semantics.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const LEDGER='config/content_review_candidate_lifecycle.json',STAGE='config/content_review_preflight_status.json';
const STATE='config/content_review_worker_status.json',POLICY='config/content_review_lifecycle_policy.json',REGISTRY='config/review_console.json';
const LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const COLLECTIONS=new Set(['weekly','bellingcat','first','m3aawg','sans','soups']);
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};

export async function writeDuplicate({db,github,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,
 verify=verifyWorkerContext,audit=auditDuplicateInputs}){
 if(!db||!github||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||typeof verify!=='function'||typeof audit!=='function'||
  !input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['expectedHead','expectedMain','files','owner','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  !input.files||typeof input.files!=='object'||Array.isArray(input.files))throw Error('Invalid duplicate request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','streamBlob','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Duplicate GitHub operation unavailable');
 const files=input.files,paths=Object.keys(files),receipts=paths.filter(p=>/^config\/content_review_mechanical_checkpoints\/[0-9a-f]{64}\.json$/.test(p));
 const manifests=paths.filter(p=>/^config\/[a-zA-Z0-9_-]+_review_manifest\.json$/.test(p));
 if(paths.length!==5||receipts.length!==1||manifests.length!==1||![LEDGER,STAGE,STATE].every(p=>paths.includes(p))||
  paths.some(p=>typeof files[p]!=='string'))throw Error('Invalid duplicate file inventory');
 let size=0;for(const path of paths){size+=new TextEncoder().encode(files[path]).length;if(size>LIMIT)throw Error('Duplicate file limit exceeded');}
 let receipt,after;
 try{receipt=JSON.parse(files[receipts[0]]);after={manifest:JSON.parse(files[manifests[0]]),ledger:JSON.parse(files[LEDGER]),
  stage:JSON.parse(files[STAGE]),state:JSON.parse(files[STATE])};}catch{throw Error('Duplicate JSON invalid');}
 if(!receipt||receipt.run_id!==input.runId||receipt.source_review_commit!==input.expectedHead||receipt.source_main_commit!==input.expectedMain||
  !COLLECTIONS.has(receipt.collection)||!ID.test(receipt.candidate_id||'')||!HASH.test(receipt.content_sha256||''))
  throw Error('Duplicate receipt identity invalid');
 const expectedReceipt='config/content_review_mechanical_checkpoints/'+fingerprints.sha256(input.runId+'\0'+receipt.collection+':'+receipt.candidate_id+'\0'+receipt.content_sha256)+'.json';
 if(receipts[0]!==expectedReceipt)throw Error('Duplicate receipt path invalid');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Duplicate branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Duplicate source head changed');};
 await checkHeads();await verify({github,input,now});
 const registry=await jsonVerifier.verifiedJson(await github.fetchFile({repository_full_name:REPO,path:REGISTRY,ref:input.expectedHead,require_content:true}),{limit:LIMIT});
 const entries=Array.isArray(registry.collections)?registry.collections.filter(x=>x?.id===receipt.collection):[];
 if(entries.length!==1||entries[0].manifest_url!=='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/'+manifests[0]||
  !['soups','normalized'].includes(entries[0].adapter))throw Error('Duplicate manifest differs from registry');
 // This scan is independent of the proposed gate and checks all registered
 // collections, the public corpus, exclusions and retained/current queues.
 const evidence=await audit({github,expectedReview:input.expectedHead,expectedMain:input.expectedMain,
  collection:receipt.collection,candidateId:receipt.candidate_id});
 await verify({github,input,now});
 const expectedEvidence={method:'complete immutable corpus, exclusions, registered collections and upstream inventories',
  review_commit:input.expectedHead,main_commit:input.expectedMain,input_blobs:evidence.input_blobs,
  matches:[],exclusions:[],upstream_aliases:[]};
 const before={};
 for(const [key,path] of Object.entries({manifest:manifests[0],ledger:LEDGER,stage:STAGE,state:STATE,policy:POLICY}))
  before[key]=await jsonVerifier.verifiedJson(await github.fetchFile({repository_full_name:REPO,path,ref:input.expectedHead,require_content:true}),{limit:LIMIT});
 const prior=await github.fetchFile({repository_full_name:REPO,path:receipts[0],ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Duplicate receipt is not confirmed absent');
 const snapshots=await read({db,heartbeat:()=>verify({github,input,now})});
 const verified=validator.validateDuplicate({before,after,receipt,snapshot:snapshots.snapshot,confirmed:snapshots.confirmed_snapshot,
  audit:evidence,expectedEvidence,now:now()});
 if(verified.receipt_path!==receipts[0])throw Error('Duplicate receipt verification differs');
 const privateFingerprint=fingerprints.fingerprint(snapshots.snapshot);
 const details=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:input.expectedHead}),'Duplicate base commit unavailable');
 if(details.sha!==input.expectedHead||!SHA.test(details.tree_sha||''))throw Error('Duplicate base tree unavailable');
 const additions=[];
 for(const path of paths.sort()){
  const expected=await jsonVerifier.blobIdentity(files[path],{limit:LIMIT});
  const blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Duplicate blob creation failed');
  if(blob.sha!==expected)throw Error('Duplicate blob mismatch');
  additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:details.tree_sha,tree_elements:additions}),'Duplicate tree creation failed');
 if(!SHA.test(tree.sha||''))throw Error('Duplicate tree identity invalid');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,
  expectedHead:input.expectedHead,expectedMain:input.expectedMain,expectedTree:tree.sha,receiptPath:receipts[0],
  receiptBlob:additions.find(x=>x.path===receipts[0]).sha,d1Fingerprint:privateFingerprint};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;
  if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Duplicate fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Duplicate fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Checkpoint bounded content review evidence'});}
  catch{throw Error('Duplicate commit outcome ambiguous; fence remains held');}
  const result=unwrap(update,'Duplicate commit rejected or ambiguous; fence remains held');
  if(result.success!==true||!SHA.test(result.sha||''))throw Error('Duplicate commit outcome ambiguous; fence remains held');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==result.sha)throw Error('Duplicate commit readback differs; reconcile fence');
  return {status:'committed_and_read_back',commit_sha:result.sha,receipt_path:receipts[0],gate:'duplicates',
   candidate_processing:true,native_completion_verified:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Duplicate fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Duplicate commit outcome ambiguous or unconfirmed; reconcile branch and fence');
  throw error;
 }
}
