// Private service-only handoff of a verified source artifact to the leased
// coordinator. Browsers are refused by the route; no token or signed URL is
// returned. This operation does not pass a gate or modify candidate records.
import {verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {readSourceArtifact} from './site_actions_artifact.mjs';
import verifier from './verified_git_blob.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',LIMIT=12*1024*1024;
const SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};
export async function readSourceEvidence({github,getToken,input,now=()=>Date.now(),verify=verifyWorkerContext,
 artifactReader=readSourceArtifact,heartbeatFactory=makeHeartbeatKeeper}){
 if(!github||typeof getToken!=='function'||typeof now!=='function'||typeof verify!=='function'||typeof artifactReader!=='function'||
  typeof heartbeatFactory!=='function'||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['artifactId','expectedHead','expectedMain','owner','runId','sourceRunId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  !Number.isSafeInteger(input.sourceRunId)||input.sourceRunId<1||!Number.isSafeInteger(input.artifactId)||input.artifactId<1)
  throw Error('Invalid source artifact handoff');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile'])if(typeof github[method]!=='function')throw Error('Source handoff GitHub access unavailable');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source handoff branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);
  if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source handoff head changed');};
 await checkHeads();await verify({github,input,now});
 const state=await verifier.verifiedJson(await github.fetchFile({repository_full_name:REPO,path:WORKER,ref:input.expectedHead,require_content:true}),{limit:LIMIT});
 const pending=state?.current_run?.pending_source_request;
 if(!pending||!HASH.test(pending.request_id||''))throw Error('No pending source request');
 const heartbeat=heartbeatFactory({github,input,now});
 const observed=await artifactReader({getToken,runId:input.sourceRunId,artifactId:input.artifactId,heartbeat});
 let result;try{result=JSON.parse(observed.result_text)}catch{throw Error('Source artifact JSON invalid')}
 if(result?.request_id!==pending.request_id||!SHA.test(observed.native_run?.head_sha||''))throw Error('Source artifact does not match pending request');
 const reservation=observed.native_run.head_sha;let cursor=input.expectedHead,found=false;
 for(let i=0;i<20;i++){
  await heartbeat();const item=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:cursor}),'Source handoff history unavailable');
  if(item.sha!==cursor||!Array.isArray(item.parents)||item.parents.some(x=>!SHA.test(x||'')))throw Error('Source handoff history invalid');
  if(cursor===reservation){found=true;break;}if(item.parents.length!==1)throw Error('Source handoff reservation outside linear history');cursor=item.parents[0];
 }
 if(!found)throw Error('Source handoff reservation outside bounded history');
 await checkHeads();await verify({github,input,now});
 return {status:'verified_source_artifact',request_id:pending.request_id,native_run:observed.native_run,
  artifact:observed.artifact,result_text:observed.result_text,candidate_processing:false,publication_verified:false};
}
