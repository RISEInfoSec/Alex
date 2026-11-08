// Private service-only handoff of a verified source artifact to the leased
// coordinator. Browsers are refused by the route; no token or signed URL is
// returned. This operation does not pass a gate or modify candidate records.
import {verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import {readSourceArtifact} from './site_actions_artifact.mjs';
import verifier from './verified_git_blob.cjs';
import {findLinearAncestor} from './site_linear_history.mjs';

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
 await checkHeads();await verify({github,input,now,manualScope:'source_retention_only'});
 const state=await verifier.verifiedJson(await github.fetchFile({repository_full_name:REPO,path:WORKER,ref:input.expectedHead,require_content:true}),{limit:LIMIT});
 const pending=state?.current_run?.pending_source_request;
 const runs=[state?.current_run,...(Array.isArray(state?.run_history)?state.run_history:[])];
 const known=runs.flatMap(r=>Array.isArray(r?.accounted_source_requests)?r.accounted_source_requests:[]);
 if(!HASH.test(pending?.request_id||'')&&!known.some(x=>x?.artifact_id===input.artifactId&&x?.native_run_id===input.sourceRunId))
  throw Error('No pending or accounted source request');
 const heartbeat=heartbeatFactory({github,input,now});
 const observed=await artifactReader({getToken,runId:input.sourceRunId,artifactId:input.artifactId,heartbeat});
 let result;try{result=JSON.parse(observed.result_text)}catch{throw Error('Source artifact JSON invalid')}
 const requestId=result?.request_id;
 const entries=known.filter(x=>x?.request_id===requestId);
 const accounted=entries.length===1&&entries[0].artifact_id===input.artifactId&&entries[0].native_run_id===input.sourceRunId&&
  entries[0].artifact_sha256===observed.artifact?.sha256;
 if(!HASH.test(requestId||'')||(!accounted&&pending?.request_id!==requestId)||!SHA.test(observed.native_run?.head_sha||''))
  throw Error('Source artifact does not match a pending or accounted request');
 const reservation=observed.native_run.head_sha;
 const details=async sha=>unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:sha}),'Source handoff history unavailable');
 await findLinearAncestor({github,head:input.expectedHead,ancestor:reservation,heartbeat,details,
  linearError:'Source handoff reservation outside linear history',boundedError:'Source handoff reservation outside bounded history'});
 await checkHeads();await verify({github,input,now,manualScope:'source_retention_only'});
 return {status:'verified_source_artifact',request_id:requestId,native_run:observed.native_run,
  artifact:observed.artifact,result_text:observed.result_text,candidate_processing:false,publication_verified:false};
}
