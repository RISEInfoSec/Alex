// Reserve one bounded source job. The GitHub push may start the existing
// source workflow; this writer never claims that the workflow ran or that a
// candidate gate passed. The route constructs GitHub and D1 access itself.
import {controlFence,verifyWorkerContext} from './d1_fence_service.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import verifier from './verified_git_blob.cjs';
import guard from './site_source_request_guard.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LEDGER='config/content_review_candidate_lifecycle.json',REGISTRY='config/review_console.json';
const LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const COLLECTIONS=new Set(['weekly','bellingcat','first','m3aawg','sans','soups']);
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};

export async function writeSourceRequest({db,github,input,now=()=>Date.now(),read=reader.readStable,control=controlFence,verify=verifyWorkerContext}){
 if(!db||!github||typeof now!=='function'||typeof read!=='function'||typeof control!=='function'||typeof verify!=='function'||
  !input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['expectedHead','expectedMain','files','owner','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  !input.files||typeof input.files!=='object'||Array.isArray(input.files))throw Error('Invalid source reservation request');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','createBlob','createTree','commitOnBranch'])
  if(typeof github[method]!=='function')throw Error('Source reservation GitHub operation unavailable');
 const files=input.files,paths=Object.keys(files),requests=paths.filter(p=>/^config\/content_review_source_requests\/[0-9a-f]{64}\.json$/.test(p));
 if(paths.length!==2||requests.length!==1||!paths.includes(WORKER)||paths.some(p=>typeof files[p]!=='string')||
  paths.reduce((n,p)=>n+new TextEncoder().encode(files[p]).length,0)>LIMIT)throw Error('Invalid source reservation file inventory');
 let after,request;try{after=JSON.parse(files[WORKER]);request=JSON.parse(files[requests[0]]);}catch{throw Error('Source reservation JSON invalid');}
 if(!request||!HASH.test(request.request_id||'')||requests[0]!=='config/content_review_source_requests/'+request.request_id+'.json'||
  !Array.isArray(request.records)||request.records.length<1||request.records.length>5||
  request.records.some(x=>!x||!COLLECTIONS.has(x.collection)))throw Error('Source reservation identity invalid');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source reservation branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source reservation head changed');};
 await checkHeads();await verify({github,input,now});
 async function readJson(path){
  const result=await github.fetchFile({repository_full_name:REPO,path,ref:input.expectedHead,require_content:true});
  const value=await verifier.verifiedJson(result,{limit:LIMIT}),bytes=new TextEncoder().encode(result.structuredContent.content);
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  return {value,hash};
 }
 const before=(await readJson(WORKER)).value,ledger=(await readJson(LEDGER)).value,registry=(await readJson(REGISTRY)).value;
 const manifests={},manifestHashes={};
 for(const collection of new Set(request.records.map(x=>x.collection))){
  const entries=Array.isArray(registry.collections)?registry.collections.filter(x=>x?.id===collection):[];
  const root='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/config/';
  if(entries.length!==1||!['soups','normalized'].includes(entries[0].adapter)||!entries[0].manifest_url?.startsWith(root))
   throw Error('Source reservation manifest unavailable');
  const name=entries[0].manifest_url.slice(root.length);if(!/^[a-zA-Z0-9_-]+_review_manifest\.json$/.test(name))
   throw Error('Source reservation manifest invalid');
  const value=await readJson('config/'+name);manifests[collection]=value.value;manifestHashes[collection]=value.hash;
 }
 const prior=await github.fetchFile({repository_full_name:REPO,path:requests[0],ref:input.expectedHead});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Source reservation already exists');
 const snapshots=await read({db,heartbeat:()=>verify({github,input,now})});
 const result=guard.validateSourceRequest({before,after,request,manifests,manifestHashes,ledger,snapshot:snapshots.snapshot,
  confirmed:snapshots.confirmed_snapshot,owner:input.owner,runId:input.runId,now:now()});
 if(result.request_path!==requests[0])throw Error('Source reservation identity differs');
 const privateFingerprint=fingerprints.fingerprint(snapshots.snapshot);
 const details=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:input.expectedHead}),'Source reservation base unavailable');
 if(details.sha!==input.expectedHead||!SHA.test(details.tree_sha||''))throw Error('Source reservation base tree invalid');
 const additions=[];
 for(const path of paths.sort()){
  const expected=await verifier.blobIdentity(files[path],{limit:LIMIT});
  const blob=unwrap(await github.createBlob({repository_full_name:REPO,content:files[path],encoding:'utf-8'}),'Source reservation blob failed');
  if(blob.sha!==expected)throw Error('Source reservation blob mismatch');
  additions.push({path,mode:'100644',type:'blob',sha:expected});
 }
 const tree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:details.tree_sha,tree_elements:additions}),'Source reservation tree failed');
 if(!SHA.test(tree.sha||''))throw Error('Source reservation tree invalid');
 if(now()-Date.parse(after.current_run.pending_source_request.prepared_at)>40000)throw Error('Source reservation expired');
 const fence={action:'acquire',operationId:crypto.randomUUID(),owner:input.owner,runId:input.runId,expectedHead:input.expectedHead,
  expectedMain:input.expectedMain,expectedTree:tree.sha,receiptPath:requests[0],receiptBlob:additions.find(x=>x.path===requests[0]).sha,
  d1Fingerprint:privateFingerprint};
 let mayHaveFence=false,commitAttempted=false;
 try{
  mayHaveFence=true;if((await control({db,github,input:fence,now})).status!=='acquired')throw Error('Source reservation fence unavailable');
  if((await control({db,github,input:{...fence,action:'begin'},now})).status!=='committing')throw Error('Source reservation fence did not enter commit');
  commitAttempted=true;let update;
  try{update=await github.commitOnBranch({repository_full_name:REPO,branch_name:REVIEW,expected_sha:input.expectedHead,
   additions:paths.map(path=>({path,content:files[path]})),message:'Reserve bounded source evidence request'});}
  catch{throw Error('Source reservation outcome ambiguous');}
  const committed=unwrap(update,'Source reservation rejected or ambiguous');
  if(committed.success!==true||!SHA.test(committed.sha||''))throw Error('Source reservation outcome ambiguous');
  const released=await control({db,github,input:{...fence,action:'release'},now});
  if(released.status!=='confirmed_and_released'||released.commit_sha!==committed.sha)throw Error('Source reservation readback differs');
  return {status:'committed_and_read_back',commit_sha:committed.sha,request_path:requests[0],
   source_request_limit:result.source_request_limit,source_request_reserved:true,source_workflow_verified:false,
   candidate_processing:false,publication_verified:false};
 }catch(error){
  if(mayHaveFence&&!commitAttempted){let aborted=false;try{aborted=(await control({db,github,input:{...fence,action:'abort'},now})).status==='aborted';}catch{}
   if(!aborted)throw Error('Source reservation fence state unconfirmed; inspect fence');}
  if(commitAttempted)throw Error('Source reservation commit outcome ambiguous or unconfirmed; reconcile branch and fence');
  throw error;
 }
}
